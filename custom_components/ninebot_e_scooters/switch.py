"""Cruise and tail-light controls; require authenticated stationary scooter."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory
from .coordinator import ScooterCoordinator
from .entity import ScooterEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([
        ScooterSettingSwitch(entry.runtime_data, "tail_light", "is_tail_light_on", "async_set_tail_light", "mdi:led-strip-variant"),
        ScooterSettingSwitch(entry.runtime_data, "cruise_control", "is_cruise_on", "async_set_cruise", "mdi:speedometer"),
    ])


class ScooterSettingSwitch(ScooterEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ScooterCoordinator, key: str, field: str, action: str, icon: str) -> None:
        super().__init__(coordinator)
        self._field = field
        self._action = action
        self._attr_translation_key = key
        self._attr_unique_id = (
            f"{coordinator.address}_tail_light" if key == "tail_light"
            else f"{coordinator.address}_control_{key}"
        )
        self._attr_icon = icon

    @property
    def available(self) -> bool:
        return self.coordinator.supports_action(self._field) and self.coordinator.setting_fresh(self._field) and self.is_on is not None

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return getattr(data, self._field) if data is not None else None

    async def async_turn_on(self, **kwargs) -> None:
        await getattr(self.coordinator, self._action)(True)

    async def async_turn_off(self, **kwargs) -> None:
        await getattr(self.coordinator, self._action)(False)
