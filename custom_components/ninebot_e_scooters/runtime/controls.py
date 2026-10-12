"""Stationary-only Xiaomi controls with capability checks and verified readback."""

from __future__ import annotations
import asyncio
from dataclasses import replace
from datetime import datetime
import time
from homeassistant.components import bluetooth
from ..utilities import UTC
from ..compat import async_request_active_scan
from ..protocols.ninebot.packet import (
    CMD_READ,
    CMD_READ_ACK,
    CMD_WRITE,
    CMD_WRITE_ACK,
    CMD_WRITE_NO_REPLY,
    SOURCE_PHONE,
    TARGET_ESC,
    NinebotPacket,
    make_read,
)
from ..protocols.ninebot.packet import (
    RegisterReadSize,
    Xiaomi1sEscRegister,
    Xiaomi1sFastTelemetry,
    XIAOMI1S_KNOWN_LOCK_BYTES,
)
from ..protocols.xiaomi import ScooterMessage, apply_message
from .errors import ScooterConnectionError
from .constants import MAX_ADVERTISEMENT_AGE
import logging

_LOGGER = logging.getLogger(__name__)


class ControlsMixin:
    """Controls operations on the coordinator session."""

    @property
    def control_ready(self) -> bool:
        """Authenticated, stationary and telemetered within THIS GATT session."""
        data = self.data
        if (self._shutting_down or not self._session_ready
            or self._client is None or not self._client.is_connected
            or data is None or data.speed_kmh is None
            or self._last_speed_at is None or not self.last_update_success
            or self._control_session_started_at is None
                or self._last_speed_at < self._control_session_started_at):
            return False
        return (datetime.now(UTC) - self._last_speed_at).total_seconds() <= max(15, self.poll_interval + 3) and abs(data.speed_kmh) < 0.01

    async def _async_write_setting(self, index: int, value: int, read_register: int, read_length: int, field: str, expected: object) -> None:
        """Read fresh speed and verify writes; the lock reconnects beforehand."""
        if not self.supports_action(field):
            raise ScooterConnectionError("Schreibbefehl für das erkannte Scooter-Modell nicht bestätigt")
        if not self.control_ready:
            raise ScooterConnectionError("Steuerung nur bei aktiver BLE129-Sitzung mit frischen 0 km/h")
        async with self._command_lock:
            if not self.control_ready:
                raise ScooterConnectionError("Scooter nicht mehr bereit für Steuerbefehle")
            if not isinstance(value, int) or not 0 <= value <= 0xFFFF:
                raise ScooterConnectionError("Ungültiger Registerwert")
            speed = await self._async_crypto_request(
                make_read(TARGET_ESC, Xiaomi1sEscRegister.FAST_TELEMETRY, RegisterReadSize.FAST_TELEMETRY),
                expected_commands={CMD_READ, CMD_READ_ACK},
                timeout=1.5, accept_timeout=True, quiet_timeout=True,
            )
            if speed is None:
                raise ScooterConnectionError("Geschwindigkeit nicht frisch bestätigt")
            fresh = replace(self.data)
            if not apply_message(fresh, ScooterMessage(
                direction=speed.source, read_write=speed.command,
                attribute=speed.index, payload=speed.data, raw=speed.pack(),
            )) or fresh.speed_kmh is None or abs(fresh.speed_kmh) >= 0.01:
                raise ScooterConnectionError("Scooter bewegt sich oder Geschwindigkeit unbekannt")
            if not self.control_ready:
                raise ScooterConnectionError("Scooter-Verbindung während Prüfung verloren")
            _LOGGER.info("Scooter control write register 0x%02X", index)
            try:
                for opcode in ((CMD_WRITE_NO_REPLY, CMD_WRITE) if field == "work_mode"
                               else (CMD_WRITE_NO_REPLY,)):
                    packet = NinebotPacket(source=SOURCE_PHONE, target=TARGET_ESC,
                                           command=opcode, index=index,
                                           data=value.to_bytes(2, "little"))
                    await self._async_crypto_request(
                        packet, expected_commands={CMD_WRITE_ACK, CMD_WRITE, CMD_WRITE_NO_REPLY},
                        timeout=0.45 if opcode == CMD_WRITE_NO_REPLY else 0.75,
                        accept_timeout=True, quiet_timeout=True,
                    )
                # A single readback could miss ESC settling.
                # Repeat the read, never an unconfirmed write.
                    for attempt in range(3):
                        if attempt:
                            await asyncio.sleep(0.2)
                        readback = await self._async_crypto_request(
                            make_read(TARGET_ESC, read_register, read_length),
                            expected_commands={CMD_READ, CMD_READ_ACK},
                            timeout=1.5, accept_timeout=True, quiet_timeout=True,
                        )
                        if readback is None:
                            continue
                        updated = replace(self.data)
                        if apply_message(updated, ScooterMessage(
                            direction=readback.source, read_write=readback.command,
                            attribute=readback.index, payload=readback.data,
                            raw=readback.pack(),
                        )) and getattr(updated, field) == expected:
                            self._setting_read_at[field] = datetime.now(UTC)
                            self.async_set_updated_data(updated)
                            return
                    if opcode == CMD_WRITE_NO_REPLY and field == "work_mode":
                        # Try the acknowledged variant only while still
                        # stationary; each write changes the same mode.
                        speed_check = await self._async_crypto_request(
                            make_read(TARGET_ESC, Xiaomi1sEscRegister.FAST_TELEMETRY, RegisterReadSize.FAST_TELEMETRY),
                            expected_commands={CMD_READ, CMD_READ_ACK},
                            timeout=1.5, accept_timeout=True, quiet_timeout=True,
                        )
                        stationary = replace(self.data)
                        if speed_check is None or not apply_message(stationary, ScooterMessage(
                            direction=speed_check.source, read_write=speed_check.command,
                            attribute=speed_check.index, payload=speed_check.data,
                            raw=speed_check.pack(),
                        )) or stationary.speed_kmh is None or abs(stationary.speed_kmh) >= 0.01:
                            raise ScooterConnectionError("Scooter bewegt sich; Fahrmodus nicht erneut geschrieben")
                        _LOGGER.info("Scooter ride mode did not change; trying acknowledged write once")
                raise ScooterConnectionError("Befehl gesendet, Status nicht bestätigt")
            except ScooterConnectionError:
                raise
            except Exception as err:
                raise ScooterConnectionError(
                    f"Befehl gesendet, Rückmeldung unsicher: {type(err).__name__}"
                ) from err

    async def async_set_lock(self, locked: bool) -> None:
        """Legacy lock/unlock may reboot the controller."""
        if not self.supports_action("is_lock_on"):
            raise ScooterConnectionError("Sperre für das erkannte Scooter-Modell nicht geprüft")
        if self.data is None or self.data.is_lock_on is None:
            raise ScooterConnectionError("Sperrstatus unbekannt")
        await self._async_reconnect_for_lock()
        if self.data.is_lock_on == locked:
            return
        await self._async_write_setting(
            Xiaomi1sEscRegister.LOCK if locked else Xiaomi1sEscRegister.UNLOCK,
            1, Xiaomi1sEscRegister.FAST_TELEMETRY, RegisterReadSize.FAST_TELEMETRY,
            "is_lock_on", locked,
        )

    async def _async_reconnect_for_lock(self) -> None:
        """Open a fresh authenticated session before a lock state transition."""
        async with self._command_lock:
            if self._shutting_down:
                raise ScooterConnectionError("Scooter wird gerade entladen")
            await self._async_disconnect()
            # A requested lock change takes precedence over an old connection
            # cooldown, but still needs a newly received connectable advert.
            self._retry_not_before = asyncio.get_running_loop().time()
            service_info = None
            for attempt in range(3):
                info = bluetooth.async_last_service_info(
                    self.hass, self.address, connectable=True,
                )
                if info is not None and getattr(info, "connectable", False) and getattr(info, "device", None) is not None:
                    seen_at = getattr(info, "time", 0)
                    clock = time.time() if seen_at > 1_000_000_000 else asyncio.get_running_loop().time()
                    if 0 <= clock - seen_at <= MAX_ADVERTISEMENT_AGE:
                        service_info = info
                        break
                if attempt < 2:
                    await async_request_active_scan(self.hass, duration=3.5)
            if service_info is None:
                self._rearm_advertisements()
                raise ScooterConnectionError("Nach dem Trennen kein aktuelles Bluetooth-Advertisement für die Sperre gefunden")

            self._pending_ble_device = service_info.device
            self._pending_ble_name = getattr(service_info, "name", None)
            self._pending_seen_at = asyncio.get_running_loop().time()
            self._last_seen_rssi = getattr(service_info, "rssi", None)
            try:
                await self._async_ensure_session()
                response = await self._async_crypto_request(
                    make_read(TARGET_ESC, Xiaomi1sEscRegister.FAST_TELEMETRY, RegisterReadSize.FAST_TELEMETRY),
                    expected_commands={CMD_READ, CMD_READ_ACK},
                    timeout=1.5, accept_timeout=True, quiet_timeout=True,
                )
                if (response is None
                        or len(response.data) < Xiaomi1sFastTelemetry.MINIMUM_PAYLOAD
                        or response.data[Xiaomi1sFastTelemetry.LOCK_BYTE_OFFSET]
                        not in XIAOMI1S_KNOWN_LOCK_BYTES):
                    raise ScooterConnectionError("Sperrstatus nach Wiederverbindung nicht bestätigt")
                fresh = replace(self.data)
                if not apply_message(fresh, ScooterMessage(
                    direction=response.source, read_write=response.command,
                    attribute=response.index, payload=response.data, raw=response.pack(),
                )) or fresh.speed_kmh is None or abs(fresh.speed_kmh) >= 0.01:
                    raise ScooterConnectionError("Scooter bewegt sich oder Geschwindigkeit unbekannt")
                self._last_speed_at = datetime.now(UTC)
                self._last_telemetry_at = self._last_speed_at
                self._setting_read_at["is_lock_on"] = self._last_speed_at
                self.async_set_updated_data(fresh)
            except Exception:
                await self._async_disconnect()
                raise

    async def async_set_cruise(self, enabled: bool) -> None:
        if not self.supports_action("is_cruise_on"):
            raise ScooterConnectionError("Tempomat für das erkannte Scooter-Modell nicht geprüft")
        if self.data is None or self.data.is_cruise_on is None:
            raise ScooterConnectionError("Tempomat unbekannt")
        if self.data.is_cruise_on == enabled:
            return
        await self._async_write_setting(
            Xiaomi1sEscRegister.CRUISE, int(enabled), Xiaomi1sEscRegister.CRUISE,
            RegisterReadSize.WORD, "is_cruise_on", enabled,
        )

    async def async_set_tail_light(self, enabled: bool) -> None:
        if not self.supports_action("is_tail_light_on"):
            raise ScooterConnectionError("Rücklicht für das erkannte Scooter-Modell nicht geprüft")
        if self.data is None or self.data.is_tail_light_on is None:
            raise ScooterConnectionError("Rücklicht unbekannt")
        if self.data.is_tail_light_on == enabled:
            return
        await self._async_write_setting(
            Xiaomi1sEscRegister.TAIL_LIGHT, 2 if enabled else 0,
            Xiaomi1sEscRegister.TAIL_LIGHT, RegisterReadSize.WORD,
            "is_tail_light_on", enabled,
        )

    async def async_set_kers_mode(self, mode: int) -> None:
        """Experimental KERS write on this specific SHFW variant."""
        if not self.supports_action("kers_mode"):
            raise ScooterConnectionError("KERS für das erkannte Scooter-Modell nicht geprüft")
        if mode not in (0, 1, 2):
            raise ScooterConnectionError("KERS muss 0, 1 oder 2 sein")
        if self.data is None or self.data.kers_mode not in (0, 1, 2):
            raise ScooterConnectionError("KERS-Register unbekannt")
        if self.data.kers_mode == mode:
            return
        await self._async_write_setting(
            Xiaomi1sEscRegister.SUPPLEMENTARY_KERS, mode,
            Xiaomi1sEscRegister.SUPPLEMENTARY_KERS,
            RegisterReadSize.SUPPLEMENTARY, "kers_mode", mode,
        )

    async def async_set_ride_mode(self, mode: int) -> None:
        """Change the 1S riding mode only while stationary and verify 0x75."""
        if not self.supports_action("work_mode"):
            raise ScooterConnectionError("Fahrmodus-Steuerung für dieses Modell nicht geprüft")
        if mode not in (0, 1, 2):
            raise ScooterConnectionError("Fahrmodus muss Drive (0), Eco (1) oder Sport (2) sein")
        if self.data is None or self.data.work_mode not in (0, 1, 2):
            raise ScooterConnectionError("Fahrmodus-Register 0x75 noch nicht bestätigt")
        if self.data.work_mode == mode:
            return
        await self._async_write_setting(
            Xiaomi1sEscRegister.WORK_MODE, mode, Xiaomi1sEscRegister.WORK_MODE,
            RegisterReadSize.WORD, "work_mode", mode,
        )
