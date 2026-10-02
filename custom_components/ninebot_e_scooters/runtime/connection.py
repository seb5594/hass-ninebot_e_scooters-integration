"""Fresh-advertisement connection scheduling and deterministic GATT cleanup."""

from __future__ import annotations
import asyncio
from typing import Any
from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    BleakOutOfConnectionSlotsError,
    establish_connection,
)
from homeassistant.components import bluetooth
from ..compat import (
    async_request_active_scan,
    clear_advertisement_history,
    create_background_task,
    describe_unreachable_scooter,
)
from ..storage import snapshot
from ..utilities import TIMEOUT_ERRORS
from .errors import ScooterConnectionError
from .constants import (
    DIRECT_GATT_TIMEOUT,
    GATT_CLEANUP_COOLDOWN,
    GATT_RETRY_COOLDOWN,
    SCANNER_ALTERNATIVE_MIN_RSSI,
    SCANNER_RECENT_SECONDS,
    SCANNER_SOURCE_COOLDOWN,
    SHORT_SESSION_SECONDS,
)
import logging

_LOGGER = logging.getLogger(__name__)


class ConnectionMixin:
    """Connection operations on the coordinator session."""

    def async_note_scanner_advertisement(self, service_info: Any) -> None:
        """Record the source of each live advertisement, including busy polls."""
        if (not getattr(service_info, "connectable", False)
                or service_info.address.upper() != self.address.upper()):
            return
        source = getattr(service_info, "source", None)
        if source:
            self._scanner_last_seen[source] = (
                asyncio.get_running_loop().time(), getattr(service_info, "rssi", None)
            )

    def async_on_live_advertisement(self, service_info: Any) -> bool:
        """Reserve exactly the BLEDevice from a fresh connectable advertisement.

        Never replace it with a MAC lookup from Home Assistant history. The
        device and its BlueZ D-Bus path are valid only for this short window.
        """
        if self._shutting_down or not service_info.connectable:
            return False
        if service_info.address.upper() != self.address.upper():
            return False
        self.async_note_scanner_advertisement(service_info)
        if self._command_lock.locked() or (
            self._client is not None and self._client.is_connected
        ):
            return False
        now = asyncio.get_running_loop().time()
        if now < self._retry_not_before or self._pending_ble_device is not None:
            return False
        source = getattr(service_info, "source", None)
        if (getattr(self, "_enable_scanner_failover", False)
                and source and now < self._scanner_avoid_until.get(source, 0.0)):
            alternative = next((
                other for other, (last_seen, rssi) in self._scanner_last_seen.items()
                if (other != source
                    and now >= self._scanner_avoid_until.get(other, 0.0)
                    and now - last_seen <= SCANNER_RECENT_SECONDS
                    and rssi is not None and rssi >= SCANNER_ALTERNATIVE_MIN_RSSI)
            ), None)
            if alternative is not None:
                _LOGGER.debug(
                    "Scooter scanner %s cooling down; waiting for live advertisement "
                    "from alternate scanner %s", source, alternative,
                )
                return False
        self._pending_ble_device = service_info.device
        self._pending_ble_name = getattr(service_info, "name", None)
        self._pending_seen_at = now
        self._last_seen_rssi = getattr(service_info, "rssi", None)
        self._last_seen_scanner_source = getattr(service_info, "source", None)
        _LOGGER.info(
            "Scooter live advertisement captured; scheduling GATT connect "
            "(scanner=%s, rssi=%s)",
            self._last_seen_scanner_source, self._last_seen_rssi,
        )
        return True

    async def _async_rearm_after_cooldown(self) -> None:
        """Clear HA's identical-advertisement filter after connection cooldown.

        Clearing immediately after a failed attempt would let a broadcast
        *during* the cooldown be deduplicated forever after the cooldown.
        """
        try:
            # The next failure can extend the deadline during sleep or a
            # recovery scan. Check it again before ending this task.
            while not self._shutting_down:
                remaining = self._retry_not_before - asyncio.get_running_loop().time()
                if remaining > 0:
                    await asyncio.sleep(remaining)
                    continue
                clear_advertisement_history(self.hass, self.address)
                _LOGGER.debug("Scooter advertisement history rearmed for next live sighting")
                if getattr(self, "_gatt_last_failure", None) is not None:
                    # A config-entry reload triggers a fresh discovery; do
                    # the same after a failed automatic GATT reconnect.
                    try:
                        self._recovery_scan_count = getattr(self, "_recovery_scan_count", 0) + 1
                        await async_request_active_scan(self.hass, duration=4.0)
                    except Exception:
                        _LOGGER.debug("Scooter Bluetooth recovery scan failed", exc_info=True)
                if self._retry_not_before <= asyncio.get_running_loop().time():
                    break
        finally:
            self._rearm_task = None

    def _rearm_advertisements(self) -> None:
        if self._shutting_down:
            return
        if self._rearm_task is not None and not self._rearm_task.done():
            return
        self._rearm_task = create_background_task(
            self.entry,
            self.hass,
            self._async_rearm_after_cooldown(),
            f"ninebot_e_scooters_rearm_{self.entry.entry_id}",
        )

    async def async_test_gatt_connection(self) -> None:
        """Verify that the scooter accepts a basic GATT connection."""
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass,
            self.address,
            connectable=True,
        )
        if ble_device is None:
            await async_request_active_scan(self.hass)
            for _ in range(6):
                await asyncio.sleep(0.5)
                ble_device = bluetooth.async_ble_device_from_address(
                    self.hass,
                    self.address,
                    connectable=True,
                )
                if ble_device is not None:
                    break
        if ble_device is None:
            raise ScooterConnectionError(
                "Home Assistant has no currently reachable Bluetooth path: "
                f"{describe_unreachable_scooter(self.hass, self.address)}"
            )
        client = await self._async_establish_client(ble_device)
        try:
            self._last_services = tuple(
                str(service.uuid).lower()
                for service in client.services
            )
        except BleakError as err:
            raise ScooterConnectionError(f"GATT connection failed: {err}") from err
        finally:
            if client.is_connected:
                await client.disconnect()

    async def async_shutdown(self) -> None:
        """Stop the BLE session and cancel this entry's advertisement rearm."""
        self._shutting_down = True
        # Interrupt an in-flight 0x5C/telemetry waiter before acquiring its
        # command lock. Otherwise unloading may wait for the full pairing window.
        if self._packet_queue.full():
            self._packet_queue.get_nowait()
        self._packet_queue.put_nowait(None)
        if self.data is not None and self._last_telemetry_at is not None:
            self._saved_snapshot = snapshot(self.address, self.data, self._last_telemetry_at)
        if self._saved_snapshot is not None:
            try:
                await self._telemetry_store.async_save(self._saved_snapshot)
            except OSError:
                _LOGGER.warning("Could not save scooter telemetry on unload", exc_info=True)
        if self._rearm_task is not None:
            self._rearm_task.cancel()
        # Serialize unload with a running read; otherwise its crypto and queue
        # vanish while the saved-session probe is awaiting a BLE reply.
        async with self._command_lock:
            await self._async_disconnect()

    async def _async_establish_client(self, ble_device: Any) -> Any:
        """Connect to the fresh HA BLEDevice with managed BlueZ cleanup.

        m365py opens a new peripheral for each connection attempt and enables
        notifications only after the link exists.  We preserve that lifecycle
        while still using Home Assistant's freshly discovered BLEDevice rather
        than starting our own scanner or connecting by a stale MAC lookup.
        """
        self._stage = "gatt_connect"
        self._gatt_retry_cooldown = GATT_RETRY_COOLDOWN
        self._gatt_attempts += 1
        loop = asyncio.get_running_loop()
        connect_started = loop.time()

        details = getattr(ble_device, "details", None)
        address_type = None
        bluez_path = None
        if isinstance(details, dict):
            props = details.get("props")
            if isinstance(props, dict):
                address_type = props.get("AddressType")
            bluez_path = details.get("path")
        self._last_ble_address_type = address_type
        self._last_bluez_path = bluez_path

        _LOGGER.info(
            "Scooter BLE phase: %s (attempt=%d, fresh_age=%.2fs, rssi=%s, "
            "address_type=%s)",
            self._stage,
            self._gatt_attempts,
            loop.time() - self._pending_seen_at,
            self._last_seen_rssi,
            address_type or "unknown",
        )

        def _disconnected(client: BleakClient) -> None:
            if self._shutting_down or client is not self._client:
                return
            now = asyncio.get_running_loop().time()
            if getattr(self, "_gatt_connected_at", None) is not None:
                self._last_unexpected_session_duration_s = round(
                    now - self._gatt_connected_at, 2
                )
            source = getattr(self, "_connected_scanner_source", None)
            if (getattr(self, "_enable_scanner_failover", False)
                    and source and self._last_unexpected_session_duration_s is not None):
                if self._last_unexpected_session_duration_s < SHORT_SESSION_SECONDS:
                    short_count = self._scanner_short_disconnects.get(source, 0) + 1
                    self._scanner_short_disconnects[source] = short_count
                    if short_count >= 2:
                        self._scanner_avoid_until[source] = now + SCANNER_SOURCE_COOLDOWN
                else:
                    self._scanner_short_disconnects.pop(source, None)
            self._session_ready = False
            # Refresh the connectivity binary sensor immediately rather than
            # waiting for the next telemetry interval after a dropped link.
            if (update_listeners := getattr(self, "async_update_listeners", None)) is not None:
                update_listeners()
            self._pending_ble_device = None
            self._disconnect_count += 1
            self._stage = "gatt_disconnected"
            # Wake the current 0x5B/read waiter immediately. Waiting for its
            # full response timeout hid the real link loss in diagnostics.
            if self._packet_queue.full():
                self._packet_queue.get_nowait()
            self._packet_queue.put_nowait(None)
            self._last_error = "Bluetooth disconnected; waiting for a fresh advertisement"
            self._retry_not_before = max(
                self._retry_not_before, asyncio.get_running_loop().time() + GATT_RETRY_COOLDOWN
            )
            _LOGGER.info(
                "Scooter GATT disconnected unexpectedly (count=%d, scanner=%s, "
                "session_duration_s=%s); waiting for a fresh live advertisement",
                self._disconnect_count, getattr(self, "_connected_scanner_source", None),
                getattr(self, "_last_unexpected_session_duration_s", None),
            )
            self._rearm_advertisements()
            # Release the previous BlueZ client even when no refresh is in
            # progress. A config-entry reload used to perform this cleanup;
            # subsequent automatic connects could otherwise race the old link.
            create_background_task(
                self.entry,
                self.hass,
                self._async_cleanup_disconnected_client(client),
                f"ninebot_e_scooters_disconnect_cleanup_{self.entry.entry_id}",
            )

        client: BleakClient | None = None
        try:
            # A paired scooter may need a second GATT attempt after a brief
            # disconnect. Keep initial pairing to one attempt.
            client = await establish_connection(
                BleakClientWithServiceCache, ble_device, self.device_name,
                disconnected_callback=_disconnected,
                max_attempts=2 if self._pairing_completed else 1,
                use_services_cache=False,
                timeout=DIRECT_GATT_TIMEOUT,
            )
            if not client.is_connected:
                raise BleakError("BleakClient.connect returned without an active connection")
            self._gatt_successes += 1
            self._gatt_last_duration_s = round(loop.time() - connect_started, 2)
            self._gatt_last_failure = None
            self._gatt_connected_at = loop.time()
            self._connected_scanner_source = getattr(self, "_last_seen_scanner_source", None)
            _LOGGER.info("Scooter GATT connected in %.2fs", self._gatt_last_duration_s)
            return client
        except BaseException as err:
            duration = round(loop.time() - connect_started, 2)
            self._gatt_last_duration_s = duration
            # Bleak may still be unwinding BlueZ's D-Bus Device1.Connect.
            # Wait for the scanner to see a new advertisement rather than
            # hammering the same backend immediately after this timeout.
            # Bleak reports both "disconnect timed out: True" and "...False".
            # The latter is NOT a failed disconnect; either indicates that
            # BlueZ needed to unwind the preceding connect attempt.
            prolonged_cleanup = (
                "disconnect timed out:" in str(err).lower()
                or duration >= DIRECT_GATT_TIMEOUT + 10.0
            )
            slot_exhausted = isinstance(err, BleakOutOfConnectionSlotsError)
            source = getattr(self, "_last_seen_scanner_source", None)
            if (getattr(self, "_enable_scanner_failover", False)
                    and source and isinstance(err, (BleakError, *TIMEOUT_ERRORS))):
                self._scanner_avoid_until[source] = loop.time() + SCANNER_SOURCE_COOLDOWN
            self._gatt_retry_cooldown = (
                GATT_CLEANUP_COOLDOWN if prolonged_cleanup or slot_exhausted else GATT_RETRY_COOLDOWN
            )
            self._gatt_last_failure = {
                "kind": type(err).__name__,
                "duration_s": duration,
                "bluez_cleanup_after_connect_timeout": prolonged_cleanup,
                "connection_slots_exhausted": slot_exhausted,
                "address_type": str(address_type) if address_type else None,
                "rssi": self._last_seen_rssi,
                "scanner_source": getattr(self, "_last_seen_scanner_source", None),
                "cooldown_s": self._gatt_retry_cooldown,
            }
            _LOGGER.info(
                "Scooter GATT failed after %.2fs (%s); BlueZ cooldown %.0fs",
                duration, type(err).__name__, self._gatt_retry_cooldown,
            )
            try:
                if client is not None and client.is_connected:
                    await asyncio.wait_for(client.disconnect(), timeout=2.0)
            except (BleakError, *TIMEOUT_ERRORS):
                pass
            raise

    async def _async_cleanup_disconnected_client(self, client: BleakClient) -> None:
        """Finish a lost link before allowing a fresh client to take its slot."""
        async with self._command_lock:
            if self._shutting_down or self._client is not client:
                return
            await self._async_disconnect()
            self._disconnect_cleanup_count = getattr(self, "_disconnect_cleanup_count", 0) + 1

    async def _async_disconnect(self) -> None:
        """Close the active BLE connection and reset only transport state."""
        client = self._client
        rx_char = self._rx_char
        had_gatt_attempt = self._gatt_attempt_active
        self._gatt_attempt_active = False
        self._pending_ble_device = None
        self._pending_ble_name = None
        self._client = None
        self._tx_char = None
        self._rx_char = None
        self._session_ready = False
        if (update_listeners := getattr(self, "async_update_listeners", None)) is not None:
            update_listeners()
        self._control_session_started_at = None
        self._crypto = None
        self._legacy_link = None
        self._initial_telemetry = None
        self._pending_pair_confirmation = None
        self._pending_pair_ack = None
        self._authentication_mode = None
        self._packet_queue = asyncio.Queue(maxsize=128)
        self._rx_buffer.clear()
        try:
            if client is not None and client.is_connected:
                if rx_char is not None:
                    try:
                        await asyncio.wait_for(client.stop_notify(rx_char), timeout=2.0)
                    except (BleakError, *TIMEOUT_ERRORS):
                        pass
            # Bleak can report is_connected=False while BlueZ is still
            # releasing the old Device1 connection. Always complete teardown.
            if client is not None:
                await asyncio.wait_for(client.disconnect(), timeout=5.0)
        except (BleakError, *TIMEOUT_ERRORS):
            _LOGGER.debug("Scooter BlueZ disconnect did not complete in time")
        finally:
            if had_gatt_attempt:
                # Clear only after disconnect; if reconnect is cooling down,
                # defer clearing until it is actually eligible to reconnect.
                self._rearm_advertisements()
