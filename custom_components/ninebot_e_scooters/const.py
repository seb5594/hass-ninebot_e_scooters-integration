"""Constants for the Ninebot E-Scooters integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "ninebot_e_scooters"

# Short form for owners to report whether their scooter works.
REPORT_URL = (
    "https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues/new"
    "?template=scooter-report.yml"
)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.LOCK,
    Platform.SELECT,
]

CONF_POLL_INTERVAL = "poll_interval"
DEFAULT_POLL_INTERVAL = 10
MIN_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 120

# The reference scooter; entries created before the model option existed use it.
MODEL = "Mi Electric Scooter 1S"
MANUFACTURER = "Xiaomi"
CONF_MODEL = "model"
# Options form only: a session password another app has already set on the scooter.
CONF_PAIRING_PASSWORD = "pairing_password"
REFERENCE_RANGE_KM = {MODEL: 30.0}
# The 1S 0x75 mapping must stay separate from other scooter families.
RIDE_MODE_LABELS_1S = {0: "Drive", 1: "Eco", 2: "Sport"}
