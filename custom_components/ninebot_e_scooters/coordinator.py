"""Home Assistant coordinator for Ninebot and Xiaomi scooter sessions."""

from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta
import secrets
from typing import Any
from bleak import BleakClient
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from .const import CONF_MODEL, DEFAULT_POLL_INTERVAL, MODEL
from .protocols.legacy import LegacyM365Link
from .protocols.ninebot.crypto import NinebotCrypto
from .protocols.ninebot.packet import DeviceId, NinebotPacket
from .models.profiles import AUTO_MODEL, identify_model
from .protocols.xiaomi import ScooterData
from .storage import storage_key
from .runtime.constants import GATT_RETRY_COOLDOWN
from .runtime.device import DeviceMixin
from .runtime.connection import ConnectionMixin
from .runtime.session import SessionMixin
from .runtime.requests import RequestsMixin
from .runtime.telemetry import TelemetryMixin
from .runtime.controls import ControlsMixin
from .runtime.ninebot import NinebotMixin
from .utilities import ConnectionBackoff, parse_app_key
from .runtime.errors import ScooterConnectionError as ScooterConnectionError

_LOGGER = logging.getLogger(__name__)


class ScooterCoordinator(DeviceMixin, ConnectionMixin, SessionMixin, RequestsMixin, TelemetryMixin, ControlsMixin, NinebotMixin, DataUpdateCoordinator[ScooterData]):
    """Own one scooter session and expose it to Home Assistant entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, address: str, name: str, poll_interval: int = DEFAULT_POLL_INTERVAL) -> None:
        """Initialize the coordinator."""
        self.address = address
        self.device_name = name
        self.model = entry.options.get(CONF_MODEL, MODEL)
        self._auto_model_pending = self.model == AUTO_MODEL
        self._model_identification = identify_model(None, name)
        self._model_conflict = False
        self._registered_model: str | None = None
        self.poll_interval = poll_interval
        self.entry = entry
        self._backoff = ConnectionBackoff()
        transport = self.transport_profile
        self._host_id = transport.host_id if transport is not None else DeviceId.PHONE
        self._ninebot_optional_index = 0
        stored_key = entry.data.get("app_key")
        if stored_key:
            self._app_key = parse_app_key(stored_key)
        else:
            self._app_key = secrets.token_bytes(16)
            hass.config_entries.async_update_entry(entry, data={**entry.data, "app_key": self._app_key.hex()})

        self._pairing_completed = bool(entry.data.get("paired", False))
        self._pairing_failed = False  # retained for older diagnostics; transient timeouts never set it
        self._last_pairing_notice_at = 0.0
        self._last_transport_notice_at = 0.0
        self._transport_failures = 0
        self._command_lock = asyncio.Lock()
        self._client: BleakClient | None = None
        self._tx_char: Any | None = None
        self._rx_char: Any | None = None
        self._packet_queue: asyncio.Queue[NinebotPacket | None] = asyncio.Queue(maxsize=128)
        self._initial_telemetry: NinebotPacket | None = None
        self._rx_buffer = bytearray()
        self._crypto: NinebotCrypto | None = None
        self._legacy_link: LegacyM365Link | None = None
        self._session_ready = False
        self._pairing_serial: bytes | None = None
        self._pending_pair_confirmation: NinebotPacket | None = None
        self._pending_pair_ack: NinebotPacket | None = None
        self._last_raw_packets: tuple[str, ...] = ()
        self._last_services: tuple[str, ...] = ()
        self._last_notification: str | None = None
        self._last_error: str | None = None
        self._last_telemetry_at: datetime | None = None
        self._telemetry_store = Store(hass, 1, storage_key(address), private=True)
        self._saved_snapshot: dict[str, Any] | None = None
        self._last_saved_at = 0.0
        self._last_speed_at: datetime | None = None
        self._setting_read_at: dict[str, datetime] = {}
        self._next_setting_read_at: dict[str, float] = {}
        self._empty_read_count = 0
        self._authentication_mode: str | None = None
        self._control_session_started_at: datetime | None = None
        self._stage = "idle"
        self._last_reply_command: str | None = None
        self._raw_notification_count = 0
        self._notification_callback_errors = 0
        self._rejected_crypto_frames = 0
        self._last_frame_issue: str | None = None
        self._disconnect_count = 0
        self._disconnect_cleanup_count = 0
        self._recovery_scan_count = 0
        self._existing_key_retries = 0
        self._extra_index = 0
        self._dynamic_extra_index = 0
        self._extra_supported: dict[str, bool] = {}
        self._extra_payload_lengths: dict[str, int] = {}
        self._last_protocol = "BLE129/NinebotCrypto"
        self._retry_not_before = 0.0
        self._gatt_retry_cooldown = GATT_RETRY_COOLDOWN
        self._gatt_attempts = 0
        self._gatt_successes = 0
        self._gatt_last_duration_s: float | None = None
        self._gatt_last_failure: dict[str, Any] | None = None
        self._last_seen_rssi: int | None = None
        self._last_seen_scanner_source: str | None = None
        self._connected_scanner_source: str | None = None
        self._gatt_connected_at: float | None = None
        self._last_unexpected_session_duration_s: float | None = None
        self._scanner_last_seen: dict[str, tuple[float, int | None]] = {}
        self._scanner_avoid_until: dict[str, float] = {}
        self._scanner_short_disconnects: dict[str, int] = {}
        # Scanner failover needs hardware validation before it can replace
        # Home Assistant's default connection selection.
        self._enable_scanner_failover = False
        self._last_failure_snapshot: dict[str, Any] | None = None
        self._last_rejected_frame_counter16: int | None = None
        # An address from BLE history is not a connection invitation. Consume
        # only the BLEDevice from a *live* HA BluetoothServiceInfoBleak event.
        self._pending_ble_device: Any | None = None
        self._pending_ble_name: str | None = None
        self._crypto_name_source: str | None = None
        self._crypto_name_matches_saved: bool | None = None
        self._last_write_mode: str | None = None
        self._last_lock_status_word: int | None = None
        self._last_b0_lock_byte: int | None = None
        self._pending_seen_at = 0.0
        self._gatt_attempt_active = False
        self._rearm_task: asyncio.Task[None] | None = None
        self._shutting_down = False

        super().__init__(
            hass,
            _LOGGER,
            name=f"ninebot_e_scooters_{address}",
            update_interval=timedelta(seconds=poll_interval),
        )
