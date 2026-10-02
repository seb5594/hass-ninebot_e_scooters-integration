"""Privacy-aware, JSON-safe diagnostics for the Ninebot E-Scooters integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .const import CONF_POLL_INTERVAL
from .coordinator import ScooterCoordinator

# A list/set of field names, NOT a dict mapping fields to string replacements:
# HA's helper treats mapping values as callable redaction functions.
TO_REDACT = (
    "address", "serial", "app_key", "bluetooth_name", "device_name", "title",
    "last_bluez_path", "last_seen_scanner_source", "connected_scanner_source", "scanner_source",
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry[ScooterCoordinator],
) -> dict[str, Any]:
    """Return serializable, redacted diagnostics without initiating Bluetooth I/O.

    A half-loaded config entry is also supported so diagnostics stay available
    when setting up GATT or authenticating a stored key failed.
    """
    coordinator = getattr(entry, "runtime_data", None)
    diagnostics: dict[str, Any] = {}
    services: list[str] = []
    if coordinator is not None:
        diagnostics = dict(coordinator.diagnostics)
        services = list(getattr(coordinator, "_last_services", ()))
        # Raw binary notifications can contain device-identifying content.
        # The counters, last decoded reply and validation errors are sufficient
        # for the current connection/pairing troubleshooting workflow.
        diagnostics.pop("last_notification", None)
        diagnostics.pop("raw_packets", None)
        # Scanner identifiers can also be dictionary keys, outside HA's field redaction.
        for name in ("scanner_short_disconnects", "scanner_retry_cooldown_remaining_s"):
            if isinstance(diagnostics.get(name), dict):
                diagnostics[name] = {
                    f"scanner_{index}": value
                    for index, value in enumerate(diagnostics[name].values(), start=1)
                }
        address = entry.data.get("address")
        if address and isinstance(diagnostics.get("last_error"), str):
            diagnostics["last_error"] = diagnostics["last_error"].replace(
                address, "**REDACTED**"
            )

    return {
        "diagnostics_schema": 2,
        "legacy_m365_nus_present": any(
            "6e400001-b5a3-f393-e0a9-e50e24dcca9e" in service
            for service in services
        ),
        "entry": async_redact_data(
            {
                "title": entry.title,
                "data": dict(entry.data),
                "options": {
                    CONF_POLL_INTERVAL: entry.options.get(CONF_POLL_INTERVAL),
                },
            },
            TO_REDACT,
        ),
        "coordinator": async_redact_data(diagnostics, TO_REDACT),
    }
