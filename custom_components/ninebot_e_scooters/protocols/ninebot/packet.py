"""5A A5 packet layout, device roles and Xiaomi BLE129 register identifiers.

The legacy Ninebot ES serial frame is documented at:
https://wiki.scooterhacking.org/doku.php?id=nbdocs
BLE129 wraps the logical 5A A5 packet in a six-byte crypto trailer. ESC
registers in the PDF must not be assumed to have the same 1S/SHFW layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

HEADER = b"\x5A\xA5"
LOGICAL_HEADER_LENGTH = 7
ENCRYPTED_TRAILER_LENGTH = 6
ENCRYPTED_FRAME_OVERHEAD = LOGICAL_HEADER_LENGTH + ENCRYPTED_TRAILER_LENGTH
BLE129_APP_KEY_LENGTH = 16
BLE129_SERIAL_LENGTH = 14
BLE129_INIT_REPLY_LENGTH = BLE129_APP_KEY_LENGTH + BLE129_SERIAL_LENGTH


class FrameOffset(IntEnum):
    """Byte offsets inside a decrypted logical 5A A5 packet."""

    LENGTH = 2
    SOURCE = 3
    TARGET = 4
    COMMAND = 5
    INDEX = 6
    DATA = 7


class DeviceId(IntEnum):
    """Ninebot serial-bus addresses; 0x23 has other legacy Xiaomi meanings."""

    BROADCAST = 0x00
    ESC = 0x20
    DASHBOARD = 0x21
    BMS = 0x22
    EXTERNAL_BMS = 0x23
    PC = 0x3D
    PHONE = 0x3E


class LegacyM365Reply(IntEnum):
    """55 AA direction aliases accepted by the existing Xiaomi reply matcher."""

    ESC = 0x23
    BMS = 0x25


class PacketOpcode(IntEnum):
    """Control-table and BLE129 handshake commands."""

    READ = 0x01
    WRITE = 0x02
    WRITE_NO_REPLY = 0x03
    READ_ACK = 0x04
    WRITE_ACK = 0x05
    INIT = 0x5B
    PING = 0x5C
    PAIR = 0x5D


class PairingStatus(IntEnum):
    """The 0x5C/0x5D reply argument in the current BLE129 exchange."""

    PENDING = 0x00
    CONFIRMED = 0x01


class RegisterReadSize(IntEnum):
    """Observed read lengths for this 1S, in bytes (not register words)."""

    WORD = 0x02
    SUPPLEMENTARY = 0x06
    BMS_MANUFACTURE_DATE = 0x06
    TRIP_AND_BATTERY = 0x0A
    GENERAL_INFO = 0x16
    BMS_CELLS = 0x1B
    FAST_TELEMETRY = 0x20


class NinebotEsRegister(IntEnum):
    """Selected ESC indices in the Ninebot ES PDF; not a universal map."""

    SERIAL = 0x10
    ERROR = 0x1B
    ALARM = 0x1C
    STATUS_BITS = 0x1D
    CURRENT_MODE = 0x1F
    SET_MODE = 0x75
    CRUISE = 0x7C
    FUNCTION_BITS = 0x7D
    QUICK_ERROR = 0xB0
    QUICK_ALARM = 0xB1
    QUICK_STATUS = 0xB2


class Xiaomi1sEscRegister(IntEnum):
    """Indices actually queried on this 1S/SHFW; variants need validation."""

    GENERAL_INFO = 0x10
    ERROR = 0x1B
    ALARM = 0x1C
    STATUS_BITS = 0x1D
    DISTANCE_LEFT = 0x25
    TRIP_INFO = 0x3A
    BLE_VERSION = 0x68
    LOCK = 0x70
    UNLOCK = 0x71
    WORK_MODE = 0x75
    SUPPLEMENTARY_KERS = 0x7B
    CRUISE = 0x7C
    TAIL_LIGHT = 0x7D
    FAST_TELEMETRY = 0xB0
    QUICK_WARNING = 0xB1
    LOCK_STATUS = 0xB2
    QUICK_SPEED = 0xB5
    TRIP_DISTANCE = 0xB9


class Xiaomi1sBmsRegister(IntEnum):
    """Battery indices used in existing Xiaomi 1S reads and decode paths."""

    VERSION_LEGACY = 0x17
    CHARGE_CYCLES = 0x1B
    MANUFACTURE_DATE = 0x20
    STATUS = 0x30
    BATTERY_INFO = 0x31
    BATTERY_PERCENT = 0x32
    BATTERY_CURRENT = 0x33
    BATTERY_VOLTAGE = 0x34
    BATTERY_HEALTH = 0x3B
    CELL_VOLTAGES = 0x40
    VERSION_STANDARD = 0x67


class Xiaomi1sTelemetryOffset(IntEnum):
    """Byte offsets from the start of the 1S 0xB0 payload, in wire order."""

    LOCK = 4
    BATTERY_PERCENT = 8
    SPEED = 10
    AVERAGE_SPEED = 12
    ODOMETER = 14
    TRIP_DISTANCE = 18
    UPTIME = 20
    TEMPERATURE = 22


class Xiaomi1sDashboardRegister(IntEnum):
    """Version index observed on some dashboard replies."""

    BLE_VERSION = 0x68


class Xiaomi1sFastTelemetry(IntEnum):
    """Offsets and confirmed lock values in the 1S 0xB0 reply payload."""

    LOCK_BYTE_OFFSET = 4
    VALUES_OFFSET = 8
    MINIMUM_PAYLOAD = 24
    LOCK_UNLOCKED = 0
    LOCK_ACTIVE = 2
    LOCK_ALARM = 6


XIAOMI1S_CONTROLLER_REPLY_IDS = (DeviceId.ESC, LegacyM365Reply.ESC)
XIAOMI1S_BMS_REPLY_IDS = (DeviceId.BMS, LegacyM365Reply.BMS)
XIAOMI1S_KNOWN_LOCK_BYTES = frozenset((
    Xiaomi1sFastTelemetry.LOCK_UNLOCKED,
    Xiaomi1sFastTelemetry.LOCK_ACTIVE,
    Xiaomi1sFastTelemetry.LOCK_ALARM,
))

SOURCE_PHONE = DeviceId.PHONE.value
SOURCE_PC = DeviceId.PC.value

TARGET_ESC = DeviceId.ESC.value
TARGET_BLE = DeviceId.DASHBOARD.value
TARGET_BMS = DeviceId.BMS.value

CMD_READ = PacketOpcode.READ.value
CMD_WRITE = PacketOpcode.WRITE.value
CMD_WRITE_NO_REPLY = PacketOpcode.WRITE_NO_REPLY.value
CMD_READ_ACK = PacketOpcode.READ_ACK.value  # Ninebot-style read reply. Xiaomi replies use CMD_READ (0x01).
CMD_WRITE_ACK = PacketOpcode.WRITE_ACK.value
CMD_INIT = PacketOpcode.INIT.value
CMD_PING = PacketOpcode.PING.value
CMD_PAIR = PacketOpcode.PAIR.value


@dataclass(frozen=True, slots=True)
class NinebotPacket:
    """Decoded logical 5A A5 packet."""

    source: int
    target: int
    command: int
    index: int
    data: bytes = b""

    def pack(self) -> bytes:
        """Pack a logical packet before encryption."""
        return (
            HEADER
            + bytes(
                [
                    len(self.data),
                    self.source,
                    self.target,
                    self.command,
                    self.index,
                ]
            )
            + self.data
        )

    @classmethod
    def unpack(cls, packet: bytes) -> NinebotPacket | None:
        """Decode a decrypted logical packet."""
        if len(packet) < LOGICAL_HEADER_LENGTH or packet[:len(HEADER)] != HEADER:
            return None

        data_len = packet[FrameOffset.LENGTH]
        expected_len = data_len + LOGICAL_HEADER_LENGTH

        if len(packet) != expected_len:
            return None

        return cls(
            source=packet[FrameOffset.SOURCE],
            target=packet[FrameOffset.TARGET],
            command=packet[FrameOffset.COMMAND],
            index=packet[FrameOffset.INDEX],
            data=packet[FrameOffset.DATA:],
        )


def make_read(
    target: int,
    index: int,
    read_length: int,
) -> NinebotPacket:
    """Create a standard control-table read request."""
    return NinebotPacket(
        source=SOURCE_PHONE,
        target=int(target),
        command=CMD_READ,
        index=int(index),
        data=bytes([read_length]),
    )


def make_init() -> NinebotPacket:
    """Create the BLE initialization packet."""
    return NinebotPacket(
        source=SOURCE_PHONE,
        target=TARGET_BLE,
        command=CMD_INIT,
        index=PairingStatus.PENDING.value,
    )


def make_ping(app_key: bytes) -> NinebotPacket:
    """Create the BLE pairing-state packet."""
    return NinebotPacket(
        source=SOURCE_PHONE,
        target=TARGET_BLE,
        command=CMD_PING,
        index=PairingStatus.PENDING.value,
        data=app_key,
    )


def make_pair(serial: bytes) -> NinebotPacket:
    """Create the BLE pairing packet."""
    return NinebotPacket(
        source=SOURCE_PHONE,
        target=TARGET_BLE,
        command=CMD_PAIR,
        index=PairingStatus.PENDING.value,
        data=serial,
    )
