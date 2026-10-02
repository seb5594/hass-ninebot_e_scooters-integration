"""Model-specific polling, decoded telemetry and last-known-value storage."""

from __future__ import annotations
import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import time
from homeassistant.components import persistent_notification
from homeassistant.core import CoreState
from homeassistant.helpers.update_coordinator import UpdateFailed
from ..const import MODEL
from ..protocols.ninebot.packet import (
    CMD_READ,
    CMD_READ_ACK,
    TARGET_ESC,
    NinebotPacket,
    make_read,
)
from ..protocols.ninebot.packet import (
    DeviceId,
    RegisterReadSize,
    Xiaomi1sBmsRegister,
    Xiaomi1sEscRegister,
    Xiaomi1sFastTelemetry,
    XIAOMI1S_CONTROLLER_REPLY_IDS,
    XIAOMI1S_KNOWN_LOCK_BYTES,
)
from ..protocols.xiaomi import ScooterData, ScooterMessage, apply_message
from ..protocols.ninebot.registers import apply_packet as apply_ninebot_packet
from ..storage import restore, snapshot
from .errors import ScooterConnectionError
from .constants import EXTRA_READ_REGISTERS, GATT_RETRY_COOLDOWN, STATIC_EXTRA_NAMES
import logging

_LOGGER = logging.getLogger(__name__)


