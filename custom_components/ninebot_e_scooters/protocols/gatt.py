"""GATT serial services that carry the scooter request/reply protocol.

Xiaomi scooters and older Ninebot generations reuse the Nordic UART service.
Newer Segway-Ninebot dashboards expose the same byte stream under their own
service, whose notifications arrive on characteristic 0004 rather than 0003.
Source: https://nootnooot.codeberg.page/segway-ninebot-ble/transport/
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class UartService:
    """One serial-over-GATT service: the host writes requests and subscribes to replies."""

    name: str
    service_uuid: str
    write_uuid: str
    notify_uuid: str


NORDIC_UART = UartService(
    "nordic_uart",
    "6e400001-b5a3-f393-e0a9-e50e24dcca9e",
    "6e400002-b5a3-f393-e0a9-e50e24dcca9e",
    "6e400003-b5a3-f393-e0a9-e50e24dcca9e",
)
NINEBOT_UART = UartService(
    "ninebot_uart",
    "6e400001-0000-0000-006e-696e65626f74",
    "6e400002-0000-0000-006e-696e65626f74",
    "6e400004-0000-0000-006e-696e65626f74",
)

# Tried in this order, so every scooter that worked before resolves as before.
UART_SERVICES = (NORDIC_UART, NINEBOT_UART)


def describe_characteristics(services: Any) -> tuple[str, ...]:
    """List every characteristic as 'service/characteristic [properties]' for diagnostics."""
    return tuple(
        f"{service.uuid}/{characteristic.uuid} [{','.join(characteristic.properties)}]".lower()
        for service in services
        for characteristic in getattr(service, "characteristics", ())
    )


def find_uart_characteristics(
    services: Any, preferred: UartService | None = None,
) -> tuple[Any | None, Any | None]:
    """Return the write and notify characteristics of the first complete UART.

    `services` is the service collection of a connected Bleak client. Some
    scooters offer both services and answer on one only, so the service a
    family is documented with is tried first. Both entries are None when
    the device offers no known serial service.
    """
    candidates = UART_SERVICES if preferred is None else (
        preferred, *(uart for uart in UART_SERVICES if uart is not preferred))
    for uart in candidates:
        write_characteristic = services.get_characteristic(uart.write_uuid)
        notify_characteristic = services.get_characteristic(uart.notify_uuid)
        if write_characteristic is not None and notify_characteristic is not None:
            return write_characteristic, notify_characteristic
    return None, None
