"""Shared entity helpers for the Ninebot E-Scooters integration."""

from __future__ import annotations

from collections.abc import Iterable

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .compat import DeviceInfo, EntityNameFallback
from .const import DOMAIN, MANUFACTURER
from .coordinator import ScooterCoordinator


def async_remove_entities(
    hass: HomeAssistant, platform: str, address: str, keys: Iterable[str]
) -> None:
    """Drop registry entries this scooter no longer provides.

    Covers entities removed in an update as well as optional sensors the user
    switched off, so neither lingers as "no longer provided" on the device page.
    """
    registry = entity_registry.async_get(hass)
    for key in keys:
        entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{address}_{key}")
        if entity_id is not None:
            registry.async_remove(entity_id)


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
