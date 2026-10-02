"""Experimental KERS selector; never controls a moving scooter."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory
from .coordinator import ScooterCoordinator
from .entity import ScooterEntity

KERS_LABELS = {0: "Schwach", 1: "Mittel", 2: "Stark"}
KERS_VALUES = {label: number for number, label in KERS_LABELS.items()}

# The 1S 0x75 mapping must stay separate from other scooter families.
RIDE_MODE_LABELS_1S = {0: "Drive", 1: "Eco", 2: "Sport"}
RIDE_MODE_VALUES_1S = {label: number for number, label in RIDE_MODE_LABELS_1S.items()}


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([ScooterKersSelect(entry.runtime_data), ScooterRideModeSelect(entry.runtime_data)])


class ScooterKersSelect(ScooterEntity, SelectEntity):
    _attr_translation_key = "kers_level"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:car-brake-retarder"
    _attr_options = list(KERS_VALUES)

    def __init__(self, coordinator: ScooterCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_kers_level_control"

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return self.coordinator.supports_action("kers_mode") and self.coordinator.setting_fresh("kers_mode") and data is not None and data.kers_mode in KERS_LABELS

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data
        return KERS_LABELS.get(data.kers_mode) if data is not None else None

    async def async_select_option(self, option: str) -> None:
        if option not in KERS_VALUES:
            raise ValueError("Ungültige KERS-Stufe")
        await self.coordinator.async_set_kers_mode(KERS_VALUES[option])


class ScooterRideModeSelect(ScooterEntity, SelectEntity):
    """Select a 1S riding mode after a fresh 0x75 reply in this BLE session."""

    _attr_translation_key = "ride_mode"
    _attr_icon = "mdi:scooter"
    _attr_options = list(RIDE_MODE_VALUES_1S)

    def __init__(self, coordinator: ScooterCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_ride_mode_control"

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return (self.coordinator.supports_action("work_mode")
                and self.coordinator.setting_fresh("work_mode")
                and data is not None and data.work_mode in RIDE_MODE_LABELS_1S)

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data
        return RIDE_MODE_LABELS_1S.get(data.work_mode) if data is not None else None

    async def async_select_option(self, option: str) -> None:
        if option not in RIDE_MODE_VALUES_1S:
            raise ValueError("Ungültiger Fahrmodus")
        await self.coordinator.async_set_ride_mode(RIDE_MODE_VALUES_1S[option])
