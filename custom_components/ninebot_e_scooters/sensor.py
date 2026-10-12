"""Sensor entities for the Ninebot E-Scooters integration."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    Platform,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfPower,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity import EntityCategory

from .compat import description_dataclass
from .const import DOMAIN, REFERENCE_RANGE_KM, RIDE_MODE_LABELS_1S
from .coordinator import ScooterCoordinator
from .entity import ScooterEntity, async_remove_entities
from .protocols.data import ScooterData
from .sensor_groups import (
    BATTERY_HEALTH,
    DEVICE_INFO,
    RIDING,
    STATUS_CODES,
    TEMPERATURES,
    selected_sensor_groups,
)

AMPERE_HOURS = "Ah"
BATTERY_CELL_COUNT = 10

# Sensors of earlier releases; their registry entries are cleaned up on setup.
OBSOLETE_SENSOR_KEYS = ("connection_status", "kers_mode", "detected_model", "last_telemetry")

RIDE_MODE_STATES = {number: label.lower() for number, label in RIDE_MODE_LABELS_1S.items()}

# Device class and unit pairs shared by several sensors.
DISTANCE_KILOMETERS = {
    "device_class": SensorDeviceClass.DISTANCE,
    "native_unit_of_measurement": UnitOfLength.KILOMETERS,
}
DISTANCE_METERS = {
    "device_class": SensorDeviceClass.DISTANCE,
    "native_unit_of_measurement": UnitOfLength.METERS,
}
SPEED_KILOMETERS_PER_HOUR = {
    "device_class": SensorDeviceClass.SPEED,
    "native_unit_of_measurement": UnitOfSpeed.KILOMETERS_PER_HOUR,
}
TEMPERATURE_CELSIUS = {
    "device_class": SensorDeviceClass.TEMPERATURE,
    "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
}
VOLTAGE_VOLTS = {
    "device_class": SensorDeviceClass.VOLTAGE,
    "native_unit_of_measurement": UnitOfElectricPotential.VOLT,
}


@description_dataclass
class ScooterSensorDescription(SensorEntityDescription):
    """Describe a scooter sensor."""

    value_fn: Callable[[ScooterData], object] = lambda _data: None
    # None keeps the sensor always on; otherwise one of OPTIONAL_SENSOR_GROUPS.
    sensor_group: str | None = None


def _sensor(*, key: str, **attributes: Any) -> ScooterSensorDescription:
    """Every sensor is named by the translation that shares its key."""
    return ScooterSensorDescription(key=key, translation_key=key, **attributes)


def _reading(
    *, key: str, state_class: SensorStateClass = SensorStateClass.MEASUREMENT, **attributes: Any
) -> ScooterSensorDescription:
    """A numeric value Home Assistant keeps long-term statistics for."""
    return _sensor(key=key, state_class=state_class, **attributes)


def _diagnostic(*, key: str, **attributes: Any) -> ScooterSensorDescription:
    """A slowly changing fact about the hardware, listed under diagnostics."""
    return _sensor(key=key, entity_category=EntityCategory.DIAGNOSTIC, **attributes)


def _status_code(key: str) -> ScooterSensorDescription:
    """A raw 16-bit status register, printed as 0x0000 like service tools do."""
    return _diagnostic(
        key=key,
        sensor_group=STATUS_CODES,
        value_fn=lambda data: _as_hex_word(getattr(data, key)),
    )


def _cell_voltage(index: int) -> ScooterSensorDescription:
    """Voltage of one battery cell, counted from 1; hidden until enabled by hand."""
    return _reading(
        key=f"cell_{index}",
        sensor_group=BATTERY_HEALTH,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: _cell(data.battery_cell_voltages, index),
        **VOLTAGE_VOLTS,
    )


def _as_hex_word(value: int | None) -> str | None:
    return None if value is None else f"0x{value:04X}"


def _cell(voltages: tuple[float, ...], index: int) -> float | None:
    return voltages[index - 1] if len(voltages) >= index else None


def _manufacture_date(data: ScooterData) -> date | None:
    stored = data.battery_manufacture_date
    return date.fromisoformat(stored) if stored else None


def _reference_range_km(battery_percent: float | None, model: str) -> float | None:
    """Scale the manufacturer's range for the model by the current charge."""
    maximum = REFERENCE_RANGE_KM.get(model)
    if maximum is None or battery_percent is None:
        return None
    return round(maximum * max(0, min(100, battery_percent)) / 100, 1)


