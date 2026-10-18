"""Conservative Bluetooth discovery without opening a GATT connection."""

from __future__ import annotations

from typing import Any

from .protocols.research import NINEBOT_SERIAL

SCOOTER_NAME_PREFIXES = ("miscooter", "ninebot", "nbscooter", "segway")

# Company identifiers the Ninebot BLE module puts into its manufacturer data,
# whatever name the owner gave the scooter: 0x424E ("NB") on older generations,
# 0x434E on newer ones. Keep in sync with the bluetooth matchers in manifest.json.
NINEBOT_MANUFACTURER_IDS = (0x424E, 0x434E)


def is_scooter_advertisement(service_info: Any) -> bool:
    """Recognize a scooter by its BLE module first and by its name second.

    A renamed scooter still carries the module's manufacturer data. Newer Ninebot
    generations advertise their serial number as name instead. A shared Nordic
    UART UUID alone cannot identify a scooter.
    """
    return _has_ninebot_manufacturer_data(service_info) or _has_scooter_name(
        getattr(service_info, "name", None)
    )


def _has_ninebot_manufacturer_data(service_info: Any) -> bool:
    manufacturer_data = getattr(service_info, "manufacturer_data", None) or {}
    return any(company in manufacturer_data for company in NINEBOT_MANUFACTURER_IDS)


def _has_scooter_name(name: object) -> bool:
    if not isinstance(name, str):
        return False
    return name.casefold().startswith(SCOOTER_NAME_PREFIXES) or bool(NINEBOT_SERIAL.fullmatch(name))


def needs_explicit_model(name: str) -> bool:
    """A Ninebot Bluetooth name does not select its controller register map."""
    return not name.casefold().startswith("miscooter")
