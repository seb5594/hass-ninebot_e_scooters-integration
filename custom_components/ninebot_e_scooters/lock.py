"""Native Home Assistant lock entity, driven by validated BLE129 register state."""
from __future__ import annotations

from homeassistant.components.lock import LockEntity
from .coordinator import ScooterCoordinator
from .entity import ScooterEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([ScooterLock(entry.runtime_data)])


class ScooterLock(ScooterEntity, LockEntity):
    _attr_translation_key = "scooter_lock"
    _attr_icon = "mdi:scooter"

    def __init__(self, coordinator: ScooterCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_scooter_lock_control"

    @property
    def available(self) -> bool:
        return (
            self.coordinator.supports_action("is_lock_on")
            and self.coordinator.setting_fresh("is_lock_on")
            and self.coordinator.data is not None
            and self.coordinator.data.is_lock_on is not None
        )

    @property
    def is_locked(self) -> bool | None:
        data = self.coordinator.data
        return None if data is None else data.is_lock_on

    async def async_lock(self, **kwargs) -> None:
        await self.coordinator.async_set_lock(True)

    async def async_unlock(self, **kwargs) -> None:
        await self.coordinator.async_set_lock(False)
