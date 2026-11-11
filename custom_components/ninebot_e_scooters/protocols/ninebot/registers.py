"""Read-only Ninebot control tables, ordered by target and register index.

Two generations share the word-addressed register file but not its layout:

Classic scooters (ES, E, F, Max G30, Max G2) keep ride data on the ESC 0x20
and battery data on the BMS 0x22. Every entry is listed with the same index
and width in at least one of
  ownbee/ninebot-ble, register.py at commit 1850351f (tested on an F series)
  Ninebot ES protocol PDF linked from the ScooterHacking wiki (nbdocs)
  https://nootnooot.codeberg.page/segway-ninebot-ble/devices/ (Max G2 commands)
The trip distance is left out: the F series keeps it at 0xB9, the Max G2 at 0xB7.

The generation with a vehicle control unit (F3, Max G3) answers on VCU 0x16
and, where the pack has its own board, on battery 0x07. Index and width come
from the vendor command table of the F3; scales are the ones an F3 owner
compared with the vendor app:
  https://nootnooot.codeberg.page/segway-ninebot-ble/devices/ekickscooter-f3/
  https://github.com/BobMcGlobus/ha-ninebot/issues/9

These definitions must never be passed to the Xiaomi 1S block decoder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..data import ScooterData
from .packet import (
    CMD_READ,
    CMD_READ_ACK,
    DeviceId,
    NinebotPacket,
)

BYTES_PER_WORD = 2
SERIAL_LENGTH = 14
BATTERY_TEMPERATURE_OFFSET_C = 20
MISSING_TEMPERATURE_SENSOR = 0xFF
LOCKED_STATUS_BIT = 0x0002
# An erased or never written version word.
BLANK_VERSION_WORDS = (0x0000, 0xFFFF)
PERCENT_FIELDS = frozenset({"battery_percent", "battery_health_percent"})

Encoding = Literal[
    "unsigned", "signed", "version", "serial", "status",
    "temperatures",          # one byte per sensor, stored 20 degrees too high
    "celsius_bytes",         # one byte per sensor in plain degrees, 0xFF without sensor
]


@dataclass(frozen=True, slots=True)
class RegisterSpec:
    """Describe a block assembled from individual two-byte register words."""

    target: DeviceId
    index: int
    fields: tuple[str, ...]
    words: int = 1
    encoding: Encoding = "unsigned"
    scale: float = 1.0
    static: bool = False


@dataclass(frozen=True, slots=True)
class RegisterMap:
    """The registers one scooter generation is polled with."""

    protocol_label: str
    # Read on every poll; the first one also proves a resumed session.
    core: tuple[RegisterSpec, ...]
    # Read one per poll, in turn; a scooter may leave any of them unanswered.
    optional: tuple[RegisterSpec, ...]
    # The vendor app of the VCU generation fetches a block with one request.
    # Classic scooters are only documented with one word per request.
    reads_whole_blocks: bool = False

    @property
    def session_probe(self) -> RegisterSpec:
        """The register whose reply shows that the scooter serves this session."""
        return self.core[0]


# Do not read controller 0x17: it contains the Bluetooth password.
CLASSIC_REGISTERS = RegisterMap(
    protocol_label="Ninebot chained crypto / word registers (read-only)",
    core=(
        RegisterSpec(DeviceId.BMS, 0x32, ("battery_percent",)),
        RegisterSpec(DeviceId.ESC, 0x1D, ("status_flags", "is_lock_on"), encoding="status"),
        RegisterSpec(DeviceId.BMS, 0x33, ("battery_current_a",), encoding="signed", scale=0.01),
        RegisterSpec(DeviceId.BMS, 0x34, ("battery_voltage_v",), scale=0.01),
        RegisterSpec(DeviceId.BMS, 0x35, ("battery_temperature_1_c", "battery_temperature_2_c"),
                     encoding="temperatures"),
    ),
    optional=(
        RegisterSpec(DeviceId.ESC, 0x10, ("serial",), 7, "serial", static=True),
        RegisterSpec(DeviceId.ESC, 0x1A, ("firmware_version",), encoding="version", static=True),
        RegisterSpec(DeviceId.ESC, 0x1B, ("error_flags",)),
        RegisterSpec(DeviceId.ESC, 0x1C, ("warning_flags",)),
        RegisterSpec(DeviceId.ESC, 0x25, ("distance_left_km",), scale=0.01),
        RegisterSpec(DeviceId.ESC, 0x29, ("odometer_km",), 2, scale=0.001),
        RegisterSpec(DeviceId.ESC, 0x3E, ("frame_temperature_c",), scale=0.1),
        RegisterSpec(DeviceId.ESC, 0x65, ("speed_average_kmh",), scale=0.1),
        RegisterSpec(DeviceId.ESC, 0x68, ("ble_version",), encoding="version", static=True),
        # 0 drive, 1 eco, 2 sport: the numbering the Xiaomi 1S uses as well.
        RegisterSpec(DeviceId.ESC, 0x75, ("work_mode",)),
        RegisterSpec(DeviceId.BMS, 0x17, ("bms_version",), encoding="version", static=True),
        RegisterSpec(DeviceId.BMS, 0x1B, ("battery_charge_cycles",)),
        RegisterSpec(DeviceId.BMS, 0x31, ("battery_capacity_ah",), scale=0.001),
        RegisterSpec(DeviceId.BMS, 0x3B, ("battery_health_percent",)),
    ),
)

# The ride mode (0x70 counts eco, drive, sport) and the speed are left out:
# the two sources disagree on their index.
VCU_REGISTERS = RegisterMap(
    protocol_label="Ninebot chained crypto / VCU registers (read-only)",
    core=(
        RegisterSpec(DeviceId.VCU, 0x55, ("battery_percent",)),
        RegisterSpec(DeviceId.VCU, 0x5F, ("distance_left_km",), scale=0.01),
        RegisterSpec(DeviceId.VCU, 0x62, ("odometer_km",), 2, scale=0.1),
    ),
    optional=(
        # Not every model has a battery board at this address: a Max G3 stays silent.
        RegisterSpec(DeviceId.VCU_BATTERY, 0x59, ("battery_charge_cycles",)),
        RegisterSpec(DeviceId.VCU_BATTERY, 0x5B, ("battery_capacity_ah",), scale=0.01),
        RegisterSpec(DeviceId.VCU_BATTERY, 0x8C, ("battery_voltage_v",), scale=0.01),
        # This pack counts charging as positive; every other family counts it negative.
        RegisterSpec(DeviceId.VCU_BATTERY, 0x8D, ("battery_current_a",), encoding="signed", scale=-0.01),
        RegisterSpec(DeviceId.VCU_BATTERY, 0x96, ("battery_temperature_1_c", "battery_temperature_2_c"),
                     encoding="celsius_bytes"),
        RegisterSpec(DeviceId.VCU, 0x10, ("serial",), 7, "serial", static=True),
        RegisterSpec(DeviceId.VCU, 0x58, ("error_flags",)),
        RegisterSpec(DeviceId.VCU, 0x59, ("warning_flags",)),
        RegisterSpec(DeviceId.VCU, 0x6B, ("frame_temperature_c",), encoding="signed", scale=0.1),
    ),
    reads_whole_blocks=True,
)

REGISTER_MAPS = (CLASSIC_REGISTERS, VCU_REGISTERS)
REGISTER_BY_ADDRESS = {
    (spec.target, spec.index): spec
    for register_map in REGISTER_MAPS
    for spec in (*register_map.core, *register_map.optional)
}


def apply_packet(data: ScooterData, packet: NinebotPacket) -> bool:
    """Decode only a complete read reply from the descriptor's own target."""
    spec = REGISTER_BY_ADDRESS.get((packet.source, packet.index))
    if (spec is None or packet.command not in (CMD_READ, CMD_READ_ACK)
            or packet.target not in (DeviceId.PHONE, DeviceId.PC)
            or len(packet.data) != spec.words * BYTES_PER_WORD):
        return False
    values = _decode(spec, packet.data)
    if values is None:
        return False
    for field, value in zip(spec.fields, values, strict=True):
        setattr(data, field, value)
    return True


