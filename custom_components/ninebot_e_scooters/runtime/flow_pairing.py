"""Confirm a scooter pairs before the config flow creates its config entry.

One bounded, self-contained GATT session that never touches a coordinator or
an existing config entry: it runs while the config flow is deciding how to
create one. The classic BLE129 handshake (0x5B/0x5C/0x5D, reused from
runtime/requests.py) is tried first; if it fails for any reason, the newer
MIoT elliptic handshake (protocols/miot_elliptic.py) is tried on the same
connection before giving up, since some newer Xiaomi scooters do not speak
BLE129 at all. The config flow (see config_flow.py's async_step_pairing_done)
creates the entry already paired if either one succeeds, or, as a last
resort, unpaired if both fail — the way setup always used to work, so the
scooter still pairs itself on the next live advertisement.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass
from typing import Any

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from cryptography.exceptions import InvalidTag
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant

from ..helpers.utilities import TIMEOUT_ERRORS
from ..helpers.utilities import timeout as async_timeout
from ..protocols.gatt import find_uart_characteristics
from ..protocols.miot_elliptic import (
    MIOT_ELLIPTIC_PAIRING_CHARACTERISTIC,
    MIOT_PAIR_CHAL_1,
    MIOT_PAIR_CHAL_2,
    MIOT_PAIR_EC_END,
    MIOT_PAIR_EC_START,
    MIOT_PAIR_OK,
    MIOT_PAIR_OK_ACK,
    MIOT_PAIR_REQ,
    MIOT_PAIR_REQ_OK,
    MIOT_PAIR_SOL_ACK,
    miot_elliptic_derive_pairing_keys,
    miot_elliptic_fragment,
    miot_elliptic_generate_keypair,
    miot_elliptic_load_peer_point,
    miot_elliptic_pairing_response,
    miot_elliptic_public_point,
    miot_elliptic_shared_secret,
)
from ..protocols.ninebot.crypto import NinebotCrypto
from ..protocols.ninebot.packet import (
    BLE129_APP_KEY_LENGTH,
    BLE129_INIT_REPLY_LENGTH,
    CMD_INIT,
    CMD_PAIR,
    CMD_PING,
    DeviceId,
    PairingStatus,
    make_init,
    make_pair,
    make_ping,
)
from .constants import DIRECT_GATT_TIMEOUT, PAIRING_REPLY_TIMEOUT, PAIRING_RETRY_PAUSE, PAIRING_TIMEOUT
from .errors import ScooterConnectionError
from .requests import RequestsMixin

_LOGGER = logging.getLogger(__name__)

# The paper's pairable window is seventeen seconds after the headlight button
# is held; this adds margin for the GATT exchange itself around it.
MIOT_ELLIPTIC_PAIRING_WINDOW = 30.0
MIOT_ELLIPTIC_STEP_TIMEOUT = 10.0


@dataclass(frozen=True, slots=True)
class PairingOutcome:
    """What one config-flow pairing attempt established, if anything."""

    protocol: str | None  # None, "ble129" or "xiaomi_mi_ec".
    app_key: bytes | None
    error: str | None


class _FlowPairingSession(RequestsMixin):
    """The minimal state runtime.requests.RequestsMixin needs, reused as-is
    for this one bounded attempt instead of duplicating its frame
    reassembly and response-matching logic."""

    def __init__(self, client: BleakClient) -> None:
        self._client = client
        self._tx_char: Any | None = None
        self._rx_char: Any | None = None
        self._crypto: NinebotCrypto | None = None
        self._host_id = DeviceId.PHONE
        self._handshake_board = DeviceId.DASHBOARD
        self._packet_queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=32)
        self._rx_buffer = bytearray()
        self._stage = "config_flow_pairing"
        self._shutting_down = False
        self._raw_notification_count = 0
        self._rejected_crypto_frames = 0
        self._last_frame_issue: str | None = None
        self._last_reply_command: str | None = None
        self._last_rejected_frame_counter16: int | None = None
        self._last_notification: str | None = None
        self._pending_pair_confirmation = None
        self._pending_pair_ack = None


def _async_show_pairing_notice(hass: HomeAssistant, notification_id: str) -> None:
    """Raise the same notice pairing_dialog.js already watches for by its ID
    prefix and title, so its power-button dialog opens during this flow."""
    persistent_notification.async_create(
        hass,
        "Bitte jetzt einmal kurz die Einschalttaste am Scooter drücken, um das Pairing "
        "während der Einrichtung zu bestätigen. Lass den Scooter eingeschaltet.\n\n"
        '<p align="center"><img alt="Animation: Einschalttaste am Scooter kurz drücken" '
        'src="/api/ninebot_e_scooters/power_button.gif"></p>',
        title="Ninebot/Xiaomi Scooter – Pairing jetzt bestätigen",
        notification_id=notification_id,
    )


async def _async_connect(ble_device: Any, device_name: str) -> BleakClient:
    """One direct connection attempt; no retry scheduling, no entry lifecycle."""
    client = await establish_connection(
        BleakClientWithServiceCache, ble_device, device_name,
        max_attempts=1, use_services_cache=False, timeout=DIRECT_GATT_TIMEOUT,
    )
    if not client.is_connected:
        raise ScooterConnectionError("BleakClient.connect returned without an active connection")
    return client


async def _async_attempt_classic_pairing(
    client: BleakClient, device_name: str, app_key: bytes, hass: HomeAssistant, notification_id: str,
) -> None:
    """Try the existing BLE129 0x5B -> 0x5C -> 0x5D handshake on `client`."""
    tx_char, rx_char = find_uart_characteristics(client.services)
    if tx_char is None or rx_char is None:
        raise ScooterConnectionError("Scooter UART write/notify characteristics are missing")

    session = _FlowPairingSession(client)
    session._tx_char = tx_char
    session._rx_char = rx_char
    session._crypto = NinebotCrypto(device_name)

    def notification_handler(_characteristic: Any, payload: bytearray) -> None:
        if session._client is client and client.is_connected:
            session._handle_notification(bytes(payload))

    await client.start_notify(rx_char, notification_handler, bluez={"use_start_notify": True})
    await asyncio.sleep(0.40)

    init_response = await session._async_crypto_request(
        make_init(), expected_commands={CMD_INIT}, timeout=2.5, accept_timeout=True, quiet_timeout=True,
    )
    if init_response is None or len(init_response.data) < BLE129_INIT_REPLY_LENGTH:
        raise ScooterConnectionError("BLE129 0x5B unanswered or malformed; not a classic Ninebot/Xiaomi scooter")
    pairing_serial = init_response.data[BLE129_APP_KEY_LENGTH:BLE129_INIT_REPLY_LENGTH]

    deadline = asyncio.get_running_loop().time() + PAIRING_TIMEOUT
    notice_shown = False
    confirmed = False
    while asyncio.get_running_loop().time() < deadline:
        response = await session._async_crypto_request(
            make_ping(app_key), expected_commands={CMD_PING}, timeout=PAIRING_REPLY_TIMEOUT,
            accept_timeout=True, quiet_timeout=True,
        )
        if response is not None and response.index == PairingStatus.CONFIRMED:
            confirmed = True
            break
        if not notice_shown:
            notice_shown = True
            _async_show_pairing_notice(hass, notification_id)
        await asyncio.sleep(PAIRING_RETRY_PAUSE)
    if not confirmed:
        raise ScooterConnectionError("BLE129 pairing timed out waiting for the power-button confirmation")

    for attempt in range(3):
        confirm = await session._async_crypto_request(
            make_pair(pairing_serial), expected_commands={CMD_PAIR}, timeout=2.5, accept_timeout=True,
        )
        if confirm is not None and confirm.index == PairingStatus.CONFIRMED:
            return
        if attempt < 2:
            await asyncio.sleep(0.5)
    raise ScooterConnectionError("BLE129 0x5C01 was received but 0x5D01 was not")


async def _async_attempt_miot_elliptic_pairing(
    client: BleakClient, hass: HomeAssistant, notification_id: str,
) -> None:
    """Try the newer MIoT elliptic (P4) pairing handshake on `client`.

    Any unexpected reply or timeout raises ScooterConnectionError rather than
    guessing further; see protocols/miot_elliptic.py for exactly which parts
    of this sequence the cited paper confirms.
    """
    characteristic = client.services.get_characteristic(MIOT_ELLIPTIC_PAIRING_CHARACTERISTIC)
    if characteristic is None:
        raise ScooterConnectionError("Scooter has no MIoT elliptic pairing characteristic")

    _async_show_pairing_notice(hass, notification_id)
    inbox: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)

    def on_notify(_characteristic: Any, payload: bytearray) -> None:
        if inbox.full():
            inbox.get_nowait()
        inbox.put_nowait(bytes(payload))

    await client.start_notify(characteristic, on_notify)
    try:
        async def write(frame: bytes) -> None:
            await client.write_gatt_char(characteristic, frame, response=False)

        async def expect(prefix: bytes, timeout: float) -> bytes:
            async with async_timeout(timeout):
                while True:
                    frame = await inbox.get()
                    if frame.startswith(prefix):
                        return frame

        await write(MIOT_PAIR_REQ)
        await expect(MIOT_PAIR_REQ_OK, MIOT_ELLIPTIC_PAIRING_WINDOW)

        chal_1 = await expect(MIOT_PAIR_CHAL_1, MIOT_ELLIPTIC_STEP_TIMEOUT)
        chal_2 = await expect(MIOT_PAIR_CHAL_2, MIOT_ELLIPTIC_STEP_TIMEOUT)
        challenge = chal_1[len(MIOT_PAIR_CHAL_1):] + chal_2[len(MIOT_PAIR_CHAL_2):]
        if len(challenge) != 16:
            raise ScooterConnectionError(f"Unexpected MIoT elliptic challenge length: {len(challenge)}")

        private_key = miot_elliptic_generate_keypair()
        own_point = miot_elliptic_public_point(private_key)
        await write(MIOT_PAIR_EC_START)
        for fragment in miot_elliptic_fragment(own_point):
            await write(fragment)
        await write(MIOT_PAIR_EC_END)

        peer_point = bytearray(64)
        expected_offsets = {0x0000, 0x0010, 0x0020, 0x0030}
        collected: set[int] = set()
        deadline = asyncio.get_running_loop().time() + MIOT_ELLIPTIC_STEP_TIMEOUT
        while collected != expected_offsets:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise ScooterConnectionError("Timed out collecting the scooter's MIoT elliptic public key")
            frame = await asyncio.wait_for(inbox.get(), timeout=remaining)
            if len(frame) <= 2:
                continue
            offset = int.from_bytes(frame[:2], "big")
            if offset not in expected_offsets:
                continue
            chunk = frame[2:]
            peer_point[offset:offset + len(chunk)] = chunk
            collected.add(offset)

        shared_secret = miot_elliptic_shared_secret(
            private_key, miot_elliptic_load_peer_point(bytes(peer_point))
        )
        derived = miot_elliptic_derive_pairing_keys(shared_secret)
        one_time_key = derived[16:]
        # otk is fresh every pairing attempt (a new ECDH keypair each time),
        # so a fixed nonce for this single encryption cannot be reused across
        # sessions; the paper does not name the real one. See the module
        # docstring in protocols/miot_elliptic.py.
        proof_nonce = b"\x00" * 12
        response = miot_elliptic_pairing_response(one_time_key, proof_nonce, challenge)
        for fragment in miot_elliptic_fragment(response):
            await write(fragment)
        await expect(MIOT_PAIR_SOL_ACK, MIOT_ELLIPTIC_STEP_TIMEOUT)

        await write(MIOT_PAIR_OK)
        await expect(MIOT_PAIR_OK_ACK, MIOT_ELLIPTIC_STEP_TIMEOUT)
    except (BleakError, InvalidTag, ValueError, *TIMEOUT_ERRORS) as err:
        raise ScooterConnectionError(f"MIoT elliptic pairing failed: {type(err).__name__}: {err}") from err
    finally:
        try:
            await client.stop_notify(characteristic)
        except (BleakError, *TIMEOUT_ERRORS):
            pass


async def async_attempt_pairing(hass: HomeAssistant, ble_device: Any, device_name: str, flow_id: str) -> PairingOutcome:
    """Try classic BLE129 pairing, then the MIoT elliptic handshake as a fallback.

    Used only by the config flow, before any config entry exists. Always
    disconnects and dismisses its own notice before returning.
    """
    notification_id = f"ninebot_e_scooters_pair_{flow_id}"
    app_key = secrets.token_bytes(16)
    try:
        client = await _async_connect(ble_device, device_name)
    except (BleakError, *TIMEOUT_ERRORS) as err:
        return PairingOutcome(None, None, f"{type(err).__name__}: {err}")

    try:
        _async_show_pairing_notice(hass, notification_id)
        try:
            await _async_attempt_classic_pairing(client, device_name, app_key, hass, notification_id)
            return PairingOutcome("ble129", app_key, None)
        except ScooterConnectionError as classic_error:
            if not client.is_connected:
                return PairingOutcome(None, None, str(classic_error))
            _LOGGER.info(
                "Scooter classic BLE129 pairing failed (%s); trying the MIoT elliptic handshake",
                classic_error,
            )
            try:
                await _async_attempt_miot_elliptic_pairing(client, hass, notification_id)
                return PairingOutcome("xiaomi_mi_ec", app_key, None)
            except ScooterConnectionError as elliptic_error:
                return PairingOutcome(None, None, f"{classic_error}; {elliptic_error}")
    finally:
        persistent_notification.async_dismiss(hass, notification_id)
        try:
            if client.is_connected:
                await client.disconnect()
        except (BleakError, *TIMEOUT_ERRORS):
            pass
