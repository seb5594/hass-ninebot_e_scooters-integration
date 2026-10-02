"""Transport-independent scooter telemetry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
        """Return a serializable diagnostics dictionary."""
        data = {
            key: value
            for key, value in {
                "serial": self.serial,
                "firmware_version": self.firmware_version,
                "bms_version": self.bms_version,
                "ble_version": self.ble_version,
                "battery_capacity_ah": self.battery_capacity_ah,
                "battery_percent": self.battery_percent,
                "battery_current_a": self.battery_current_a,
                "battery_voltage_v": self.battery_voltage_v,
                "battery_temperature_1_c": self.battery_temperature_1_c,
                "battery_temperature_2_c": self.battery_temperature_2_c,
                "battery_cell_voltages": list(self.battery_cell_voltages),
                "speed_kmh": self.speed_kmh,
                "speed_average_kmh": self.speed_average_kmh,
                "odometer_km": self.odometer_km,
                "trip_distance_m": self.trip_distance_m,
                "distance_left_km": self.distance_left_km,
                "uptime_s": self.uptime_s,
                "frame_temperature_c": self.frame_temperature_c,
                "error_flags": self.error_flags,
                "warning_flags": self.warning_flags,
                "status_flags": self.status_flags,
                "bms_status_flags": self.bms_status_flags,
                "battery_charge_cycles": self.battery_charge_cycles,
                "battery_health_percent": self.battery_health_percent,
                "battery_manufacture_date": self.battery_manufacture_date,
                "work_mode": self.work_mode,
                "is_cruise_on": self.is_cruise_on,
                "is_tail_light_on": self.is_tail_light_on,
                "is_lock_on": self.is_lock_on,
                "kers_mode": self.kers_mode,
                "battery_power_w": self.battery_power_w,
                "battery_cell_min_v": self.battery_cell_min_v,
                "battery_cell_max_v": self.battery_cell_max_v,
                "battery_cell_delta_v": self.battery_cell_delta_v,
            }.items()
            if value is not None
        }

        if include_raw:
            data["raw_packets"] = list(self.raw_packets)

        return data