def _decode(spec: RegisterSpec, raw: bytes) -> tuple[Any, ...] | None:
    """Return one value per field of the register, or None for an implausible reply."""
    if spec.encoding == "serial":
        serial = _decode_serial(raw)
        return None if serial is None else (serial,)
    if spec.encoding == "temperatures":
        return tuple(float(byte - BATTERY_TEMPERATURE_OFFSET_C) for byte in raw)
    if spec.encoding == "celsius_bytes":
        return tuple(None if byte == MISSING_TEMPERATURE_SENSOR else float(byte) for byte in raw)
    number = int.from_bytes(raw, "little", signed=spec.encoding == "signed")
    if spec.encoding == "version":
        return None if number in BLANK_VERSION_WORDS else (_format_version(number),)
    if spec.encoding == "status":
        return number, bool(number & LOCKED_STATUS_BIT)
    if spec.fields[0] in PERCENT_FIELDS and number > 100:
        return None
    return (number if spec.scale == 1.0 else number * spec.scale,)


def _decode_serial(raw: bytes) -> str | None:
    try:
        serial = raw.rstrip(b"\x00").decode("ascii")
    except UnicodeDecodeError:
        return None
    return serial if len(serial) == SERIAL_LENGTH and serial.isalnum() else None


def _format_version(word: int) -> str:
    """0x0128 is firmware 1.2.8: one byte major, then a nibble each for minor and patch."""
    return f"V{word >> 8}.{(word >> 4) & 0xF}.{word & 0xF}"