class TelemetryMixin:
    """Telemetry operations on the coordinator session."""

    async def async_restore_saved_data(self) -> None:
        """Restore verified readings without treating them as a live BLE session."""
        try:
            payload = await self._telemetry_store.async_load()
            data, last_read_at = restore(payload, self.address)
        except (OSError, ValueError, TypeError):
            _LOGGER.debug("Could not restore scooter telemetry", exc_info=True)
            return
        if data is None:
            return
        self._saved_snapshot = payload
        self._last_telemetry_at = last_read_at
        if data.serial:
            self._identify_serial(data.serial)
        self.async_set_updated_data(data)

    async def _async_update_data(self) -> ScooterData:
        """Fetch telemetry only after HA startup and when BLE can see the scooter."""
        # CoordinatorEntity may schedule an interval refresh while HA is still
        # starting. Do not involve the Bluetooth stack in that phase: the
        # adapter and scooter discovery history may not exist yet.
        if self.hass.state is not CoreState.running:
            self._stage = "waiting_for_home_assistant"
            return self.data or ScooterData()

        # Do not burn connection slots on cached BLEDevice objects from 58-118
        # seconds ago. Each attempt requires an unconsumed live advertisement.
        now = asyncio.get_running_loop().time()
        connected_session = (
            self._session_ready and self._client is not None and self._client.is_connected
        )
        if not connected_session and (
            self._pending_ble_device is None or now - self._pending_seen_at > 5.0
        ):
            self._pending_ble_device = None
            self._stage = "waiting_for_live_advertisement"
            return self.data or ScooterData()

        if now < self._retry_not_before:
            self._stage = "waiting_for_connect_cooldown"
            return self.data or ScooterData()
        try:
            async with self._command_lock:
                await self._async_ensure_session()
                replies = await self._async_read_registers()
                if self._client is None or not self._client.is_connected or not self._session_ready:
                    raise ScooterConnectionError("Scooter disconnected during telemetry refresh")
        except ScooterConnectionError as err:
            self._last_error = str(err)
            self._remember_failed_session(type(err).__name__)
            self._transport_failures += 1
            if (not self._pairing_completed or self._stage == "ble129_init_5b"
                    or self._transport_failures >= 3):
                self._show_transport_notice()
            # A short GATT retry set by _async_ensure_session() was previously
            # overwritten here with 15 seconds. Preserve the phase-specific
            # cooldown while keeping handshake failures less aggressive.
            cooldown = (
                self._gatt_retry_cooldown
                if self._stage in ("gatt_connect", "gatt_disconnected")
                else 15.0
            )
            if (backoff := getattr(self, "_backoff", None)) is not None:
                cooldown = backoff.failed(
                    cooldown,
                    needs_confirmation="pairing" in self._stage or "confirmation" in self._stage,
                )
            self._retry_not_before = max(
                self._retry_not_before,
                asyncio.get_running_loop().time() + cooldown,
            )
            await self._async_disconnect()
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            self._last_error = str(err)
            self._remember_failed_session(type(err).__name__)
            cooldown = 15.0
            if (backoff := getattr(self, "_backoff", None)) is not None:
                cooldown = backoff.failed(cooldown)
            self._retry_not_before = max(self._retry_not_before, asyncio.get_running_loop().time() + cooldown)
            _LOGGER.exception("Unexpected Xiaomi Scooter communication error")
            await self._async_disconnect()
            raise UpdateFailed(
                f"{self._stage}: {type(err).__name__}: {err!r}"
            ) from err

        if not replies:
            self._empty_read_count += 1
            self._last_error = "No telemetry reply in the authenticated session"
            if self._empty_read_count >= 2:
                self._remember_failed_session("NoTelemetryReplies")
                cooldown = GATT_RETRY_COOLDOWN
                if (backoff := getattr(self, "_backoff", None)) is not None:
                    cooldown = backoff.failed(cooldown)
                self._retry_not_before = max(self._retry_not_before, asyncio.get_running_loop().time() + cooldown)
                await self._async_disconnect()
            raise UpdateFailed("Scooter connected but returned no telemetry")

        self._empty_read_count = 0
        data = replace(self.data, raw_packets=()) if self.data is not None else ScooterData()
        decoded_count = 0
        for packet in replies:
            if getattr(self, "_uses_ninebot", lambda: False)():
                if apply_ninebot_packet(data, packet):
                    decoded_count += 1
                    if packet.index == 0x10 and data.serial:
                        self._identify_serial(data.serial)
                continue
            if (
                packet.source in XIAOMI1S_CONTROLLER_REPLY_IDS
                and packet.index == Xiaomi1sEscRegister.FAST_TELEMETRY
                and len(packet.data) > Xiaomi1sFastTelemetry.LOCK_BYTE_OFFSET
            ):
                self._last_b0_lock_byte = packet.data[Xiaomi1sFastTelemetry.LOCK_BYTE_OFFSET]
            if self.display_model == MODEL and packet.index == Xiaomi1sEscRegister.LOCK_STATUS:
                # On this 1S, B2 is an ESC status word. It has not been
                # proven to represent the lock; retain it for diagnostics.
                if packet.source in XIAOMI1S_CONTROLLER_REPLY_IDS and len(packet.data) >= RegisterReadSize.WORD:
                    self._last_lock_status_word = int.from_bytes(packet.data[:2], "little")
                continue
            if apply_message(
                data,
                ScooterMessage(
                    direction=packet.source,
                    read_write=packet.command,
                    attribute=packet.index,
                    payload=packet.data,
                    raw=packet.pack(),
                ),
            ):
                decoded_count += 1
                if (packet.source in XIAOMI1S_CONTROLLER_REPLY_IDS
                        and packet.index == Xiaomi1sEscRegister.GENERAL_INFO and data.serial):
                    self._identify_serial(data.serial)
                if (packet.source in XIAOMI1S_CONTROLLER_REPLY_IDS
                        and packet.index in (Xiaomi1sEscRegister.FAST_TELEMETRY,
                                             Xiaomi1sEscRegister.QUICK_SPEED)):
                    self._last_speed_at = datetime.now(UTC)
                if packet.source in XIAOMI1S_CONTROLLER_REPLY_IDS:
                    fields = {
                        Xiaomi1sEscRegister.FAST_TELEMETRY: ("is_lock_on",),
                        Xiaomi1sEscRegister.WORK_MODE: ("work_mode",),
                        Xiaomi1sEscRegister.SUPPLEMENTARY_KERS: ("kers_mode", "is_cruise_on", "is_tail_light_on"),
                        Xiaomi1sEscRegister.CRUISE: ("is_cruise_on",),
                        Xiaomi1sEscRegister.TAIL_LIGHT: ("is_tail_light_on",),
                        Xiaomi1sEscRegister.LOCK_STATUS: ("is_lock_on",),
                    }.get(packet.index, ())
                    for field in fields:
                        if (packet.index == Xiaomi1sEscRegister.FAST_TELEMETRY
                                and field == "is_lock_on"
                                and packet.data[Xiaomi1sFastTelemetry.LOCK_BYTE_OFFSET]
                                not in XIAOMI1S_KNOWN_LOCK_BYTES):
                            continue
                        if packet.index == Xiaomi1sEscRegister.SUPPLEMENTARY_KERS and len(packet.data) < {
                            "kers_mode": 2, "is_cruise_on": 4, "is_tail_light_on": 6,
                        }[field]:
                            continue
                        if getattr(data, field) is not None:
                            self._setting_read_at[field] = datetime.now(UTC)
                _LOGGER.info(
                    "Scooter telemetry decoded: register=0x%02X payload_len=%d",
                    packet.index, len(packet.data),
                )
            else:
                if (packet.source in XIAOMI1S_CONTROLLER_REPLY_IDS
                        and packet.index == Xiaomi1sEscRegister.LOCK_STATUS
                        and len(packet.data) >= RegisterReadSize.WORD):
                    self._last_lock_status_word = int.from_bytes(packet.data[:2], "little")
                log_unsupported = (
                    _LOGGER.debug
                    if packet.index in (Xiaomi1sEscRegister.LOCK_STATUS,
                                        Xiaomi1sBmsRegister.VERSION_STANDARD)
                    and len(packet.data) == RegisterReadSize.WORD
                    else _LOGGER.warning
                )
                log_unsupported(
                    "Scooter telemetry register 0x%02X replied with %d bytes, "
                    "but its payload layout is not yet supported",
                    packet.index, len(packet.data),
                )

        if decoded_count == 0:
            raise UpdateFailed(
                "Scooter replied to telemetry requests but none of the "
                "payload layouts could be decoded; see register lengths in debug log"
            )

        # Legacy replies were converted to a common decoded-data shape; do
        # not present those synthetic packets as captured 5A A5 radio frames.
        self._last_raw_packets = (
            () if getattr(self, "_legacy_link", None) is not None
            else tuple(packet.pack().hex() for packet in replies)[-20:]
        )
        data.raw_packets = self._last_raw_packets
        self._last_error = None
        self._transport_failures = 0
        if (backoff := getattr(self, "_backoff", None)) is not None:
            backoff.reset()
        persistent_notification.async_dismiss(
            self.hass, f"ninebot_e_scooters_connection_{self.entry.entry_id}"
        )
        self._last_telemetry_at = datetime.now(UTC)
        self._saved_snapshot = snapshot(self.address, data, self._last_telemetry_at)
        now = time.monotonic()
        if now - self._last_saved_at >= 60 or (
            self.data is not None
            and self.data.battery_health_percent is None
            and data.battery_health_percent is not None
        ):
            self._last_saved_at = now
            self._telemetry_store.async_delay_save(lambda: self._saved_snapshot, 1)
        self._sync_model_to_registry()
        return data

    @staticmethod
    def _legacy_as_packet(message: ScooterMessage) -> NinebotPacket:
        """Use the shared decoded-data path after validating a 55 AA frame."""
        return NinebotPacket(
            message.direction, DeviceId.PHONE, message.read_write,
            message.attribute, message.payload,
        )

    async def _async_read_legacy_registers(self) -> list[NinebotPacket]:
        """Keep essential M365 reads short and retry missing BMS metadata."""
        assert self._legacy_link is not None
        replies: list[NinebotPacket] = []
        if self._initial_telemetry is not None:
            replies.append(self._initial_telemetry)
            self._initial_telemetry = None
        else:
            speed = await self._legacy_link.read(
                DeviceId.ESC, Xiaomi1sEscRegister.FAST_TELEMETRY,
                RegisterReadSize.FAST_TELEMETRY,
            )
            if speed is not None:
                replies.append(self._legacy_as_packet(speed))
        battery = await self._legacy_link.read(
            DeviceId.BMS, Xiaomi1sBmsRegister.BATTERY_INFO,
            RegisterReadSize.TRIP_AND_BATTERY,
        )
        if battery is not None:
            replies.append(self._legacy_as_packet(battery))
        if not replies:
            return replies

        now = asyncio.get_running_loop().time()
        optional = (
            ("legacy_serial", DeviceId.ESC, Xiaomi1sEscRegister.GENERAL_INFO, RegisterReadSize.GENERAL_INFO, 300),
            ("legacy_date", DeviceId.BMS, Xiaomi1sBmsRegister.MANUFACTURE_DATE, RegisterReadSize.BMS_MANUFACTURE_DATE, 120),
            ("legacy_health", DeviceId.BMS, Xiaomi1sBmsRegister.BATTERY_HEALTH, RegisterReadSize.WORD, 120),
            ("legacy_mode", DeviceId.ESC, Xiaomi1sEscRegister.WORK_MODE, RegisterReadSize.WORD, 30),
        )
        for name, target, register, length, interval in optional:
            if name == "legacy_serial" and self.data is not None and self.data.serial:
                continue
            if name == "legacy_date" and self.data is not None and self.data.battery_manufacture_date:
                continue
            if name == "legacy_health" and self.data is not None and self.data.battery_health_percent is not None:
                continue
            if now < self._next_setting_read_at.get(name, 0):
                continue
            self._next_setting_read_at[name] = now + interval
            response = await self._legacy_link.read(target, register, length, timeout=1.4)
            if response is not None:
                replies.append(self._legacy_as_packet(response))
            break
        return replies

    async def _async_read_registers(self) -> list[NinebotPacket]:
        """Read the core telemetry registers."""
        if getattr(self, "_legacy_link", None) is not None:
            return await self._async_read_legacy_registers()
        if getattr(self, "_uses_ninebot", lambda: False)():
            return await self._async_read_ninebot_registers()
        m365_pro = getattr(self, "_uses_m365_pro_crypto", lambda: False)()
        if m365_pro:
            self._last_protocol = "M365 Pro BLE110/122 (5A A5)"
        requests = (
            make_read(DeviceId.ESC, Xiaomi1sEscRegister.FAST_TELEMETRY, RegisterReadSize.FAST_TELEMETRY),
            make_read(DeviceId.ESC, Xiaomi1sEscRegister.TRIP_INFO, RegisterReadSize.TRIP_AND_BATTERY),
            # The firmware's range estimate is intentionally hidden and does
            # not need to consume a BLE request on every telemetry refresh.
            make_read(DeviceId.BMS, Xiaomi1sBmsRegister.BATTERY_INFO, RegisterReadSize.TRIP_AND_BATTERY),
        )
        if m365_pro:
            # BLE110/122 share the encrypted framing, but the 1S's fast
            # settings and extra register sweep are firmware specific.
            requests = tuple(request for request in requests
                             if request.index != Xiaomi1sEscRegister.TRIP_INFO)
        replies: list[NinebotPacket] = []
        if self._initial_telemetry is not None:
            replies.append(self._initial_telemetry)
            self._initial_telemetry = None
        for request in requests:
            if request.index == Xiaomi1sEscRegister.FAST_TELEMETRY and replies:
                continue
            response = await self._async_crypto_request(
                request,
                # Xiaomi answers read requests with 0x01. 0x04 is the
                # Ninebot-family read ACK; accept both, then check register,
                # sender and recipient before using the data.
                expected_commands={CMD_READ, CMD_READ_ACK},
                timeout=2.0,
                accept_timeout=True,
                # A single unanswered register is tolerated; a complete
                # telemetry failure still raises UpdateFailed below.
                quiet_timeout=True,
            )
            if response is None:
                continue

            # Source, target and register are already validated inside
            # _async_crypto_request(). In 5A A5, the native sources are 0x20
            # (controller) and 0x22 (BMS); the older 55 AA aliases 0x23/0x25
            # are accepted there for firmware compatibility.
            replies.append(response)

        if not replies:
            return replies

        if m365_pro:
            now = asyncio.get_running_loop().time()
            for name, target, register, length, interval in (
                ("pro_serial", DeviceId.ESC, Xiaomi1sEscRegister.GENERAL_INFO, RegisterReadSize.GENERAL_INFO, 300),
                ("pro_date", DeviceId.BMS, Xiaomi1sBmsRegister.MANUFACTURE_DATE, RegisterReadSize.BMS_MANUFACTURE_DATE, 120),
                ("pro_health", DeviceId.BMS, Xiaomi1sBmsRegister.BATTERY_HEALTH, RegisterReadSize.WORD, 120),
            ):
                if name == "pro_serial" and self.data is not None and self.data.serial:
                    continue
                if name == "pro_date" and self.data is not None and self.data.battery_manufacture_date:
                    continue
                if name == "pro_health" and self.data is not None and self.data.battery_health_percent is not None:
                    continue
                if now < self._next_setting_read_at.get(name, 0):
                    continue
                self._next_setting_read_at[name] = now + interval
                response = await self._async_crypto_request(
                    make_read(target, register, length),
                    expected_commands={CMD_READ, CMD_READ_ACK},
                    timeout=1.25, accept_timeout=True, quiet_timeout=True,
                )
                if response is not None:
                    replies.append(response)
                break
            return replies

        # Refresh mode each cycle and one other setting per cycle so mode
        # cannot starve the KERS, cruise, light, or lock state reads.
        now = asyncio.get_running_loop().time()
        if now >= self._next_setting_read_at.get("ride_mode", 0):
            self._next_setting_read_at["ride_mode"] = now + max(8, getattr(self, "poll_interval", 10))
            mode_response = await self._async_crypto_request(
                make_read(TARGET_ESC, Xiaomi1sEscRegister.WORK_MODE, RegisterReadSize.WORD),
                expected_commands={CMD_READ, CMD_READ_ACK},
                timeout=1.0, accept_timeout=True, quiet_timeout=True,
            )
            if mode_response is not None:
                replies.append(mode_response)
            else:
                self._next_setting_read_at["ride_mode"] = now + 10
        for key, register, length in (
            ("supplementary", Xiaomi1sEscRegister.SUPPLEMENTARY_KERS, RegisterReadSize.SUPPLEMENTARY),
            ("cruise", Xiaomi1sEscRegister.CRUISE, RegisterReadSize.WORD),
            ("tail_light", Xiaomi1sEscRegister.TAIL_LIGHT, RegisterReadSize.WORD),
        ):
            if key in ("cruise", "tail_light") and self.data is not None:
                field = "is_cruise_on" if key == "cruise" else "is_tail_light_on"
                read_at = self._setting_read_at.get(field)
                if read_at is not None and (datetime.now(UTC) - read_at).total_seconds() < 45:
                    continue
            if now < self._next_setting_read_at.get(key, 0):
                continue
            self._next_setting_read_at[key] = now + 30
            response = await self._async_crypto_request(
                make_read(TARGET_ESC, register, length),
                expected_commands={CMD_READ, CMD_READ_ACK},
                timeout=1.0, accept_timeout=True, quiet_timeout=True,
            )
            if response is not None:
                replies.append(response)
            else:
                self._next_setting_read_at[key] = now + 10
            break

        # Start with one probe per poll. Static versions are read only once;
        # after the initial sweep, rotate only the changing fault/BMS values.
        # until AFTER successful core readings. They must not delay the first
        # legitimate battery / odometer states or flood unsupported firmware.
        extra = None
        if self._extra_index < len(EXTRA_READ_REGISTERS):
            extra = EXTRA_READ_REGISTERS[self._extra_index]
            self._extra_index += 1
        else:
            changing = tuple(item for item in EXTRA_READ_REGISTERS if item[0] not in STATIC_EXTRA_NAMES)
            if changing:
                extra = changing[self._dynamic_extra_index % len(changing)]
                self._dynamic_extra_index += 1
        if (self.data is not None and self.data.battery_health_percent is None
                and self._extra_index >= 3
                and now >= self._next_setting_read_at.get("battery_health_retry", 0)
                and extra is not None and extra[0] != "bms_battery_health"):
            # A missing health value should be retried promptly, while other
            # optional reads still get their turn between these attempts.
            self._next_setting_read_at["battery_health_retry"] = now + 60
            extra = next(item for item in EXTRA_READ_REGISTERS if item[0] == "bms_battery_health")
        if (self.data is not None and self.data.battery_manufacture_date is None
                and self._extra_index >= len(EXTRA_READ_REGISTERS)
                and now >= self._next_setting_read_at.get("battery_date_retry", 0)
                and extra is not None and extra[0] != "bms_manufacture_date"):
            # Retry a missing static BMS date without repeating every other
            # static register or starving dynamic telemetry.
            self._next_setting_read_at["battery_date_retry"] = now + 120
            extra = next((item for item in EXTRA_READ_REGISTERS
                          if item[0] == "bms_manufacture_date"), extra)
        if (extra is not None and extra[0] == "bms_manufacture_date"
                and self.data is not None and self.data.battery_manufacture_date is not None):
            extra = None
        if extra is not None:
            if extra[0] == "bms_manufacture_date":
                self._next_setting_read_at["battery_date_retry"] = now + 120
            name, target, register, length = extra
            self._stage = f"optional_read_0x{register:02X}"
            try:
                extra_response = await self._async_crypto_request(
                    make_read(target, register, length),
                    expected_commands={CMD_READ, CMD_READ_ACK},
                    timeout=1.25,
                    accept_timeout=True,
                    quiet_timeout=True,
                )
                self._extra_supported[name] = extra_response is not None
                if extra_response is not None:
                    self._extra_payload_lengths[name] = len(extra_response.data)
                    replies.append(extra_response)
            except ScooterConnectionError as err:
                # A truly broken link will still be noticed on the next core
                # refresh; do not throw away this cycle's good core values.
                _LOGGER.debug("Optional scooter register %s failed: %s", name, err)
                self._extra_supported[name] = False
            finally:
                # A disconnect during an optional read must keep its actual
                # phase so the GATT retry gets a short transport cooldown.
                if self._stage != "gatt_disconnected":
                    self._stage = "ble129_session_ready"

        return replies
