"""Shared entity helpers for the Ninebot E-Scooters integration."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .compat import DeviceInfo, EntityNameFallback
from .const import DOMAIN, MANUFACTURER
from .coordinator import ScooterCoordinator


class ScooterEntity(EntityNameFallback, CoordinatorEntity[ScooterCoordinator]):
    """Base class for scooter entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ScooterCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            name=coordinator.device_name,
            manufacturer=coordinator._model_identification.brand or MANUFACTURER,
            model=coordinator.display_model,
            connections={("bluetooth", coordinator.address)},
            sw_version=(
                coordinator.data.firmware_version
                if coordinator.data
                else None
            ),
        )
