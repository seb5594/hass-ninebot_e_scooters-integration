"""Conservative Bluetooth discovery without opening a GATT connection."""

from __future__ import annotations

from typing import Any

SCOOTER_NAME_PREFIXES = ("miscooter", "ninebot", "nbscooter", "segway")


def is_scooter_advertisement(service_info: Any) -> bool:
    """A shared Nordic UART UUID alone cannot identify a scooter."""
    name = getattr(service_info, "name", None)
    return isinstance(name, str) and name.casefold().startswith(SCOOTER_NAME_PREFIXES)


def needs_explicit_model(name: str) -> bool:
    """A Ninebot Bluetooth name does not select its controller register map."""
    return not name.casefold().startswith("miscooter")
