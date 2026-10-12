"""Everything that differs between Home Assistant releases lives in this module.

The rest of the integration is written against a single, current API. Each
helper below names the release that introduced the feature it papers over, so
it can be deleted once the minimum version in hacs.json has passed that release.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
import json
from collections.abc import Callable, Coroutine, Iterable
from functools import cache
from pathlib import Path
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

try:  # Home Assistant 2024.7+
    from homeassistant.components.http import StaticPathConfig
except ImportError:
    StaticPathConfig = None

try:  # Home Assistant 2024.4+
    from homeassistant.config_entries import ConfigFlowResult
except ImportError:
    from homeassistant.data_entry_flow import FlowResult as ConfigFlowResult

try:  # Home Assistant 2023.8+
    from homeassistant.helpers.device_registry import DeviceInfo
except ImportError:
    from homeassistant.helpers.entity import DeviceInfo

try:  # Home Assistant 2024.3+
    from homeassistant.helpers.redact import async_redact_data
except ImportError:
    from homeassistant.components.diagnostics import async_redact_data

__all__ = [
    "ConfigFlowResult",
    "DeviceInfo",
    "EntityNameFallback",
    "async_redact_data",
    "async_register_scooter_callback",
    "async_register_static_files",
    "async_request_active_scan",
    "async_update_reload_and_abort",
    "clear_advertisement_history",
    "create_background_task",
    "describe_unreachable_scooter",
    "description_dataclass",
]

TRANSLATIONS = Path(__file__).parent / "translations" / "en.json"
LEGACY_BACKGROUND_TASKS: dict[str, set[asyncio.Task]] = {}

# Entity descriptions are frozen dataclasses from Home Assistant 2024.1 on. A
# frozen dataclass cannot extend a mutable one, so older releases need the same.
description_dataclass = dataclass(
    frozen=(MAJOR_VERSION, MINOR_VERSION) >= (2024, 1), kw_only=True
)


def _accepts(function: Callable[..., Any], keyword: str) -> bool:
    """Tell whether a Home Assistant function takes the given keyword argument."""
    parameters = inspect.signature(function).parameters
    return keyword in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    )


def async_update_reload_and_abort(
    flow: Any, entry: ConfigEntry, updates: dict[str, Any], reason: str
) -> ConfigFlowResult:
    """Merge `updates` into the entry data, reload it and end the flow.

    Home Assistant 2024.11+ merges `data_updates` itself; earlier releases only
    know `data`, which replaces the stored data as a whole.
    """
    if _accepts(flow.async_update_reload_and_abort, "data_updates"):
        return flow.async_update_reload_and_abort(entry, data_updates=updates, reason=reason)
    return flow.async_update_reload_and_abort(entry, data={**entry.data, **updates}, reason=reason)


def _cancel_legacy_background_tasks(entry_id: str) -> None:
    for task in LEGACY_BACKGROUND_TASKS.pop(entry_id, ()):
        task.cancel()


def _create_legacy_background_task(
    entry: ConfigEntry, hass: HomeAssistant, target: Coroutine[Any, Any, Any], name: str
) -> asyncio.Task:
    """Home Assistant before 2023.3 has no entry-bound tasks; cancel them on unload ourselves."""
    tasks = LEGACY_BACKGROUND_TASKS.get(entry.entry_id)
    if tasks is None:
        tasks = LEGACY_BACKGROUND_TASKS[entry.entry_id] = set()
        entry.async_on_unload(lambda: _cancel_legacy_background_tasks(entry.entry_id))
    task = hass.loop.create_task(target, name=name)
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return task


def create_background_task(
    entry: ConfigEntry, hass: HomeAssistant, target: Coroutine[Any, Any, Any], name: str
) -> Any:
    """Schedule a task tied to the entry that starts on the next loop iteration.

    Home Assistant 2024.3+ can start tasks eagerly, which would run the first
    steps inside the caller. Older releases always schedule them lazily.
    """
    if not hasattr(entry, "async_create_background_task"):  # before Home Assistant 2023.3
        return _create_legacy_background_task(entry, hass, target, name)
    if _accepts(entry.async_create_background_task, "eager_start"):
        return entry.async_create_background_task(hass, target, name, eager_start=False)
    return entry.async_create_background_task(hass, target, name)


async def async_register_static_files(
    hass: HomeAssistant, files: Iterable[tuple[str, Path]]
) -> None:
    """Serve bundled files from the user's origin, with browser caching."""
    if StaticPathConfig is not None:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(url, str(path), True) for url, path in files]
        )
        return
    for url, path in files:
        hass.http.register_static_path(url, str(path), True)