SENSORS: tuple[ScooterSensorDescription, ...] = (
    # Always on: what matters for a scooter parked at home.
    _reading(
        key="battery_percent",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: data.battery_percent,
    ),
    _reading(
        key="battery_capacity",
        native_unit_of_measurement=AMPERE_HOURS,
        value_fn=lambda data: data.battery_capacity_ah,
    ),
    _reading(
        key="battery_voltage",
        value_fn=lambda data: data.battery_voltage_v,
        **VOLTAGE_VOLTS,
    ),
    _reading(
        key="battery_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        value_fn=lambda data: data.battery_current_a,
    ),
    _reading(
        key="battery_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda data: data.battery_power_w,
    ),
    _reading(
        key="odometer",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.odometer_km,
        **DISTANCE_KILOMETERS,
    ),
    _reading(
        key="remaining_range",
        value_fn=lambda data: data.distance_left_km,
        entity_registry_enabled_default=False,
        **DISTANCE_KILOMETERS,
    ),
    # Computed from the model in ScooterSensor.native_value.
    _reading(
        key="reference_range",
        entity_category=EntityCategory.DIAGNOSTIC,
        **DISTANCE_KILOMETERS,
    ),
    # Riding: zero or unchanged while the scooter is parked.
    _reading(
        key="speed",
        sensor_group=RIDING,
        value_fn=lambda data: data.speed_kmh,
        **SPEED_KILOMETERS_PER_HOUR,
    ),
    _reading(
        key="average_speed",
        sensor_group=RIDING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.speed_average_kmh,
        **SPEED_KILOMETERS_PER_HOUR,
    ),
    _reading(
        key="trip_distance",
        sensor_group=RIDING,
        value_fn=lambda data: data.trip_distance_m,
        **DISTANCE_METERS,
    ),
    _sensor(
        key="work_mode",
        sensor_group=RIDING,
        device_class=SensorDeviceClass.ENUM,
        options=list(RIDE_MODE_STATES.values()),
        value_fn=lambda data: RIDE_MODE_STATES.get(data.work_mode),
    ),
    _reading(
        key="uptime",
        sensor_group=RIDING,
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda data: data.uptime_s,
    ),
    # Temperatures: room temperature while parked.
    _reading(
        key="battery_temperature_1",
        sensor_group=TEMPERATURES,
        value_fn=lambda data: data.battery_temperature_1_c,
        **TEMPERATURE_CELSIUS,
    ),
    _reading(
        key="battery_temperature_2",
        sensor_group=TEMPERATURES,
        value_fn=lambda data: data.battery_temperature_2_c,
        **TEMPERATURE_CELSIUS,
    ),
    _reading(
        key="frame_temperature",
        sensor_group=TEMPERATURES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.frame_temperature_c,
        **TEMPERATURE_CELSIUS,
    ),
    # Battery health: changes over months, not between two polls.
    _sensor(
        key="battery_health_percent",
        sensor_group=BATTERY_HEALTH,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: data.battery_health_percent,
    ),
    _sensor(
        key="battery_charge_cycles",
        sensor_group=BATTERY_HEALTH,
        value_fn=lambda data: data.battery_charge_cycles,
    ),
    _reading(
        key="cell_min_voltage",
        sensor_group=BATTERY_HEALTH,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.battery_cell_min_v,
        **VOLTAGE_VOLTS,
    ),
    _reading(
        key="cell_max_voltage",
        sensor_group=BATTERY_HEALTH,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.battery_cell_max_v,
        **VOLTAGE_VOLTS,
    ),
    _reading(
        key="cell_voltage_delta",
        sensor_group=BATTERY_HEALTH,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.battery_cell_delta_v,
        **VOLTAGE_VOLTS,
    ),
    *(_cell_voltage(index) for index in range(1, BATTERY_CELL_COUNT + 1)),
    # Device information: versions and dates that only change with new hardware.
    _diagnostic(
        key="firmware_version",
        sensor_group=DEVICE_INFO,
        value_fn=lambda data: data.firmware_version,
    ),
    _diagnostic(
        key="bms_version",
        sensor_group=DEVICE_INFO,
        value_fn=lambda data: data.bms_version,
    ),
    _diagnostic(
        key="ble_version",
        sensor_group=DEVICE_INFO,
        value_fn=lambda data: data.ble_version,
    ),
    _diagnostic(
        key="battery_manufacture_date",
        sensor_group=DEVICE_INFO,
        device_class=SensorDeviceClass.DATE,
        value_fn=_manufacture_date,
    ),
    _diagnostic(
        key="serial",
        sensor_group=DEVICE_INFO,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.serial,
    ),
    # Status codes: undecoded registers, mainly useful in bug reports.
    *(
        _status_code(key)
        for key in ("error_flags", "warning_flags", "status_flags", "bms_status_flags")
    ),
)


