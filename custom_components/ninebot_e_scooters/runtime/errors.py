"""Errors shared by BLE session components."""

from homeassistant.exceptions import HomeAssistantError


class ScooterConnectionError(HomeAssistantError):
    """Raised when a scooter session cannot complete an operation."""
