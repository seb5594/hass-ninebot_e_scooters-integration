"""Sensor entities for the Ninebot E-Scooters integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.helpers.entity import EntityCategory

from .coordinator import ScooterCoordinator
from .const import REFERENCE_RANGE_KM
from .entity import ScooterEntity

KILOMETERS = "km"
METERS = "m"


@dataclass(frozen=True, kw_only=True)
class ScooterSensorDescription(SensorEntityDescription):
    """Describe a scooter sensor."""

    value_fn: Callable[[object], object] = lambda _data: None


CONNECTION_SENSORS: tuple[ScooterSensorDescription, ...] = (
    ScooterSensorDescription(
        key="detected_model",
        translation_key="detected_model",
        value_fn=lambda _data: None,
    ),
    ScooterSensorDescription(
        key="last_telemetry",
        translation_key="last_telemetry",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda _data: None,
    ),
)

SENSORS: tuple[ScooterSensorDescription, ...] = (
    ScooterSensorDescription(
        key="battery_percent",
        translation_key="battery_percent",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class="measurement",
        value_fn=lambda data: data.battery_percent,
    ),
    ScooterSensorDescription(
        key="speed",
        translation_key="speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement="km/h",
        state_class="measurement",
        value_fn=lambda data: data.speed_kmh,
    ),
    ScooterSensorDescription(
        key="average_speed",
        translation_key="average_speed",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement="km/h",
        state_class="measurement",
        value_fn=lambda data: data.speed_average_kmh,
    ),
    ScooterSensorDescription(
        key="odometer",
        translation_key="odometer",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=KILOMETERS,
        state_class="total_increasing",
        value_fn=lambda data: data.odometer_km,
    ),
    ScooterSensorDescription(
        key="trip_distance",
        translation_key="trip_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=METERS,
        state_class="measurement",
        value_fn=lambda data: data.trip_distance_m,
    ),
    ScooterSensorDescription(
        key="remaining_range",
        translation_key="remaining_range",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=KILOMETERS,
        state_class="measurement",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.distance_left_km,
    ),
    ScooterSensorDescription(
        key="reference_range",
        translation_key="reference_range",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=KILOMETERS,
        state_class="measurement",
        value_fn=lambda data: data.battery_percent,
    ),
    ScooterSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class="measurement",
        value_fn=lambda data: data.battery_voltage_v,
    ),
    ScooterSensorDescription(
        key="battery_current",
        translation_key="battery_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class="measurement",
        value_fn=lambda data: data.battery_current_a,
    ),
    ScooterSensorDescription(
        key="battery_power",
        translation_key="battery_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class="measurement",
        value_fn=lambda data: data.battery_power_w,
    ),
    ScooterSensorDescription(
        key="battery_capacity",
        translation_key="battery_capacity",
        native_unit_of_measurement="Ah",
        state_class="measurement",
        value_fn=lambda data: data.battery_capacity_ah,
    ),
    ScooterSensorDescription(
        key="battery_temperature_1",
        translation_key="battery_temperature_1",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class="measurement",
        value_fn=lambda data: data.battery_temperature_1_c,
    ),
    ScooterSensorDescription(
        key="battery_temperature_2",
        translation_key="battery_temperature_2",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class="measurement",
        value_fn=lambda data: data.battery_temperature_2_c,
    ),
    ScooterSensorDescription(
        key="frame_temperature",
        translation_key="frame_temperature",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class="measurement",
        value_fn=lambda data: data.frame_temperature_c,
    ),
    ScooterSensorDescription(
        key="uptime",
        translation_key="uptime",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class="measurement",
        value_fn=lambda data: data.uptime_s,
    ),
    ScooterSensorDescription(
        key="cell_min_voltage",
        translation_key="cell_min_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class="measurement",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.battery_cell_min_v,
    ),
    ScooterSensorDescription(
        key="cell_max_voltage",
        translation_key="cell_max_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class="measurement",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.battery_cell_max_v,
    ),
    ScooterSensorDescription(
        key="cell_voltage_delta",
        translation_key="cell_voltage_delta",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class="measurement",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.battery_cell_delta_v,
    ),
    ScooterSensorDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.firmware_version,
    ),
    ScooterSensorDescription(
        key="bms_version",
        translation_key="bms_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.bms_version,
    ),
    ScooterSensorDescription(
        key="serial",
        translation_key="serial",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.serial,
    ),
    ScooterSensorDescription(
        key="battery_manufacture_date",
        translation_key="battery_manufacture_date",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda data: (
            date.fromisoformat(data.battery_manufacture_date)
            if data.battery_manufacture_date else None
        ),
    ),
    ScooterSensorDescription(
        key="ble_version", translation_key="ble_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.ble_version,
    ),
    ScooterSensorDescription(
        key="bms_status_flags", translation_key="bms_status_flags",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: f"0x{data.bms_status_flags:04X}" if data.bms_status_flags is not None else None,
    ),
    ScooterSensorDescription(
        key="battery_charge_cycles", translation_key="battery_charge_cycles",
        value_fn=lambda data: data.battery_charge_cycles,
    ),
    ScooterSensorDescription(
        key="battery_health_percent", translation_key="battery_health_percent",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda data: data.battery_health_percent,
    ),
    ScooterSensorDescription(
        key="work_mode",
        translation_key="work_mode",
        value_fn=lambda data: data.work_mode,
    ),
    ScooterSensorDescription(
        key="error_flags",
        translation_key="error_flags",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: f"0x{data.error_flags:04X}" if data.error_flags is not None else None,
    ),
    ScooterSensorDescription(
        key="warning_flags",
        translation_key="warning_flags",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: f"0x{data.warning_flags:04X}" if data.warning_flags is not None else None,
    ),
    ScooterSensorDescription(
        key="status_flags",
        translation_key="status_flags",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: f"0x{data.status_flags:04X}" if data.status_flags is not None else None,
    ),
)

for index in range(1, 11):
    SENSORS += (
        ScooterSensorDescription(
            key=f"cell_{index}",
            translation_key=f"cell_{index}",
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            state_class="measurement",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=lambda data, index=index: (
                data.battery_cell_voltages[index - 1]
                if len(data.battery_cell_voltages) >= index
                else None
            ),
        ),
    )


async def async_setup_entry(
    hass,
    entry,
    async_add_entities,
) -> None:
    """Set up scooter sensors."""
    coordinator: ScooterCoordinator = entry.runtime_data
    from homeassistant.helpers import entity_registry

    registry = entity_registry.async_get(hass)
    old_serial = registry.async_get_entity_id(
        "sensor", "ninebot_e_scooters", f"{coordinator.address}_serial"
    )
    if old_serial is not None:
        existing = registry.async_get(old_serial)
        if existing is not None and existing.disabled_by is None:
            registry.async_update_entity(
                old_serial, disabled_by=entity_registry.RegistryEntryDisabler.INTEGRATION
            )

    for obsolete_key in ("connection_status", "kers_mode"):
        old_entity = registry.async_get_entity_id(
            "sensor", "ninebot_e_scooters", f"{coordinator.address}_{obsolete_key}"
        )
        if old_entity is not None:
            registry.async_remove(old_entity)

    descriptions = (*SENSORS, *CONNECTION_SENSORS)
    async_add_entities(
        ScooterSensor(coordinator, description)
        for description in descriptions
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
        Live status and last-received diagnostics must remain available.
        """
        if self.entity_description.key in ("last_telemetry", "detected_model"):
            return True
        return self.coordinator.data is not None

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        """Mark restored or disconnected readings with their actual sample time."""
        if self.entity_description.key in ("detected_model", "last_telemetry"):
            return None
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
        if self.entity_description.key == "last_telemetry":
            return self.coordinator._last_telemetry_at
        if self.entity_description.key == "detected_model":
            return self.coordinator.detected_model
        if self.entity_description.key == "reference_range":
            data = self.coordinator.data
            maximum = REFERENCE_RANGE_KM.get(self.coordinator.display_model)
            if data is None or maximum is None or data.battery_percent is None:
                return None
            return round(maximum * max(0, min(100, data.battery_percent)) / 100, 1)
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
