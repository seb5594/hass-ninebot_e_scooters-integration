"""Authenticate one persistent session while retaining the saved application key."""

from __future__ import annotations
import asyncio
from dataclasses import replace
from datetime import datetime
from typing import Any
from bleak.exc import BleakError
from homeassistant.components import persistent_notification
from ..const import NUS_NOTIFY_UUID, NUS_WRITE_UUID
from ..protocols.legacy import LegacyM365Link
from ..protocols.ninebot.crypto import NinebotCrypto
from ..protocols.ninebot.packet import (
    CMD_INIT,
    CMD_PAIR,
    CMD_PING,
    CMD_READ,
    CMD_READ_ACK,
    TARGET_ESC,
    make_init,
    make_pair,
    make_ping,
    make_read,
)
from ..protocols.ninebot.packet import (
    BLE129_APP_KEY_LENGTH,
    BLE129_INIT_REPLY_LENGTH,
    DeviceId,
    PairingStatus,
    RegisterReadSize,
    Xiaomi1sEscRegister,
    Xiaomi1sFastTelemetry,
)
from ..utilities import UTC, TIMEOUT_ERRORS
from .errors import ScooterConnectionError
from .constants import (
    MAX_ADVERTISEMENT_AGE,
    PAIRING_REPLY_TIMEOUT,
    PAIRING_RETRY_INTERVAL,
    PAIRING_RETRY_PAUSE,
    PAIRING_TIMEOUT,
    STORED_KEY_RECOVERY_TIMEOUT,
)
import logging

_LOGGER = logging.getLogger(__name__)


class SessionMixin:
    """Session operations on the coordinator session."""

    async def _async_ensure_session(self) -> None:
        """Connect once and complete the BLE129 handshake once per session."""
        if self._session_ready and self._client and self._client.is_connected:
            return

        transport = getattr(self, "transport_profile", None)
        if transport is not None and not transport.adapter_implemented:
            raise ScooterConnectionError("This model requires an authentication protocol that is not implemented")

        if getattr(self, "_uses_legacy_m365", lambda: False)():
            await self._async_ensure_legacy_session()
            return

        ble_device = self._pending_ble_device
        advertised_name = getattr(self, "_pending_ble_name", None)
        age = asyncio.get_running_loop().time() - self._pending_seen_at
        # Consume before the first await; a subsequent polling refresh must
        # never retry against the same stale BlueZ object.
        self._pending_ble_device = None
        self._pending_ble_name = None
        if ble_device is None or age > MAX_ADVERTISEMENT_AGE:
            raise ScooterConnectionError(
                "A fresh connectable scooter advertisement is required before GATT connect"
            )

        self._stage = "gatt_connect"
        self._rx_buffer.clear()
        self._pending_pair_confirmation = None
        self._pending_pair_ack = None
        while not self._packet_queue.empty():
            try:
                self._packet_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # BLE129 derives its first key from the on-air Bluetooth name. An
        # older entry may retain a manually entered or renamed device title.
        # Prefer the name of this *fresh* HA advertisement, then BLEDevice.
        device_name = getattr(ble_device, "name", None)
        if (isinstance(advertised_name, str) and advertised_name.strip()
                and advertised_name.upper() != self.address.upper()):
            crypto_name = advertised_name.strip()
            self._crypto_name_source = "live_advertisement"
        elif (isinstance(device_name, str) and device_name.strip()
              and device_name.upper() != self.address.upper()):
            crypto_name = device_name.strip()
            self._crypto_name_source = "ble_device"
        else:
            crypto_name = self.device_name
            self._crypto_name_source = "saved_entry"
        self._crypto_name_matches_saved = crypto_name == self.device_name
        _LOGGER.info(
            "Scooter BLE129 crypto name source=%s saved_name_matches=%s",
            self._crypto_name_source, self._crypto_name_matches_saved,
        )
        host_id = getattr(self, "_host_id", DeviceId.PHONE)
        self._crypto = (
            NinebotCrypto(crypto_name) if host_id == DeviceId.PHONE
            else NinebotCrypto(crypto_name, host_id=host_id)
        )
        # Keep optional-probe progress through short reconnects.
        self._next_setting_read_at.clear()
        self._empty_read_count = 0
        self._authentication_mode = None
        self._initial_telemetry = None
        self._raw_notification_count = 0
        self._notification_callback_errors = 0
        self._rejected_crypto_frames = 0
        self._last_frame_issue = None
        self._last_rejected_frame_counter16 = None
        self._last_notification = None
        self._gatt_attempt_active = True
        try:
            self._client = await self._async_establish_client(ble_device)
            # Capture this exact client for notifications. Referencing an
            # unbound local here silently loses every 0x5B reply in Bleak's
            # callback dispatcher, while the GATT link can still beep.
            client = self._client
            # Access services immediately after establish_connection(). This
            # confirms that BlueZ service discovery is complete before any
            # characteristic object is retained for notifications/writes.
            services = self._client.services
            self._last_services = tuple(
                str(service.uuid).lower()
                for service in services
            )
            self._stage = "gatt_characteristics"
            _LOGGER.info("Scooter BLE phase: %s", self._stage)
            self._tx_char = self._client.services.get_characteristic(NUS_WRITE_UUID)
            self._rx_char = self._client.services.get_characteristic(NUS_NOTIFY_UUID)
            if self._tx_char is None or self._rx_char is None:
                raise ScooterConnectionError(
                    "Xiaomi BLE UART write/notify characteristics are missing"
                )

            _LOGGER.debug(
                "Xiaomi NUS write characteristic: uuid=%s handle=%s properties=%s",
                self._tx_char.uuid,
                getattr(self._tx_char, "handle", None),
                self._tx_char.properties,
            )
            _LOGGER.debug(
                "Xiaomi NUS notify characteristic: uuid=%s handle=%s properties=%s",
                self._rx_char.uuid,
                getattr(self._rx_char, "handle", None),
                self._rx_char.properties,
            )

            # Some BlueZ devices need a short settle time before the first
            # GATT write after notifications have been enabled.
            await asyncio.sleep(0.40)

            def notification_handler(_characteristic: Any, payload: bytearray) -> None:
                if self._client is client and client.is_connected:
                    try:
                        self._handle_notification(bytes(payload))
                    except Exception:
                        self._notification_callback_errors += 1
                        self._last_frame_issue = "notification_callback_exception"
                        if self._packet_queue.full():
                            self._packet_queue.get_nowait()
                        self._packet_queue.put_nowait(None)
                        _LOGGER.exception("Scooter BLE notification callback failed")

            self._stage = "gatt_start_notify"
            _LOGGER.info("Scooter BLE phase: %s", self._stage)
            await self._client.start_notify(
                self._rx_char,
                notification_handler,
                bluez={"use_start_notify": True},
            )
            await asyncio.sleep(0.15)

            self._stage = "ble129_init_5b"
            _LOGGER.info("Scooter BLE phase: %s", self._stage)
            # Repeat the identical counter-zero bootstrap frame while the
            # GATT link is alive. Re-encrypting it would advance the crypto
            # counter before the scooter has accepted the first packet.
            init_request = make_init()
            if host_id != DeviceId.PHONE:
                init_request = replace(init_request, source=host_id)
            init_frame = self._crypto.encrypt(init_request.pack())
            init_response = None
            for init_attempt in range(3):
                if init_attempt:
                    await asyncio.sleep(0.15)
                init_response = await self._async_crypto_request(
                    init_request, expected_commands={CMD_INIT}, timeout=2.0,
                    accept_timeout=True, quiet_timeout=True,
                    encrypted_override=init_frame,
                )
                if init_response is not None:
                    break
            if (init_response is None and self._raw_notification_count == 0
                    and self._client is not None and self._client.is_connected):
                # A GATT connection and a successful CCC subscription do not
                # guarantee that BlueZ is delivering notifications. Re-arm
                # the existing subscription once before discarding this link.
                self._stage = "ble129_rearm_notifications"
                try:
                    await self._client.stop_notify(self._rx_char)
                    await self._client.start_notify(
                        self._rx_char, notification_handler,
                        bluez={"use_start_notify": True},
                    )
                    await asyncio.sleep(0.15)
                    self._stage = "ble129_init_5b"
                    init_response = await self._async_crypto_request(
                        init_request, expected_commands={CMD_INIT}, timeout=2.0,
                        accept_timeout=True, quiet_timeout=True,
                        encrypted_override=init_frame,
                    )
                except (BleakError, *TIMEOUT_ERRORS) as err:
                    _LOGGER.debug("Scooter NUS notification resubscription failed: %s", err)
                    self._stage = "ble129_init_5b"
            if init_response is None:
                _LOGGER.warning(
                    "Scooter BLE129 0x5B unanswered after retries on one GATT link "
                    "(notifications=%d, rejected=%d, last_frame_issue=%s)",
                    self._raw_notification_count, self._rejected_crypto_frames,
                    self._last_frame_issue,
                )
                raise ScooterConnectionError(
                    "BLE129 0x5B unanswered after notification resubscription "
                    f"(notifications={self._raw_notification_count}, "
                    f"rejected={self._rejected_crypto_frames})"
                )
            if self._crypto is None or len(init_response.data) < BLE129_INIT_REPLY_LENGTH:
                raise ScooterConnectionError(
                    f"Invalid BLE129 0x5B reply length: {len(init_response.data)}"
                )

            self._pairing_serial = init_response.data[BLE129_APP_KEY_LENGTH:BLE129_INIT_REPLY_LENGTH]
            self._identify_serial(self._pairing_serial)

            probe_request = make_read(TARGET_ESC, Xiaomi1sEscRegister.FAST_TELEMETRY, RegisterReadSize.FAST_TELEMETRY)
            probe_minimum = Xiaomi1sFastTelemetry.MINIMUM_PAYLOAD
            if getattr(self, "_uses_ninebot", lambda: False)():
                probe_request = make_read(DeviceId.BMS, 0x32, RegisterReadSize.WORD)
                probe_minimum = RegisterReadSize.WORD

            if self._pairing_completed:
                # BLE129 can serve encrypted reads after 0x5B without a new
                # 0x5C key exchange. A verified ESC reply avoids a fresh
                # button confirmation on firmware that supports this path.
                self._stage = "ble129_saved_session_probe"
                read_probe = await self._async_crypto_request(
                    probe_request,
                    expected_commands={CMD_READ, CMD_READ_ACK},
                    timeout=1.5, accept_timeout=True, quiet_timeout=True,
                )
                if read_probe is not None and len(read_probe.data) >= probe_minimum:
                    self._session_ready = True
                    self._authentication_mode = "verified_read_after_5b"
                    self._control_session_started_at = datetime.now(UTC)
                    self._stage = "ble129_session_ready"
                    self._initial_telemetry = read_probe
                    _LOGGER.info("Scooter resumed saved BLE session without key exchange")
                    return
                # "paired" is only a local record that 0x5D/0x01 was received
                # previously. 0x5C is a key-exchange request, NOT a generic
                # keepalive; BLE129 firmwares can demand button confirmation
                # again on a new encrypted GATT session. Never rotate the key.
                self._stage = "ble129_existing_key_5c"
                _LOGGER.info("Scooter BLE phase: %s", self._stage)
                for attempt in range(2):
                    response = await self._async_crypto_request(
                        make_ping(self._app_key),
                        expected_commands={CMD_PING},
                        timeout=1.0,
                        accept_timeout=True,
                        quiet_timeout=True,
                    )
                    if response is not None:
                        if response.index not in (PairingStatus.PENDING, PairingStatus.CONFIRMED):
                            raise ScooterConnectionError(
                                f"Unexpected BLE129 0x5C response argument: {response.index:02X}"
                            )
                        if response.index == PairingStatus.CONFIRMED:
                            # The scooter explicitly confirmed this key for the
                            # new session. Complete the documented 0x5D step
                            # before considering authentication ready.
                            await self._async_confirm_pairing_5d()
                            self._session_ready = True
                            self._authentication_mode = "stored_key_exchange"
                            self._control_session_started_at = datetime.now(UTC)
                            self._stage = "ble129_session_ready"
                            _LOGGER.info("Scooter BLE phase: %s (stored key)", self._stage)
                            return
                        # 0x5C00 acknowledges a key, but the firmware has not
                        # confirmed pairing. Only 0x5C01 + 0x5D01 or a
                        # verified telemetry reply may authorize this session.
                        _LOGGER.info("Scooter acknowledged stored key without confirming pairing")
                        self._stage = "ble129_5c00_verified_probe"
                        verified = await self._async_crypto_request(
                            probe_request,
                            expected_commands={CMD_READ, CMD_READ_ACK},
                            timeout=1.5, accept_timeout=True, quiet_timeout=True,
                        )
                        saved_pair_ack = None
                        if verified is None or len(verified.data) < probe_minimum:
                            # A saved key may be acknowledged with 0x5C00;
                            # some dashboard implementations accept the saved
                            # serial via 0x5D without another button press.
                            # Try once, and only trust a verified 0xB0 reply.
                            self._stage = "ble129_saved_key_5d_probe"
                            saved_pair_ack = await self._async_crypto_request(
                                make_pair(self._pairing_serial),
                                expected_commands={CMD_PAIR},
                                timeout=1.25, accept_timeout=True, quiet_timeout=True,
                            )
                            if saved_pair_ack is not None and saved_pair_ack.index == PairingStatus.CONFIRMED:
                                self._stage = "ble129_saved_key_5d_verified_probe"
                                verified = await self._async_crypto_request(
                                    probe_request,
                                    expected_commands={CMD_READ, CMD_READ_ACK},
                                    timeout=1.5, accept_timeout=True, quiet_timeout=True,
                                )
                        if verified is not None and len(verified.data) >= probe_minimum:
                            self._initial_telemetry = verified
                            self._session_ready = True
                            self._authentication_mode = (
                                "stored_key_5d_verified" if saved_pair_ack is not None
                                else "verified_read_after_5c00"
                            )
                            self._control_session_started_at = datetime.now(UTC)
                            self._stage = "ble129_session_ready"
                            _LOGGER.info("Scooter resumed stored key after verified 0x5C00 ESC reply")
                            return
                        break
                    if attempt == 0:
                        self._existing_key_retries += 1
                        _LOGGER.info(
                            "Scooter did not answer first stored-key 0x5C; "
                            "retrying once on same GATT session"
                        )
                        await asyncio.sleep(0.15)

                # Some BLE129 dashboards acknowledge the saved serial only
                # after another 0x5D attempt, without a new button event.
                # An authenticated ESC reply must still prove the session.
                if getattr(self, "_pending_pair_confirmation", None) is not None:
                    try:
                        await self._async_confirm_pairing_5d()
                    except ScooterConnectionError:
                        # A delayed 0x5D01 can be missed on this firmware.
                        # A valid encrypted ESC reply below still proves the
                        # stored key; otherwise the button path remains open.
                        _LOGGER.debug("Saved-key 0x5D ACK missed; probing authenticated ESC")
                else:
                    for saved_attempt in range(2):
                        saved_ack = await self._async_crypto_request(
                            make_pair(self._pairing_serial),
                            expected_commands={CMD_PAIR},
                            timeout=1.0, accept_timeout=True, quiet_timeout=True,
                        )
                        if saved_ack is not None and saved_ack.index == PairingStatus.CONFIRMED:
                            break
                        if saved_attempt == 0:
                            await asyncio.sleep(0.15)
                saved_read = await self._async_crypto_request(
                    probe_request,
                    expected_commands={CMD_READ, CMD_READ_ACK},
                    timeout=1.25, accept_timeout=True, quiet_timeout=True,
                )
                if saved_read is not None and len(saved_read.data) >= probe_minimum:
                    self._initial_telemetry = saved_read
                    self._session_ready = True
                    self._authentication_mode = "stored_key_late_5d_verified"
                    self._control_session_started_at = datetime.now(UTC)
                    self._stage = "ble129_session_ready"
                    return

                # The old integration disconnected here after about seven
                # seconds, before a person could confirm the pending 0x5C.
                # Reuse the EXACT saved key on the same GATT connection and
                # explicitly offer the button-confirmation path (no re-pair
                # entry creation and no key reset).
                _LOGGER.info(
                    "BLE129 stored-key 0x5C had no early acknowledgement; "
                    "waiting for power-button confirmation with the saved key"
                )
                self._stage = "ble129_stored_key_confirmation"
                await self._async_pair_current_session(reuse_stored_key=True)
                self._session_ready = True
                self._authentication_mode = "stored_key_reconfirmed"
                self._control_session_started_at = datetime.now(UTC)
                self._stage = "ble129_session_ready"
                _LOGGER.info("Scooter BLE phase: %s (stored key reconfirmed)", self._stage)
                return

            self._stage = "ble129_pairing_5c_5d"
            _LOGGER.info("Scooter BLE phase: %s", self._stage)
            await self._async_pair_current_session()
            self._session_ready = True
            self._authentication_mode = "first_pairing"
            self._control_session_started_at = datetime.now(UTC)
            self._stage = "ble129_session_ready"
            _LOGGER.info("Scooter BLE phase: %s", self._stage)

        except (BleakError, *TIMEOUT_ERRORS) as err:
            # For GATT failures, wait briefly and require a NEW
            # live advertisement/BlueZ BLEDevice before the next attempt.
            # Handshake failures retain the longer cooldown to avoid flooding
            # an already connected scooter with authentication packets.
            cooldown = self._gatt_retry_cooldown if self._stage == "gatt_connect" else 15.0
            self._retry_not_before = asyncio.get_running_loop().time() + cooldown
            self._remember_failed_session(type(err).__name__)
            await self._async_disconnect()
            error = (
                f"Scooter BLE phase '{self._stage}' failed: "
                f"{type(err).__name__}: {err!r}; "
                f"last_notification={'yes' if self._last_notification else 'no'}"
            )
            # UpdateFailed is logged once by HA coordinator. A second ERROR
            # traceback here duplicated every expected radio timeout.
            _LOGGER.debug(error, exc_info=True)
            raise ScooterConnectionError(error) from err

    async def _async_pair_current_session(self, *, reuse_stored_key: bool = False) -> None:
        """Pair with BLE129 on the *current* GATT connection.

        Firmware may send no 0x5C00; do not assume silence means the key is
        wrong. Wait for 0x5C01 after the user physically confirms pairing.
        Transient pairing timeouts must not permanently disable future live
        advertisement retries or silently rotate the persisted application key.
        """
        if self._pairing_serial is None:
            raise ScooterConnectionError("Scooter serial is missing from 0x5B reply")

        notification_id = f"ninebot_e_scooters_pair_{self.entry.entry_id}"
        wait_seconds = STORED_KEY_RECOVERY_TIMEOUT if reuse_stored_key else PAIRING_TIMEOUT
        pairing_description = (
            "die Anmeldung mit dem **gespeicherten** App-Key für diese Verbindung zu bestätigen"
            if reuse_stored_key
            else "den **neuen** Home-Assistant-App-Key zu bestätigen"
        )
        # Repeat attempts may still require confirmation on this firmware;
        # the same persistent message should not flood HA's activity feed.
        # Reconnection must restore a dismissed/failed notice when a button
        # press is required again; the old 15-minute gate hid that request.
        show_notice = False
        deadline = asyncio.get_running_loop().time() + wait_seconds
        completed_in_this_attempt = False
        attempts = 0
        try:
            while asyncio.get_running_loop().time() < deadline:
                next_request_at = asyncio.get_running_loop().time() + PAIRING_RETRY_INTERVAL
                attempts += 1
                response = await self._async_crypto_request(
                    make_ping(self._app_key),
                    expected_commands={CMD_PING},
                    timeout=PAIRING_REPLY_TIMEOUT,
                    accept_timeout=True,
                    quiet_timeout=True,
                )
                if response is not None:
                    _LOGGER.info(
                        "BLE129 0x5C response: index=%02X payload_len=%d",
                        response.index, len(response.data),
                    )
                    if response.index == PairingStatus.CONFIRMED:
                        break
                if not show_notice:
                    show_notice = True
                    self._last_pairing_notice_at = asyncio.get_running_loop().time()
                    _LOGGER.info(
                        "Scooter BLE129 0x5C requires physical confirmation "
                        "(saved_key=%s, window=%.0fs)", reuse_stored_key, wait_seconds,
                    )
                    persistent_notification.async_create(
                        self.hass,
                        "**Bluetooth ist verbunden; BLE129 `0x5B` war erfolgreich.** "
                        "Bitte **jetzt einmal kurz die Einschalttaste am Scooter drücken**, um "
                        f"{pairing_description}. "
                        "Der gespeicherte Schlüssel wird nicht geändert. "
                        "Lass den Scooter eingeschaltet und schließe andere Scooter-Apps. "
                        f"Zeitfenster: ungefähr {wait_seconds:.0f} Sekunden.\n\n"
                        '<p align="center"><img alt="Animation: Einschalttaste am Scooter kurz drücken" '
                        'src="/api/ninebot_e_scooters/power_button.gif"></p>',
                        title=("Ninebot/Xiaomi Scooter – Gespeicherten Schlüssel bestätigen"
                               if reuse_stored_key else "Ninebot/Xiaomi Scooter – Pairing jetzt bestätigen"),
                        notification_id=notification_id,
                    )
                if attempts == 1 or attempts % 10 == 0:
                    _LOGGER.info(
                        "BLE129 waiting for scooter power-button confirmation: "
                        "0x5C attempts=%d, time_remaining=%.1fs, "
                        "notifications=%d, rejected_frames=%d",
                        attempts, max(0, deadline - asyncio.get_running_loop().time()),
                        self._raw_notification_count, self._rejected_crypto_frames,
                    )
                # Repeated immediate 0x5C00 replies must not consume dozens
                # of crypto counters while the user reaches the button.
                await asyncio.sleep(min(max(0, deadline - asyncio.get_running_loop().time()),
                                        max(PAIRING_RETRY_PAUSE, next_request_at - asyncio.get_running_loop().time())))
            else:
                raise ScooterConnectionError(
                    "BLE129 pairing timed out waiting for scooter power-button "
                    "confirmation (0x5C01). The key remains saved. The next "
                    "live advertisement can retry without deleting/reloading "
                    "the integration. If the button was pressed: inspect "
                    "notification and rejected-frame diagnostics."
                )

            _LOGGER.info("Scooter accepted BLE129 0x5C01; confirming 0x5D")
            await self._async_confirm_pairing_5d()
            if not self._pairing_completed:
                self._pairing_completed = True
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data={**self.entry.data, "app_key": self._app_key.hex(), "paired": True},
                )
            completed_in_this_attempt = True
            _LOGGER.info("Xiaomi Scooter BLE129 pairing completed (saved_key=%s)", reuse_stored_key)
            return
        except ScooterConnectionError as err:
            if show_notice:
                persistent_notification.async_create(
                    self.hass,
                    "Bluetooth und `0x5B` waren erfolgreich, aber der Scooter hat "
                    "das Pairing nicht abgeschlossen. **Die Integration behält den "
                    "App-Key** und versucht es beim nächsten Live-Advertisement erneut. "
                    "Beim nächsten Hinweis einmal kurz die Einschalttaste drücken. "
                    f"Details: `{err}`",
                    title="Ninebot/Xiaomi Scooter – Pairing nicht abgeschlossen",
                    notification_id=notification_id,
                )
            raise
        finally:
            if completed_in_this_attempt:
                persistent_notification.async_dismiss(self.hass, notification_id)

    async def _async_confirm_pairing_5d(self) -> None:
        """Finish the documented 0x5C/0x01 -> 0x5D/0x01 BLE129 exchange."""
        if self._pairing_serial is None:
            raise ScooterConnectionError("Scooter serial is missing from 0x5B reply")
        for attempt in range(3):
            response = await self._async_crypto_request(
                make_pair(self._pairing_serial),
                expected_commands={CMD_PAIR},
                timeout=2.5,
                accept_timeout=True,
            )
            if response is not None and response.index == PairingStatus.CONFIRMED:
                return
            if attempt < 2:
                await asyncio.sleep(0.5)
        raise ScooterConnectionError(
            "BLE129 0x5C01 was received but 0x5D01 was not; "
            "preserving the saved app key for the next live advertisement"
        )

    async def _async_ensure_legacy_session(self) -> None:
        """Open the original M365 55 AA NUS session, without a pairing key."""
        ble_device = self._pending_ble_device
        age = asyncio.get_running_loop().time() - self._pending_seen_at
        self._pending_ble_device = None
        self._pending_ble_name = None
        if ble_device is None or age > MAX_ADVERTISEMENT_AGE:
            raise ScooterConnectionError("A fresh connectable M365 advertisement is required")
        self._stage = "m365_legacy_gatt_connect"
        self._gatt_attempt_active = True
        try:
            self._client = await self._async_establish_client(ble_device)
            client = self._client
            self._last_services = tuple(str(service.uuid).lower() for service in client.services)
            self._tx_char = client.services.get_characteristic(NUS_WRITE_UUID)
            self._rx_char = client.services.get_characteristic(NUS_NOTIFY_UUID)
            if self._tx_char is None or self._rx_char is None:
                raise ScooterConnectionError("M365 NUS write/notify characteristics are missing")
            self._legacy_link = LegacyM365Link(self._async_write_packet)

            def on_legacy_notification(_characteristic: Any, payload: bytearray) -> None:
                if self._client is client and client.is_connected and self._legacy_link is not None:
                    self._legacy_link.on_notification(bytes(payload))

            self._stage = "m365_legacy_start_notify"
            await client.start_notify(self._rx_char, on_legacy_notification,
                                      bluez={"use_start_notify": True})
            await asyncio.sleep(0.15)
            self._stage = "m365_legacy_probe"
            response = await self._legacy_link.read(
                DeviceId.ESC, Xiaomi1sEscRegister.FAST_TELEMETRY,
                RegisterReadSize.FAST_TELEMETRY, timeout=2.0,
            )
            if response is None or len(response.payload) < Xiaomi1sFastTelemetry.MINIMUM_PAYLOAD:
                raise ScooterConnectionError("M365 did not confirm 55 AA core telemetry")
            self._initial_telemetry = self._legacy_as_packet(response)
            self._session_ready = True
            self._last_protocol = "M365 legacy (55 AA)"
            self._authentication_mode = "m365_legacy_read_only"
            self._control_session_started_at = datetime.now(UTC)
            self._stage = "m365_legacy_session_ready"
        except (BleakError, *TIMEOUT_ERRORS) as err:
            raise ScooterConnectionError(
                f"M365 legacy phase '{self._stage}' failed: {type(err).__name__}: {err}"
            ) from err