def _is_switched_on(description: ScooterSensorDescription, groups: frozenset[str]) -> bool:
    return description.sensor_group is None or description.sensor_group in groups


def _keep_serial_disabled_by_default(hass, address: str) -> None:
    """The serial number identifies its owner; it stays off until enabled by hand."""
    registry = entity_registry.async_get(hass)
    entity_id = registry.async_get_entity_id(Platform.SENSOR, DOMAIN, f"{address}_serial")
    existing = registry.async_get(entity_id) if entity_id is not None else None
    if existing is not None and existing.disabled_by is None:
        registry.async_update_entity(
            entity_id, disabled_by=entity_registry.RegistryEntryDisabler.INTEGRATION
        )


async def async_setup_entry(
    hass,
    entry,
    async_add_entities,
) -> None:
    """Set up the always-on sensors and the optional groups the user switched on."""
    coordinator: ScooterCoordinator = entry.runtime_data
    groups = selected_sensor_groups(entry.options)
    switched_off_keys = [
        description.key for description in SENSORS if not _is_switched_on(description, groups)
    ]
    async_remove_entities(
        hass, Platform.SENSOR, coordinator.address, (*OBSOLETE_SENSOR_KEYS, *switched_off_keys)
    )
    _keep_serial_disabled_by_default(hass, coordinator.address)
    async_add_entities(
        ScooterSensor(coordinator, description)
        for description in SENSORS
        if _is_switched_on(description, groups)
    )


class ScooterSensor(ScooterEntity, SensorEntity):
    """Representation of one scooter sensor."""

    entity_description: ScooterSensorDescription

    def __init__(
        self,
        coordinator: ScooterCoordinator,
        description: ScooterSensorDescription,
    ) -> None:
        """Initialize the scooter sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.address}_{description.key}"
        )

    @property
    def available(self) -> bool:
        """Show previously decoded telemetry even if the latest BLE poll fails.

        CoordinatorEntity.available normally mirrors last_update_success;
        that incorrectly hides the previous reading after ONE GATT timeout.
        """
        return self.coordinator.data is not None

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        """Mark restored or disconnected readings with their actual sample time."""
        last_read = self.coordinator._last_telemetry_at
        if last_read is None:
            return None
        return {
            "last_live_telemetry": last_read.isoformat(),
            "value_is_cached": self.coordinator.telemetry_stale,
        }

    @property
    def native_value(self):
        """Return the sensor value."""
        data = self.coordinator.data
        if data is None:
            return None
        if self.entity_description.key == "reference_range":
            return _reference_range_km(data.battery_percent, self.coordinator.display_model)
        return self.entity_description.value_fn(data)
