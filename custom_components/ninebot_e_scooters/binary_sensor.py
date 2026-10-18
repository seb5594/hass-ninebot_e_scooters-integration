"""Binary sensor entities for the Ninebot E-Scooters integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import Platform

from .coordinator import ScooterCoordinator
from .entity import ScooterEntity, async_remove_entities

# Binary sensors of earlier releases; their registry entries are cleaned up on setup.
# "problem" only repeated the undecoded status codes, "telemetry_stale" is covered
# by the value_is_cached attribute every measurement carries.
OBSOLETE_BINARY_SENSOR_KEYS = ("cruise_control", "lock", "problem", "telemetry_stale")

CONNECTION = BinarySensorEntityDescription(
    key="connected",
    translation_key="connected",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
)


async def async_setup_entry(
    hass,
    entry,
    async_add_entities,
) -> None:
    """Set up the scooter's connection sensor."""
    coordinator: ScooterCoordinator = entry.runtime_data
    async_remove_entities(
        hass, Platform.BINARY_SENSOR, coordinator.address, OBSOLETE_BINARY_SENSOR_KEYS
    )
    async_add_entities([ScooterConnectionSensor(coordinator)])


class ScooterConnectionSensor(ScooterEntity, BinarySensorEntity):
    """Whether an authenticated Bluetooth session to the scooter is open."""

    entity_description = CONNECTION

    def __init__(self, coordinator: ScooterCoordinator) -> None:
        """Initialize the connection sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_{CONNECTION.key}"

    @property
    def available(self) -> bool:
        """A switched-off scooter is a valid answer, not a missing one."""
        return True

    @property
    def is_on(self) -> bool:
        """Return True while the session can exchange telemetry."""
        client = self.coordinator._client
        return bool(self.coordinator._session_ready and client is not None and client.is_connected)
