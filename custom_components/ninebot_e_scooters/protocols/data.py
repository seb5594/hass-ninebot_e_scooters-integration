"""Transport-independent scooter telemetry."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

# Computed from stored values; reported next to them in diagnostics.
DERIVED_VALUES = (
    "battery_power_w", "battery_cell_min_v", "battery_cell_max_v", "battery_cell_delta_v",
)


@dataclass(slots=True)
class ScooterData:
    """All decoded scooter values known by the integration."""

    serial: str | None = None
    firmware_version: str | None = None
    bms_version: str | None = None
    ble_version: str | None = None

    battery_capacity_ah: float | None = None
    battery_percent: float | None = None
    battery_current_a: float | None = None
    battery_voltage_v: float | None = None
    battery_temperature_1_c: float | None = None
    battery_temperature_2_c: float | None = None
    battery_cell_voltages: tuple[float, ...] = ()

    speed_kmh: float | None = None
    speed_average_kmh: float | None = None
    odometer_km: float | None = None
    trip_distance_m: float | None = None
    distance_left_km: float | None = None
    uptime_s: int | None = None
    frame_temperature_c: float | None = None

    error_flags: int | None = None
    warning_flags: int | None = None
    status_flags: int | None = None
    bms_status_flags: int | None = None
    battery_charge_cycles: int | None = None
    battery_health_percent: int | None = None
    battery_manufacture_date: str | None = None
    work_mode: int | None = None

    is_cruise_on: bool | None = None
    is_tail_light_on: bool | None = None
    is_lock_on: bool | None = None
    kers_mode: int | None = None

    raw_packets: tuple[str, ...] = ()

    @property
    def battery_power_w(self) -> float | None:
        """Return instantaneous battery power when both inputs are known."""
        if self.battery_voltage_v is None or self.battery_current_a is None:
            return None
        return self.battery_voltage_v * self.battery_current_a

    @property
    def battery_cell_min_v(self) -> float | None:
        """Return the minimum cell voltage."""
        if not self.battery_cell_voltages:
            return None
        return min(self.battery_cell_voltages)

    @property
    def battery_cell_max_v(self) -> float | None:
        """Return the maximum cell voltage."""
        if not self.battery_cell_voltages:
            return None
        return max(self.battery_cell_voltages)

    @property
    def battery_cell_delta_v(self) -> float | None:
        """Return the cell voltage spread."""
        if not self.battery_cell_voltages:
            return None
        return max(self.battery_cell_voltages) - min(self.battery_cell_voltages)

    def as_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        """Return every known value, stored or derived, as a serializable dictionary."""
        values: dict[str, Any] = {
            field.name: getattr(self, field.name)
            for field in fields(self)
            if field.name != "raw_packets"
        }
        values["battery_cell_voltages"] = list(self.battery_cell_voltages)
        values.update({name: getattr(self, name) for name in DERIVED_VALUES})
        data = {name: value for name, value in values.items() if value is not None}

        if include_raw:
            data["raw_packets"] = list(self.raw_packets)

        return data
