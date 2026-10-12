"""Ninebot E-Scooters integration; defer all Bluetooth work until HA is running."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from functools import partial
import logging
from pathlib import Path
import time
from typing import TypeAlias

from homeassistant.components import bluetooth
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .compat import (
    async_register_scooter_callback,
    async_register_static_files,
    async_request_active_scan,
    clear_advertisement_history,
    create_background_task,
)
from .const import (
    CONF_MODEL,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    MODEL,
    PLATFORMS,
)
from .coordinator import ScooterCoordinator
from .sensor_groups import selected_sensor_groups

_LOGGER = logging.getLogger(__name__)

# A string, because ConfigEntry only became subscriptable in Home Assistant 2024.8.
NinebotScooterConfigEntry: TypeAlias = "ConfigEntry[ScooterCoordinator]"

# HA deduplicates identical broadcasts for integration callbacks.  Its last
# service_info timestamp is still updated by the scanner; check it on a cheap
# timer rather than reusing a stale cached BLEDevice or creating a 2nd scanner.
MAX_LIVE_ADVERTISEMENT_AGE_SECONDS = 4.0
ADVERTISEMENT_CHECK_INTERVAL = timedelta(seconds=3)


def _recent_connectable_info(info: object | None) -> bool:
    """Accept only genuinely recent HA sightings, never historical replays."""
    if info is None or not getattr(info, "connectable", False):
        return False
    if getattr(info, "device", None) is None:
        return False
    timestamp = getattr(info, "time", None)
    if not isinstance(timestamp, (int, float)) or not timestamp:
        return False
    # HA's service info normally uses monotonic time. This also handles the
    # epoch timestamps exposed by some advertisement-monitor representations.
    now = time.time() if timestamp > 1_000_000_000 else time.monotonic()
    age = now - timestamp
    return -1.0 <= age <= MAX_LIVE_ADVERTISEMENT_AGE_SECONDS


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration without opening a Bluetooth connection."""
    # Serve the bundled animation from the user's HA origin. Every frontend
    # session can render the same image without writing into /config/www.
    assets = Path(__file__).parent / "assets"
    await async_register_static_files(hass, [
        ("/api/ninebot_e_scooters/power_button.gif", assets / "power_button.gif"),
        ("/api/ninebot_e_scooters/pairing_dialog.js", assets / "pairing_dialog.js"),
    ])
    # Home Assistant loads the module on each frontend page without editing
    # configuration.yaml or individual dashboards. It watches only our
    # pairing notices; the stored app key never enters the browser.
    add_extra_js_url(hass, "/api/ninebot_e_scooters/pairing_dialog.js?v=1.0.0b1")
    return True


