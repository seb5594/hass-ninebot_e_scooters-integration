"""Confirm a scooter pairs before the config flow creates its config entry.

One bounded, self-contained GATT session that never touches a coordinator or
an existing config entry: it runs while the config flow is deciding how to
create one. It tries the classic BLE129 handshake (0x5B/0x5C/0x5D, reused from
runtime/requests.py). The config flow (see config_flow.py's
async_step_pairing_done) creates the entry already paired if it succeeds, or,
as a last resort, unpaired if it does not — the way setup always used to work,
so the scooter still pairs itself on the next live advertisement.
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
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant

from ..helpers.utilities import TIMEOUT_ERRORS
from ..protocols.gatt import find_uart_characteristics
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


@dataclass(frozen=True, slots=True)
class PairingOutcome:
    """What one config-flow pairing attempt established, if anything."""

    protocol: str | None  # None or "ble129".
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


async def async_attempt_pairing(hass: HomeAssistant, ble_device: Any, device_name: str, flow_id: str) -> PairingOutcome:
    """Try the classic BLE129 pairing handshake once, before any entry exists.

    Used only by the config flow. Always disconnects and dismisses its own
    notice before returning. On failure the outcome carries no protocol, and
    the flow adds the scooter unpaired, to pair on the next live advertisement.
    """
    notification_id = f"ninebot_e_scooters_pair_{flow_id}"
    app_key = secrets.token_bytes(16)
    if ble_device is None:
        # A discovered service_info can carry no BLEDevice (not connectable,
        # or the advertisement has already expired); nothing to connect to.
        return PairingOutcome(None, None, "no connectable Bluetooth device was available")
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
            return PairingOutcome(None, None, str(classic_error))
    finally:
        persistent_notification.async_dismiss(hass, notification_id)
        try:
            if client.is_connected:
                await client.disconnect()
        except (BleakError, *TIMEOUT_ERRORS):
            pass
