"""Serialize last verified scooter telemetry without persisting session secrets."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, date, datetime
from typing import Any

from .protocols.data import ScooterData
from .utilities import finite_number


def storage_key(address: str) -> str:
    """Keep cached data scoped to the Bluetooth address across entry reloads."""
    return f"ninebot_e_scooters_telemetry_{address.replace(':', '').lower()}"


def snapshot(address: str, data: ScooterData, last_read_at: datetime | None) -> dict[str, Any]:
    """Return JSON-safe measurements, omitting raw packets and crypto material."""
    return {
        "address": address.upper(),
        "last_read_at": last_read_at.isoformat() if last_read_at is not None else None,
        "values": {
            field.name: list(value) if isinstance(value, tuple) else value
            for field in fields(ScooterData)
            if field.name != "raw_packets"
            if (value := getattr(data, field.name)) is not None
        },
    }


def restore(payload: Any, address: str) -> tuple[ScooterData | None, datetime | None]:
    """Ignore old, foreign or malformed snapshots instead of trusting cache blindly."""
    if not isinstance(payload, dict) or payload.get("address") != address.upper():
        return None, None
    values = payload.get("values")
    if not isinstance(values, dict):
        return None, None
    allowed = {field.name for field in fields(ScooterData)} - {"raw_packets"}
    cleaned = {name: value for name, value in values.items() if name in allowed}
    text_fields = {"serial", "firmware_version", "bms_version", "ble_version"}
    bool_fields = {"is_cruise_on", "is_tail_light_on", "is_lock_on"}
    for name, value in tuple(cleaned.items()):
        if value is None:
            cleaned.pop(name)
        elif name in text_fields:
            if not isinstance(value, str):
                cleaned.pop(name)
        elif name == "battery_manufacture_date":
            try:
                if not isinstance(value, str) or date.fromisoformat(value) > date.today():
                    cleaned.pop(name)
            except ValueError:
                cleaned.pop(name)
        elif name in bool_fields:
            if not isinstance(value, bool):
                cleaned.pop(name)
        elif name != "battery_cell_voltages" and (
            not finite_number(value)
        ):
            cleaned.pop(name)
    cells = cleaned.get("battery_cell_voltages", ())
    if not isinstance(cells, list) or not all(
        finite_number(value)
        for value in cells
    ):
        cleaned["battery_cell_voltages"] = ()
    else:
        cleaned["battery_cell_voltages"] = tuple(cells)
    data = ScooterData(**cleaned)
    if not any(getattr(data, field.name) is not None for field in fields(ScooterData)
               if field.name not in ("raw_packets", "battery_cell_voltages")):
        return None, None
    try:
        last_read_at = datetime.fromisoformat(payload["last_read_at"])
        if last_read_at.tzinfo is None:
            last_read_at = None
        else:
            last_read_at = last_read_at.astimezone(UTC)
    except (KeyError, TypeError, ValueError):
        last_read_at = None
    return data, last_read_at