async def async_request_active_scan(hass: HomeAssistant, **options: Any) -> None:
    """Ask for a one-shot active scan; a no-op where Home Assistant lacks it.

    Without the API the scooter is still found as soon as it advertises, the
    callers just wait for that advertisement instead of provoking one.
    """
    request = getattr(bluetooth, "async_request_active_scan", None)
    if request is not None:
        await request(hass, **options)


def clear_advertisement_history(hass: HomeAssistant, address: str) -> None:
    """Make Home Assistant report the next identical advertisement again.

    Older releases deduplicate silently; the integration's periodic check of the
    latest sighting covers that case.
    """
    clear = getattr(bluetooth, "async_clear_advertisement_history", None)
    if clear is not None:
        clear(hass, address)


def describe_unreachable_scooter(hass: HomeAssistant, address: str) -> str:
    """Explain why no Bluetooth path to the scooter exists, as precisely as possible."""
    diagnose = getattr(bluetooth, "async_address_reachability_diagnostics", None)
    intent = getattr(bluetooth, "BluetoothReachabilityIntent", None)
    if diagnose is not None and intent is not None:
        return str(diagnose(hass, address, intent.CONNECTION))
    scanners = bluetooth.async_scanner_count(hass, connectable=True)
    return f"{scanners} connectable Bluetooth scanner(s) available, none has seen {address}"


def async_register_scooter_callback(
    hass: HomeAssistant,
    callback: Callable[..., None],
    address: str,
    *,
    scan_interval: float,
    scan_duration: float,
) -> Callable[[], None]:
    """Register for the scooter's advertisements and return the unsubscribe function.

    Replaying the newest cached sighting and tuning the active-scan cadence are
    recent features; releases without them still deliver live advertisements.
    """
    optional: dict[str, Any] = {"scan_interval": scan_interval, "scan_duration": scan_duration}
    replay = getattr(bluetooth, "BluetoothCallbackReplay", None)
    if replay is not None:
        optional["replay"] = replay.NEWEST_FIRST
    return bluetooth.async_register_callback(
        hass,
        callback,
        {"address": address, "connectable": True},
        bluetooth.BluetoothScanningMode.ACTIVE,
        **{
            key: value
            for key, value in optional.items()
            if _accepts(bluetooth.async_register_callback, key)
        },
    )


@cache
def _english_entity_names() -> dict[str, dict[str, str]]:
    """Map platform -> translation key -> English name from the bundled translation."""
    entities = json.loads(TRANSLATIONS.read_text(encoding="utf-8")).get("entity", {})
    return {
        platform: {key: value["name"] for key, value in names.items() if "name" in value}
        for platform, names in entities.items()
    }


if hasattr(Entity, "_name_translation_key"):  # Home Assistant 2023.7+

    class EntityNameFallback:
        """Entity names come from the translation files; nothing to add."""

else:

    class EntityNameFallback:
        """Name entities from the English translation on releases without name translations.

        Without it every entity of the scooter would carry just the device name.
        """

        @property
        def name(self) -> str | None:
            """Return the English name registered for this entity's translation key."""
            description = getattr(self, "entity_description", None)
            key = getattr(self, "_attr_translation_key", None) or getattr(
                description, "translation_key", None
            )
            platform = type(self).__module__.rsplit(".", 1)[-1]
            return _english_entity_names().get(platform, {}).get(key)