async def _async_options_updated(
    hass: HomeAssistant,
    entry: NinebotScooterConfigEntry,
    *,
    applied_sensor_groups: frozenset[str] = frozenset(),
) -> None:
    """Apply polling, model and sensor group options through one clean BLE reconnect."""
    # Pairing also updates entry.data. Reload only when the user changes an
    # actual option, or the first successful pairing would tear down its link.
    coordinator = entry.runtime_data
    if (coordinator.poll_interval != int(entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
            or coordinator.model != entry.options.get(CONF_MODEL, MODEL)
            or selected_sensor_groups(entry.options) != applied_sensor_groups):
        await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: NinebotScooterConfigEntry) -> bool:
    """Create entities at boot; register Bluetooth only when startup is finished."""
    setup_at = asyncio.get_running_loop().time()
    _LOGGER.info("Xiaomi Scooter config-entry setup started (HA state=%s)", hass.state)
    coordinator = ScooterCoordinator(
        hass,
        entry=entry,
        address=entry.data["address"],
        name=entry.data.get("bluetooth_name", entry.title),
        poll_interval=int(entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)),
    )
    await coordinator.async_restore_saved_data()
    entry.runtime_data = coordinator
    if hasattr(entry, "add_update_listener"):
        # Sensor groups decide which entities exist, so remember the ones in use.
        entry.async_on_unload(entry.add_update_listener(partial(
            _async_options_updated,
            applied_sensor_groups=selected_sensor_groups(entry.options),
        )))

    bluetooth_activated = False
    refresh_task: asyncio.Task | None = None
    last_waiting_log = 0.0

    @callback
    def _schedule_from_info(service_info) -> None:
        """Start at most one background GATT attempt from a fresh HA sighting."""
        nonlocal refresh_task
        if hass.state is not CoreState.running or not _recent_connectable_info(service_info):
            return
        if service_info.address.upper() != coordinator.address.upper():
            return
        coordinator.async_note_scanner_advertisement(service_info)
        if refresh_task is not None and not refresh_task.done():
            return
        if coordinator.async_on_live_advertisement(service_info):
            refresh_task = create_background_task(
                entry,
                hass,
                # Do not use request_refresh() here: its debouncer can delay
                # work long enough to invalidate the exact BlueZ BLEDevice.
                coordinator.async_refresh(),
                f"ninebot_e_scooters_live_gatt_{entry.entry_id}",
            )

    @callback
    def _scooter_advertised(service_info, _change) -> None:
        _schedule_from_info(service_info)

    @callback
    def _scooter_advertised_by_any_scanner(service_info) -> None:
        """Consider fresh sightings from backup scanners after radio failures."""
        _schedule_from_info(service_info)

    @callback
    def _check_latest_advertisement(_now=None) -> None:
        """Recover an unchanged broadcast suppressed by HA deduplication."""
        nonlocal last_waiting_log
        if hass.state is not CoreState.running:
            return
        if coordinator._session_ready and coordinator._client is not None and coordinator._client.is_connected:
            return
        info = bluetooth.async_last_service_info(
            hass, coordinator.address, connectable=True
        )
        if _recent_connectable_info(info):
            _schedule_from_info(info)
            return
        now = asyncio.get_running_loop().time()
        if now - last_waiting_log >= 60:
            last_waiting_log = now
            _LOGGER.info(
                "Scooter waiting for a live, connectable HA Bluetooth sighting "
                "(latest_age=%s, stage=%s)",
                None if info is None or getattr(info, 'time', None) is None else
                round((time.time() if info.time > 1_000_000_000 else time.monotonic()) - info.time, 1),
                coordinator._stage,
            )

    @callback
    def _activate_bluetooth() -> None:
        """Activate only after HA startup, also on a config-entry reload."""
        nonlocal bluetooth_activated
        if hass.state is not CoreState.running or bluetooth_activated:
            return
        bluetooth_activated = True
        entry.async_on_unload(
            # The newest cached sighting is replayed where supported; it is vetted
            # by its timestamp, unlike blindly trying a cached address from a
            # previous HA run.
            async_register_scooter_callback(
                hass,
                _scooter_advertised,
                coordinator.address,
                scan_interval=60.0,  # habluetooth minimum; not a connect delay.
                scan_duration=10.0,
            )
        )
        # Keep per-scanner selection disabled until it has been
        # validated against a real scooter and the user's Bluetooth setup.
        if (getattr(coordinator, "_enable_scanner_failover", False)
                and (register_all := getattr(bluetooth, "async_register_advertisement_callback", None)) is not None):
            entry.async_on_unload(register_all(
                hass, _scooter_advertised_by_any_scanner, coordinator.address,
            ))
        entry.async_on_unload(
            async_track_time_interval(hass, _check_latest_advertisement, ADVERTISEMENT_CHECK_INTERVAL)
        )
        clear_advertisement_history(hass, coordinator.address)
        _LOGGER.info(
            "Xiaomi Scooter Bluetooth activated after HA startup in %.2fs; "
            "checking HA's current advertisement now",
            asyncio.get_running_loop().time() - setup_at,
        )
        _check_latest_advertisement()

        async def _scan_now() -> None:
            """On a reload, actively discover a fresh BLEDevice immediately."""
            if coordinator._shutting_down or (
                coordinator._client is not None and coordinator._client.is_connected
            ) or coordinator._pending_ble_device is not None or coordinator._command_lock.locked():
                return
            try:
                await async_request_active_scan(hass, duration=4.0)
            except Exception:
                _LOGGER.debug("Scooter initial active scan failed", exc_info=True)
            if not coordinator._shutting_down:
                _check_latest_advertisement()

        create_background_task(
            entry,
            hass,
            _scan_now(),
            f"ninebot_e_scooters_immediate_scan_{entry.entry_id}",
        )

    # HA requires these platform setups to be awaited. No platform initiates
    # network or GATT activity and _async_update_data also checks CoreState.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info(
        "Xiaomi Scooter config-entry entity setup complete in %.2fs (HA state=%s)",
        asyncio.get_running_loop().time() - setup_at,
        hass.state,
    )

    if hass.state is CoreState.running:
        _activate_bluetooth()
    else:
        # Do not put an async_listen_once remover in async_on_unload: HA
        # removes that one-shot listener as soon as it fires, so a subsequent
        # config-entry reload tries to remove an already-removed job.
        # An ordinary listener with a guarded remover is safe in both orders:
        # reload-before-start and start-before-reload.
        unsub_started = None

        @callback
        def _cancel_start_listener() -> None:
            nonlocal unsub_started
            if unsub_started is not None:
                unsubscribe = unsub_started
                unsub_started = None
                unsubscribe()

        @callback
        def _on_ha_started(_event) -> None:
            _cancel_start_listener()
            _activate_bluetooth()

        unsub_started = hass.bus.async_listen(
            EVENT_HOMEASSISTANT_STARTED, _on_ha_started
        )
        entry.async_on_unload(_cancel_start_listener)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NinebotScooterConfigEntry) -> bool:
    """Unload entities and disconnect the scooter."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded
