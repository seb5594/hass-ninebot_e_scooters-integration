"""Read-only Ninebot control tables, ordered by target and register index.

The word access pattern follows ownbee/ninebot-ble at commit 1850351f.
These definitions must never be passed to the Xiaomi 1S block decoder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..data import ScooterData
from .packet import (
    CMD_READ,
    CMD_READ_ACK,
    DeviceId,
    NinebotPacket,
)


@dataclass(frozen=True, slots=True)
class RegisterSpec:
    """Describe a block assembled from individual two-byte register words."""

    target: DeviceId
    index: int
    fields: tuple[str, ...]
    words: int = 1
    encoding: Literal["unsigned", "signed", "version", "serial", "temperatures", "status"] = "unsigned"
    scale: float = 1.0
    static: bool = False


# Do not read controller 0x17: it contains the Bluetooth password.
REGISTERS = (
    RegisterSpec(DeviceId.ESC, 0x10, ("serial",), 7, "serial", static=True),
    RegisterSpec(DeviceId.ESC, 0x1A, ("firmware_version",), encoding="version", static=True),
    RegisterSpec(DeviceId.ESC, 0x1B, ("error_flags",)),
    RegisterSpec(DeviceId.ESC, 0x1C, ("warning_flags",)),
    RegisterSpec(DeviceId.ESC, 0x1D, ("status_flags", "is_lock_on"), encoding="status"),
    RegisterSpec(DeviceId.ESC, 0x25, ("distance_left_km",), scale=0.01),
    RegisterSpec(DeviceId.ESC, 0x29, ("odometer_km",), 2, scale=0.001),
    RegisterSpec(DeviceId.ESC, 0x3E, ("frame_temperature_c",), scale=0.1),
    RegisterSpec(DeviceId.ESC, 0x65, ("speed_average_kmh",), scale=0.1),
    RegisterSpec(DeviceId.ESC, 0x68, ("ble_version",), encoding="version", static=True),
    RegisterSpec(DeviceId.BMS, 0x17, ("bms_version",), encoding="version", static=True),
    RegisterSpec(DeviceId.BMS, 0x31, ("battery_capacity_ah",), scale=0.001),
    RegisterSpec(DeviceId.BMS, 0x32, ("battery_percent",)),
    RegisterSpec(DeviceId.BMS, 0x33, ("battery_current_a",), encoding="signed", scale=0.01),
    RegisterSpec(DeviceId.BMS, 0x34, ("battery_voltage_v",), scale=0.01),
    RegisterSpec(DeviceId.BMS, 0x35, ("battery_temperature_1_c", "battery_temperature_2_c"), encoding="temperatures"),
    RegisterSpec(DeviceId.BMS, 0x3B, ("battery_health_percent",)),
)

REGISTER_BY_ADDRESS = {(spec.target, spec.index): spec for spec in REGISTERS}
CORE_REGISTERS = tuple(REGISTER_BY_ADDRESS[address] for address in (
    (DeviceId.ESC, 0x1D),
    (DeviceId.BMS, 0x32),
    (DeviceId.BMS, 0x33),
    (DeviceId.BMS, 0x34),
    (DeviceId.BMS, 0x35),
))
OPTIONAL_REGISTERS = tuple(spec for spec in REGISTERS if spec not in CORE_REGISTERS)


def apply_packet(data: ScooterData, packet: NinebotPacket) -> bool:
    """Decode only a complete read reply from the descriptor's own target."""
    spec = REGISTER_BY_ADDRESS.get((packet.source, packet.index))
    if (spec is None or packet.command not in (CMD_READ, CMD_READ_ACK)
            or packet.target not in (DeviceId.PHONE, DeviceId.PC)
            or len(packet.data) != spec.words * 2):
        return False
    raw = packet.data
    if spec.encoding == "serial":
        try:
            value = raw.rstrip(b"\x00").decode("ascii")
        except UnicodeDecodeError:
            return False
        if len(value) != 14 or not value.isalnum():
            return False
    elif spec.encoding == "temperatures":
        for field, value in zip(spec.fields, (raw[0] - 20, raw[1] - 20), strict=True):
            setattr(data, field, float(value))
        return True
    else:
        number = int.from_bytes(raw, "little", signed=spec.encoding == "signed")
        if spec.encoding == "version":
            if number in (0, 0xFFFF):
                return False
            value = f"V{number >> 8}.{(number >> 4) & 15}.{number & 15}"
        elif spec.encoding == "status":
            data.status_flags = number
            data.is_lock_on = bool(number & 2)
            return True
        else:
            if spec.fields[0] in ("battery_percent", "battery_health_percent") and number > 100:
                return False
            value = number if spec.scale == 1.0 else number * spec.scale
    setattr(data, spec.fields[0], value)
    return True
