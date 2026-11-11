"""Conservative Bluetooth discovery without opening a GATT connection."""

from __future__ import annotations

from typing import Any

from ..protocols.constants import AUTH_SERVICE_UUID
from ..models.serials import NINEBOT_SERIAL

SCOOTER_NAME_PREFIXES = ("miscooter", "ninebot", "nbscooter", "segway")

# Company identifiers the Ninebot BLE module puts into its manufacturer data,
# whatever name the owner gave the scooter: 0x424E ("NB") on older generations,
# 0x434E on newer ones. Keep in sync with the bluetooth matchers in manifest.json.
NINEBOT_MANUFACTURER_IDS = (0x424E, 0x434E)

# Xiaomi scooters advertise a MiBeacon frame as service data of the Xiaomi UUID and
# nothing else, so a renamed one has no name or manufacturer data to recognize it by.
# The manifest can only match the UUID; the product ID inside the frame tells scooters
# apart from the many other Xiaomi devices. Add the IDs of further models here.
# 0x061C: Mi Electric Scooter 1S.
XIAOMI_SCOOTER_PRODUCT_IDS = (0x061C,)
MIBEACON_PRODUCT_ID_OFFSET = 2


def is_scooter_advertisement(service_info: Any) -> bool:
    """Recognize a scooter by its BLE module first and by its name second.

    A renamed Ninebot still carries the module's manufacturer data and a renamed
    Xiaomi its MiBeacon product ID. Newer Ninebot generations advertise their serial
    number as name instead. A shared Nordic UART UUID alone cannot identify a scooter.
    """
    return (
        _has_ninebot_manufacturer_data(service_info)
        or _has_xiaomi_scooter_beacon(service_info)
        or _has_scooter_name(getattr(service_info, "name", None))
    )


def _has_ninebot_manufacturer_data(service_info: Any) -> bool:
    manufacturer_data = getattr(service_info, "manufacturer_data", None) or {}
    return any(company in manufacturer_data for company in NINEBOT_MANUFACTURER_IDS)


def _has_xiaomi_scooter_beacon(service_info: Any) -> bool:
    service_data = getattr(service_info, "service_data", None) or {}
    beacon = service_data.get(AUTH_SERVICE_UUID)
    product_id_end = MIBEACON_PRODUCT_ID_OFFSET + 2
    if not beacon or len(beacon) < product_id_end:
        return False
    product_id = int.from_bytes(beacon[MIBEACON_PRODUCT_ID_OFFSET:product_id_end], "little")
    return product_id in XIAOMI_SCOOTER_PRODUCT_IDS


def _has_scooter_name(name: object) -> bool:
    if not isinstance(name, str):
        return False
    return name.casefold().startswith(SCOOTER_NAME_PREFIXES) or bool(NINEBOT_SERIAL.fullmatch(name))


def needs_explicit_model(name: str) -> bool:
    """A Ninebot Bluetooth name does not select its controller register map."""
    return not name.casefold().startswith("miscooter")
