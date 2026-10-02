"""Binary sensor entities for the Ninebot E-Scooters integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import entity_registry

from .coordinator import ScooterCoordinator
from .entity import ScooterEntity


@dataclass(frozen=True, kw_only=True)
class ScooterBinaryDescription(BinarySensorEntityDescription):
    """Describe a scooter binary sensor."""

    value_fn: Callable[[object], bool | None] = lambda _data: None


BINARY_SENSORS = (
    ScooterBinaryDescription(
        key="connected",
        translation_key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda _data: None,
    ),
    ScooterBinaryDescription(
        key="telemetry_stale",
        translation_key="telemetry_stale",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda _data: None,
    ),
    ScooterBinaryDescription(
        key="problem",
        translation_key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: (
            None
            if data.error_flags is None and data.warning_flags is None
            else bool(data.error_flags or data.warning_flags)
        ),
    ),
)


async def async_setup_entry(
    hass,
    entry,
    async_add_entities,
) -> None:
    """Set up scooter binary sensors."""
    coordinator: ScooterCoordinator = entry.runtime_data
    registry = entity_registry.async_get(hass)
    obsolete = registry.async_get_entity_id(
        "binary_sensor", "ninebot_e_scooters", f"{coordinator.address}_cruise_control"
    )
    if obsolete is not None:
        registry.async_remove(obsolete)
    for obsolete_key in ("lock",):
        old_entity = registry.async_get_entity_id(
            "binary_sensor", "ninebot_e_scooters", f"{coordinator.address}_{obsolete_key}"
        )
        if old_entity is not None:
            registry.async_remove(old_entity)
    async_add_entities(
        ScooterBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
    )


class ScooterBinarySensor(ScooterEntity, BinarySensorEntity):
    """Representation of a scooter binary sensor."""

    entity_description: ScooterBinaryDescription

    def __init__(
        self,
        coordinator: ScooterCoordinator,
        description: ScooterBinaryDescription,
    ) -> None:
        """Initialize the scooter binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.address}_{description.key}"
        )

    @property
    def available(self) -> bool:
        """Keep the freshness indicator visible even while BLE is offline."""
        if self.entity_description.key in ("telemetry_stale", "connected"):
            return True
        return self.coordinator.data is not None

    @property
    def is_on(self) -> bool | None:
        """Return the binary sensor state."""
        if self.entity_description.key == "telemetry_stale":
            return self.coordinator.telemetry_stale
        if self.entity_description.key == "connected":
            client = self.coordinator._client
            return bool(self.coordinator._session_ready and client is not None and client.is_connected)
        if not self.coordinator.data:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
