"""Model identity, capability gates, telemetry freshness and diagnostics."""

from __future__ import annotations
import asyncio
from datetime import datetime
from typing import Any
from homeassistant.components import persistent_notification
from homeassistant.helpers import device_registry
from ..utilities import UTC
from ..const import CONF_MODEL, DOMAIN, MANUFACTURER
from ..models.profiles import (
    AUTO_MODEL,
    M365_LEGACY,
    M365_PRO_CRYPTO,
    effective_profile,
    identify_model,
    supports_write,
)
from ..models.transports import transport_for_family
from .constants import TELEMETRY_CACHE_SECONDS
import logging

_LOGGER = logging.getLogger(__name__)


class DeviceMixin:
    """Device operations on the coordinator session."""

    def _show_transport_notice(self) -> None:
        """Explain why a pairing prompt cannot appear until 0x5B is received."""
        now = asyncio.get_running_loop().time()
        if self._last_transport_notice_at and now - self._last_transport_notice_at < 120:
            return
        self._last_transport_notice_at = now
        phase = self._stage
        if phase == "ble129_init_5b":
            detail = (
                "Bluetooth hat eine Verbindung gemeldet, aber auf die BLE129-Initialisierung "
                "kam keine verwertbare Antwort. Die Integration setzt die Benachrichtigungen "
                "erneut auf und versucht es nach dem nächsten aktuellen Bluetooth-Signal."
            )
        else:
            detail = (
                "Die Bluetooth-Verbindung zum Scooter konnte noch nicht aufgebaut werden. "
                "Die Integration versucht es bei einem neuen aktuellen Bluetooth-Signal erneut."
            )
        if getattr(self, "_legacy_link", None) is not None or getattr(self, "model", None) == "Mi Electric Scooter":
            button_detail = (
                "Das ältere M365-Protokoll braucht keinen Pairing-Tastendruck; "
                "prüfe Bluetooth-Reichweite und die Verfügbarkeit des Scooters. "
            )
        else:
            button_detail = (
                "Die Aufforderung zum kurzen Druck auf die Einschalttaste erscheint "
                "automatisch, sobald der Scooter die Initialisierung bestätigt. "
            )
        persistent_notification.async_create(
            self.hass,
            f"{detail}\n\n{button_detail}"
            "Bitte den Scooter eingeschaltet lassen und andere Scooter-Apps schließen. "
            f"Letzte Phase: `{phase}`.",
            title="Ninebot/Xiaomi Scooter – Bluetooth-Verbindung wird wiederholt",
            notification_id=f"ninebot_e_scooters_connection_{self.entry.entry_id}",
        )

    def _identify_serial(self, serial: str | bytes) -> None:
        """Record model evidence without replacing the selected connection profile."""
        finding = identify_model(serial, self.device_name)
        previous = self._model_identification
        if finding.model and previous.model and finding.model != previous.model:
            self._model_conflict = True
            _LOGGER.warning("Scooter dashboard and controller serials indicate different models; writes disabled")
        if finding.model or (finding.serial_prefix and not previous.model):
            self._model_identification = finding

    @property
    def detected_model(self) -> str | None:
        """Return a model only when the serial prefix is documented and consistent."""
        return None if self._model_conflict else self._model_identification.model

    @property
    def display_model(self) -> str:
        """Expose a detected model without changing the user's saved selection."""
        return self.detected_model or ("Xiaomi Scooter (BLE129)" if self.model == AUTO_MODEL else self.model)

    def supports_action(self, field: str) -> bool:
        """Gate every write by a vetted profile and any conflicting evidence."""
        return not self._model_conflict and supports_write(self.model, self._model_identification, field)

    def _uses_legacy_m365(self) -> bool:
        """Select the four-dot 55 AA adapter only for an identified/selected M365."""
        profile = effective_profile(self.model, self._model_identification)
        return profile is not None and profile.protocol == M365_LEGACY

    def _uses_m365_pro_crypto(self) -> bool:
        """Select read-only BLE110/122 probes without enabling 1S writes."""
        profile = effective_profile(self.model, self._model_identification)
        return profile is not None and profile.protocol == M365_PRO_CRYPTO

    def _uses_ninebot(self) -> bool:
        """Keep Ninebot word-register reads separate from Xiaomi block reads."""
        profile = effective_profile(self.model, self._model_identification)
        return profile is not None and profile.protocol in (
            "ninebot_es", "ninebot_max", "ninebot_e", "ninebot_f",
        )

    @property
    def transport_profile(self):
        """Expose the selected family's transport boundary for future adapters."""
        profile = effective_profile(self.model, self._model_identification)
        return transport_for_family(profile.protocol) if profile is not None else None

    def _sync_model_to_registry(self) -> None:
        """Update the HA device label only after a successful telemetry refresh."""
        if getattr(self, "_auto_model_pending", False) and self.detected_model:
            self.model = self.detected_model
            self._auto_model_pending = False
            self.hass.config_entries.async_update_entry(
                self.entry,
                options={**self.entry.options, CONF_MODEL: self.model},
            )
        if self._registered_model == self.display_model:
            return
        try:
            registry = device_registry.async_get(self.hass)
            device = registry.async_get_device(identifiers={(DOMAIN, self.address)})
            if device is None:
                return
            if device.model != self.display_model:
                registry.async_update_device(
                    device.id,
                    model=self.display_model,
                    manufacturer=self._model_identification.brand or MANUFACTURER,
                )
            self._registered_model = self.display_model
        except Exception:
            # Device metadata is optional; never interrupt validated telemetry.
            _LOGGER.debug("Could not update scooter model in HA device registry", exc_info=True)

    @property
    def telemetry_cache_valid(self) -> bool:
        """Whether actual decoded telemetry may be shown as a last-known value.

        A GATT/handshake failure does not erase data, but a value older than
        ten minutes must no longer be presented as a current sensor reading.
        """
        last = self._last_telemetry_at
        return last is not None and (
            0 <= (datetime.now(UTC) - last).total_seconds() <= TELEMETRY_CACHE_SECONDS
        )

    @property
    def telemetry_stale(self) -> bool:
        """True unless a completed telemetry read and BLE session are current."""
        return (
            self._last_telemetry_at is None
            or not self.last_update_success
            or not self._session_ready
        )

    def setting_fresh(self, field: str) -> bool:
        """Show a confirmed setting from the current authenticated BLE session."""
        read_at = self._setting_read_at.get(field)
        return (
            not self._shutting_down
            and self._session_ready
            and self._client is not None
            and self._client.is_connected
            and read_at is not None
            and self._control_session_started_at is not None
            and read_at >= self._control_session_started_at
            and (datetime.now(UTC) - read_at).total_seconds() <= max(90, 3 * self.poll_interval)
        )

    def _remember_failed_session(self, error_type: str) -> None:
        """Keep non-secret failure metadata after the transport is reset."""
        self._last_failure_snapshot = {
            "at": datetime.now(UTC).isoformat(),
            "phase": self._stage,
            "error_type": error_type,
            "message_counter": self._crypto.message_counter if self._crypto else None,
            "last_decoded_reply": self._last_reply_command,
            "notification_count": self._raw_notification_count,
            "notification_callback_errors": getattr(self, "_notification_callback_errors", 0),
            "rejected_crypto_frames": self._rejected_crypto_frames,
            "last_rejected_frame_counter16": self._last_rejected_frame_counter16,
            "last_frame_issue": self._last_frame_issue,
            "gatt_failure": self._gatt_last_failure,
        }

    @property
    def diagnostics(self) -> dict[str, Any]:
        """Return diagnostics information."""
        return {
            "hardware_tested_profile": (profile.hardware_tested if (profile := effective_profile(self.model, self._model_identification)) else False),
            "consecutive_failed_sessions": self._backoff.failures,
            "retry_cooldown_remaining_s": round(max(0, self._retry_not_before - asyncio.get_running_loop().time()), 1),
            "address": self.address,
            "device_name": self.device_name,
            "configured_model": self.model,
            "detected_model": self.detected_model,
            "model_evidence": self._model_identification.evidence,
            "model_serial_prefix": self._model_identification.serial_prefix,
            "model_conflict": self._model_conflict,
            "model_brand": self._model_identification.brand,
            "model_protocol": (profile.protocol if (profile := effective_profile(self.model, self._model_identification)) else None),
            "transport_adapter_implemented": (transport.adapter_implemented if (transport := self.transport_profile) else False),
            "documented_ble_versions": list(transport.documented_ble_versions) if transport else [],
            "writable_settings": sorted(field for field in ("work_mode", "kers_mode", "is_lock_on", "is_cruise_on", "is_tail_light_on") if self.supports_action(field)),
            "poll_interval": self.poll_interval,
            "connection_strategy": "ha_recent_advertisement_direct_bledevice_with_bluez_backoff",
            "gatt_attempts": self._gatt_attempts,
            "gatt_successes": self._gatt_successes,
            "gatt_last_duration_s": self._gatt_last_duration_s,
            "gatt_last_failure": self._gatt_last_failure,
            "last_seen_scanner_source": self._last_seen_scanner_source,
            "connected_scanner_source": self._connected_scanner_source,
            "last_unexpected_session_duration_s": self._last_unexpected_session_duration_s,
            "scanner_short_disconnects": dict(self._scanner_short_disconnects),
            "scanner_retry_cooldown_remaining_s": {
                source: round(max(0, until - asyncio.get_running_loop().time()), 1)
                for source, until in self._scanner_avoid_until.items()
            },
            "last_failure_snapshot": self._last_failure_snapshot,
            "last_seen_rssi": self._last_seen_rssi,
            "last_ble_address_type": getattr(self, "_last_ble_address_type", None),
            "crypto_name_source": self._crypto_name_source,
            "crypto_name_matches_saved": self._crypto_name_matches_saved,
            "last_write_mode": self._last_write_mode,
            "last_lock_status_word": self._last_lock_status_word,
            "last_b0_lock_byte": self._last_b0_lock_byte,
            "last_bluez_path": getattr(self, "_last_bluez_path", None),
            "pairing_completed": self._pairing_completed,
            "pairing_failed": self._pairing_failed,
            "session_ready": self._session_ready,
            "message_counter": self._crypto.message_counter if self._crypto else None,
            "last_update_success": self.last_update_success,
            "last_telemetry_at": self._last_telemetry_at.isoformat() if self._last_telemetry_at else None,
            "last_speed_at": self._last_speed_at.isoformat() if self._last_speed_at else None,
            "authentication_mode": self._authentication_mode,
            "consecutive_empty_reads": self._empty_read_count,
            "setting_read_at": {key: value.isoformat() for key, value in self._setting_read_at.items()},
            "control_ready": self.control_ready,
            "setting_available": {
                field: self.setting_fresh(field)
                for field in ("work_mode", "kers_mode", "is_lock_on", "is_cruise_on", "is_tail_light_on")
            },
            "telemetry_cache_valid": self.telemetry_cache_valid,
            "telemetry_stale": self.telemetry_stale,
            "last_error": self._last_error,
            "stage": self._stage,
            "last_reply_command": self._last_reply_command,
            "last_protocol": self._last_protocol,
            "services": list(self._last_services),
            "last_notification": self._last_notification,
            "raw_notification_count": self._raw_notification_count,
            "notification_callback_errors": self._notification_callback_errors,
            "rejected_crypto_frames": self._rejected_crypto_frames,
            "last_frame_issue": self._last_frame_issue,
            "rx_buffer_length": len(self._rx_buffer),
            "unexpected_disconnect_count": self._disconnect_count,
            "disconnect_cleanup_count": self._disconnect_cleanup_count,
            "recovery_scan_count": self._recovery_scan_count,
            "existing_key_retries": self._existing_key_retries,
            "optional_registers": dict(self._extra_supported),
            "optional_payload_lengths": dict(self._extra_payload_lengths),
            "data": self.data.as_dict(include_raw=False) if self.data else {},
            "raw_packets": list(self._last_raw_packets),
        }
