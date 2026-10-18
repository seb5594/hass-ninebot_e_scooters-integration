"""Xiaomi M365/1S BLE protocol implementation.

The packet definitions are based on the public M365 BLE protocol and the
original m365py message definitions.  The BLE transport itself is handled by
Home Assistant/Bleak rather than by bluepy.
"""

from __future__ import annotations

from .data import ScooterData

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import IntEnum
import struct

from ..protocols.ninebot.packet import (
    RegisterReadSize,
    Xiaomi1sBmsRegister,
    Xiaomi1sEscRegister,
    Xiaomi1sFastTelemetry,
    XIAOMI1S_BMS_REPLY_IDS,
    XIAOMI1S_CONTROLLER_REPLY_IDS,
    XIAOMI1S_KNOWN_LOCK_BYTES,
)

from .constants import (
    ATTR_BATTERY_CELL_VOLTAGES,
    ATTR_BATTERY_INFO,
    ATTR_BMS_VERSION,
    ATTR_CRUISE,
    ATTR_DISTANCE_LEFT,
    ATTR_GENERAL_INFO,
    ATTR_GET_LOCK,
    ATTR_MOTOR_INFO,
    ATTR_SPEED,
    ATTR_SUPPLEMENTARY,
    ATTR_TAIL_LIGHT,
    ATTR_TRIP_INFO,
    MASTER_TO_BATTERY,
    MASTER_TO_MOTOR,
    READ,
    WRITE,
)

HEADER = b"\x55\xAA"
LEGACY_FRAME_OVERHEAD = 6
LEGACY_MINIMUM_CONTENT_LENGTH = 2
LEGACY_MINIMUM_FRAME_LENGTH = LEGACY_FRAME_OVERHEAD + LEGACY_MINIMUM_CONTENT_LENGTH
LEGACY_MAXIMUM_FRAME_LENGTH = 512


class LegacyFrameOffset(IntEnum):
    """Byte offsets in the unencrypted 55 AA frame."""

    LENGTH = 2
    DIRECTION = 3
    COMMAND = 4
    REGISTER = 5
    PAYLOAD = 6


@dataclass(frozen=True, slots=True)
class ScooterCommand:
    """Represent one M365 protocol command."""

    direction: int
    read_write: int
    attribute: int
    payload: bytes

    def build(self) -> bytes:
        """Build a protocol packet."""
        length = len(self.payload) + 2
        body = bytes(
            [
                length,
                self.direction,
                self.read_write,
                self.attribute,
            ]
        ) + self.payload

        checksum = sum(body)
        checksum ^= 0xFFFF
        checksum &= 0xFFFF

        return HEADER + body + struct.pack("<H", checksum)


@dataclass(frozen=True, slots=True)
class ScooterMessage:
    """Represent one decoded M365 protocol message."""

    direction: int
    read_write: int
    attribute: int
    payload: bytes
    raw: bytes


def _format_packed_version(value: int) -> str:
    """Format a packed Xiaomi firmware version such as 0x0138 as V1.3.8."""
    text = f"{value:04x}"
    text = text.lstrip("0") or "0"
    return f"V{'.'.join(text)}"


def make_read(direction: int, attribute: int, parameter: int) -> bytes:
    """Build a read command."""
    return ScooterCommand(direction, READ, attribute, bytes([parameter])).build()


def make_write(direction: int, attribute: int, payload: bytes) -> bytes:
    """Build a write command."""
    return ScooterCommand(direction, WRITE, attribute, payload).build()


def standard_read_commands() -> tuple[tuple[str, bytes], ...]:
    """Return the supported legacy M365 read requests."""
    return (
        (
            "general_info",
            make_read(MASTER_TO_MOTOR, ATTR_GENERAL_INFO, RegisterReadSize.GENERAL_INFO),
        ),
        (
            "motor_info",
            make_read(MASTER_TO_MOTOR, ATTR_MOTOR_INFO, RegisterReadSize.FAST_TELEMETRY),
        ),
        (
            "battery_info",
            make_read(MASTER_TO_BATTERY, ATTR_BATTERY_INFO, RegisterReadSize.TRIP_AND_BATTERY),
        ),
        (
            "cell_voltages",
            make_read(MASTER_TO_BATTERY, ATTR_BATTERY_CELL_VOLTAGES, RegisterReadSize.BMS_CELLS),
        ),
        (
            "trip_info",
            make_read(MASTER_TO_MOTOR, ATTR_TRIP_INFO, RegisterReadSize.TRIP_AND_BATTERY),
        ),
        (
            "distance_left",
            make_read(MASTER_TO_MOTOR, ATTR_DISTANCE_LEFT, RegisterReadSize.WORD),
        ),
        (
            "speed",
            make_read(MASTER_TO_MOTOR, ATTR_SPEED, RegisterReadSize.WORD),
        ),
        (
            "cruise",
            make_read(MASTER_TO_MOTOR, ATTR_CRUISE, RegisterReadSize.WORD),
        ),
        (
            "tail_light",
            make_read(MASTER_TO_MOTOR, ATTR_TAIL_LIGHT, RegisterReadSize.WORD),
        ),
        (
            "lock",
            make_read(MASTER_TO_MOTOR, ATTR_GET_LOCK, RegisterReadSize.WORD),
        ),
        (
            "supplementary",
            make_read(MASTER_TO_BATTERY, ATTR_SUPPLEMENTARY, RegisterReadSize.SUPPLEMENTARY),
        ),
    )


def tail_light_command(enabled: bool) -> bytes:
    """Build the tail-light write command."""
    return make_write(
        MASTER_TO_MOTOR,
        ATTR_TAIL_LIGHT,
        b"\x02\x00" if enabled else b"\x00\x00",
    )


def parse_message(raw: bytes) -> ScooterMessage | None:
    """Parse one complete legacy M365 packet."""
    if len(raw) < LEGACY_MINIMUM_FRAME_LENGTH or raw[:len(HEADER)] != HEADER:
        return None

    length = raw[LegacyFrameOffset.LENGTH]
    total_length = length + LEGACY_FRAME_OVERHEAD

    # Legacy packet:
    # 55 AA | length | direction | rw | attribute | payload | checksum(2)
    if length < LEGACY_MINIMUM_CONTENT_LENGTH or total_length != len(raw):
        return None

    payload_end = LegacyFrameOffset.PAYLOAD + length - LEGACY_MINIMUM_CONTENT_LENGTH
    if payload_end > len(raw) - 2:
        return None

    payload = raw[LegacyFrameOffset.PAYLOAD:payload_end]
    checksum = sum(raw[2:payload_end])
    checksum ^= 0xFFFF
    checksum &= 0xFFFF

    expected_checksum = int.from_bytes(raw[payload_end:payload_end + 2], "little")

    if checksum != expected_checksum:
        return None

    return ScooterMessage(
        direction=raw[LegacyFrameOffset.DIRECTION],
        read_write=raw[LegacyFrameOffset.COMMAND],
        attribute=raw[LegacyFrameOffset.REGISTER],
        payload=payload,
        raw=raw,
    )


class PacketParser:
    """Reassemble M365 packets from arbitrary BLE notification chunks."""

    def __init__(self) -> None:
        """Initialize the packet parser."""
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[ScooterMessage]:
        """Feed notification bytes and return all complete messages."""
        if not data:
            return []

        self._buffer.extend(data)
        messages: list[ScooterMessage] = []

        while True:
            header_index = self._buffer.find(HEADER)
            if header_index < 0:
                # Preserve a possible trailing 0x55 for the next BLE fragment.
                self._buffer[:] = self._buffer[-1:] if self._buffer[-1:] == HEADER[:1] else b""
                break

            if header_index:
                del self._buffer[:header_index]

            if len(self._buffer) <= LegacyFrameOffset.LENGTH:
                break

            length = self._buffer[LegacyFrameOffset.LENGTH]
            total_length = length + LEGACY_FRAME_OVERHEAD

            if length < LEGACY_MINIMUM_CONTENT_LENGTH or total_length > LEGACY_MAXIMUM_FRAME_LENGTH:
                del self._buffer[:2]
                continue

            if len(self._buffer) < total_length:
                break

            raw = bytes(self._buffer[:total_length])
            del self._buffer[:total_length]

            message = parse_message(raw)
            if message is not None:
                messages.append(message)

        return messages


def _safe_temperature(value: int) -> float:
    """Convert battery temperature encoding to degrees Celsius."""
    return value - 20.0


def decode_battery_manufacture_date(payload: bytes) -> str | None:
    """Decode the Xiaomi M365 BMS register 0x20 packed battery pack date."""
    # Some BMS revisions return one word; documented M365 replies return
    # three words, with the packed date in the first one.
    if len(payload) not in (RegisterReadSize.WORD, RegisterReadSize.BMS_MANUFACTURE_DATE):
        return None
    packed = int.from_bytes(payload[:RegisterReadSize.WORD], "little")
    if packed in (0, 0xFFFF):
        return None
    # The M365 compatible BMS firmware encodes 2018 as 18 << 9. This is
    # its own register format; the unrelated SMBus date uses a 1980 epoch.
    year = 2000 + (packed >> 9)
    month = (packed >> 5) & 0x0F
    day = packed & 0x1F
    if year < 2016:
        return None
    try:
        manufactured = date(year, month, day)
    except ValueError:
        return None
    return manufactured.isoformat() if manufactured <= date.today() else None


def apply_message(data: ScooterData, message: ScooterMessage) -> bool:
    """Apply one decoded scooter message to the data model."""
    if message.read_write not in (1, 4):
        return False
    controller = message.direction in XIAOMI1S_CONTROLLER_REPLY_IDS
    battery = message.direction in XIAOMI1S_BMS_REPLY_IDS
    if message.attribute in (
        ATTR_GENERAL_INFO, ATTR_MOTOR_INFO, ATTR_TRIP_INFO, ATTR_SPEED,
        ATTR_DISTANCE_LEFT, ATTR_CRUISE, ATTR_TAIL_LIGHT, ATTR_GET_LOCK,
        ATTR_SUPPLEMENTARY, Xiaomi1sEscRegister.ALARM,
        Xiaomi1sEscRegister.STATUS_BITS, Xiaomi1sEscRegister.QUICK_WARNING,
    ) and not controller:
        return False
    if message.attribute in (
        ATTR_BATTERY_INFO, ATTR_BATTERY_CELL_VOLTAGES, ATTR_BMS_VERSION,
        Xiaomi1sBmsRegister.VERSION_LEGACY, Xiaomi1sBmsRegister.STATUS,
        Xiaomi1sBmsRegister.BATTERY_HEALTH, Xiaomi1sBmsRegister.MANUFACTURE_DATE,
    ) and not battery:
        return False
    if message.attribute == Xiaomi1sEscRegister.ERROR and not (controller or battery):
        return False
    if message.attribute == ATTR_GENERAL_INFO:
        if len(message.payload) < 22:
            return False

        serial, _pin, version = struct.unpack("<14s6sH", message.payload[:22])
        data.serial = serial.rstrip(b"\x00").decode("utf-8", errors="replace")
        data.firmware_version = _format_packed_version(version)
        return True

    if message.attribute in (ATTR_BMS_VERSION, Xiaomi1sBmsRegister.VERSION_LEGACY):
        if len(message.payload) >= 2:
            version = struct.unpack_from("<H", message.payload)[0]
            if version == 0 or version == 0xFFFF:
                return False
            data.bms_version = _format_packed_version(version)
            return True
        return False

    if message.attribute == Xiaomi1sBmsRegister.MANUFACTURE_DATE:
        if message.direction not in XIAOMI1S_BMS_REPLY_IDS:
            return False
        manufactured = decode_battery_manufacture_date(message.payload)
        if manufactured is None:
            return False
        data.battery_manufacture_date = manufactured
        return True

    # One-at-a-time optional reads. Do not reinterpret short 0xB0 telemetry as
    # an error: 0xB0/len32 is the PROVEN fast data block on this 1S.
    if message.attribute in (
        Xiaomi1sEscRegister.ERROR, Xiaomi1sEscRegister.ALARM,
        Xiaomi1sEscRegister.STATUS_BITS, Xiaomi1sEscRegister.WORK_MODE,
        Xiaomi1sEscRegister.BLE_VERSION, Xiaomi1sEscRegister.QUICK_WARNING,
        Xiaomi1sBmsRegister.STATUS, Xiaomi1sBmsRegister.BATTERY_HEALTH,
    ):
        if len(message.payload) < RegisterReadSize.WORD:
            return False
        value = struct.unpack_from("<H", message.payload)[0]
        source = message.direction
        if message.attribute == Xiaomi1sEscRegister.ERROR:
            if source in XIAOMI1S_BMS_REPLY_IDS:
                data.battery_charge_cycles = value
            else:
                data.error_flags = value
        elif message.attribute == Xiaomi1sEscRegister.ALARM:
            data.warning_flags = value
        elif message.attribute == Xiaomi1sEscRegister.STATUS_BITS:
            data.status_flags = value
        elif message.attribute == Xiaomi1sEscRegister.WORK_MODE:
            if source not in XIAOMI1S_CONTROLLER_REPLY_IDS or value not in (0, 1, 2):
                return False
            data.work_mode = value
        elif message.attribute == Xiaomi1sEscRegister.BLE_VERSION:
            if value in (0, 0xFFFF):
                return False
            data.ble_version = _format_packed_version(value)
        elif message.attribute == Xiaomi1sEscRegister.QUICK_WARNING:
            data.warning_flags = value
        elif message.attribute == Xiaomi1sBmsRegister.STATUS and source in XIAOMI1S_BMS_REPLY_IDS:
            data.bms_status_flags = value
        elif message.attribute == Xiaomi1sBmsRegister.BATTERY_HEALTH and source in XIAOMI1S_BMS_REPLY_IDS:
            if not 0 <= value <= 100:
                return False
            data.battery_health_percent = value
        else:
            return False
        return True

    if message.attribute == ATTR_MOTOR_INFO:
        # m365py decodes:
        # payload[8:] -> battery %, speed, avg speed, odometer, trip,
        # uptime and frame temperature.
        if len(message.payload) < Xiaomi1sFastTelemetry.MINIMUM_PAYLOAD:
            return False

        # Legacy M365 maps its lock/alarm state to B0 payload byte four.
        # Interpret only documented values; unknown variants remain unknown.
        lock_byte = message.payload[Xiaomi1sFastTelemetry.LOCK_BYTE_OFFSET]
        if lock_byte in XIAOMI1S_KNOWN_LOCK_BYTES:
            data.is_lock_on = lock_byte in (Xiaomi1sFastTelemetry.LOCK_ACTIVE, Xiaomi1sFastTelemetry.LOCK_ALARM)

        (
            battery_percent,
            speed_raw,
            average_speed_raw,
            odometer_raw,
            trip_distance_raw,
            uptime_raw,
            temperature_raw,
        ) = struct.unpack_from(
            "<HhHIhhh",
            message.payload,
            Xiaomi1sFastTelemetry.VALUES_OFFSET,
        )

        data.battery_percent = float(battery_percent)
        data.speed_kmh = speed_raw / 100.0
        data.speed_average_kmh = average_speed_raw / 100.0
        data.odometer_km = odometer_raw / 1000.0
        data.trip_distance_m = float(trip_distance_raw)
        data.uptime_s = int(uptime_raw)
        data.frame_temperature_c = temperature_raw / 10.0
        return True

    if message.attribute == ATTR_TRIP_INFO:
        if len(message.payload) < RegisterReadSize.TRIP_AND_BATTERY:
            return False

        uptime_raw, trip_distance_raw, temperature_raw = struct.unpack(
            "<HIxxh",
            message.payload[:RegisterReadSize.TRIP_AND_BATTERY],
        )
        data.uptime_s = int(uptime_raw)
        data.trip_distance_m = float(trip_distance_raw)
        data.frame_temperature_c = temperature_raw / 10.0
        return True

    if message.attribute == ATTR_BATTERY_INFO:
        if len(message.payload) < RegisterReadSize.TRIP_AND_BATTERY:
            return False

        (
            capacity_raw,
            battery_percent,
            current_raw,
            voltage_raw,
            temperature_1_raw,
            temperature_2_raw,
        ) = struct.unpack("<HHhHBB", message.payload[:RegisterReadSize.TRIP_AND_BATTERY])

        data.battery_capacity_ah = capacity_raw / 1000.0
        data.battery_percent = float(battery_percent)
        data.battery_current_a = current_raw / 100.0
        data.battery_voltage_v = voltage_raw / 100.0
        data.battery_temperature_1_c = _safe_temperature(temperature_1_raw)
        data.battery_temperature_2_c = _safe_temperature(temperature_2_raw)
        return True

    if message.attribute == ATTR_BATTERY_CELL_VOLTAGES:
        if len(message.payload) < 20:
            return False

        cells = struct.unpack("<10H", message.payload[:20])
        if not all(2500 <= value <= 4500 for value in cells):
            # SHFW or a different BMS may return an incompatible layout;
            # leave the existing good values untouched rather than displaying
            # physically implausible 30-40 V 'individual cells'.
            return False
        data.battery_cell_voltages = tuple(value / 1000.0 for value in cells)
        return True

    if message.attribute == ATTR_DISTANCE_LEFT:
        if len(message.payload) < 2:
            return False
        data.distance_left_km = struct.unpack_from("<H", message.payload)[0] / 100.0
        return True

    if message.attribute == ATTR_SPEED:
        if len(message.payload) < 2:
            return False
        data.speed_kmh = struct.unpack_from("<h", message.payload)[0] / 100.0
        return True

    if message.attribute == ATTR_CRUISE:
        if len(message.payload) < 2:
            return False
        data.is_cruise_on = struct.unpack_from("<H", message.payload)[0] == 1
        return True

    if message.attribute == ATTR_TAIL_LIGHT:
        if len(message.payload) < 2:
            return False
        data.is_tail_light_on = struct.unpack_from("<H", message.payload)[0] == 2
        return True

    if message.attribute == ATTR_GET_LOCK:
        if len(message.payload) < 2:
            return False
        state_word = struct.unpack_from("<H", message.payload)[0]
        # Other bitfields must not silently appear as an unlocked scooter.
        if state_word not in (0, 2):
            return False
        data.is_lock_on = state_word == 2
        data.status_flags = state_word
        return True

    if message.attribute == ATTR_SUPPLEMENTARY:
        if len(message.payload) < 2:
            return False

        kers_mode = struct.unpack_from("<H", message.payload)[0]
        if kers_mode not in (0, 1, 2):
            return False
        data.kers_mode = kers_mode
        if len(message.payload) >= 4:
            cruise_raw = struct.unpack_from("<H", message.payload, 2)[0]
            if cruise_raw in (0, 1):
                data.is_cruise_on = cruise_raw == 1
        if len(message.payload) >= 6:
            light_raw = struct.unpack_from("<H", message.payload, 4)[0]
            if light_raw in (0, 2):
                data.is_tail_light_on = light_raw == 2
        return True

    return False


def merge_messages(messages: Iterable[ScooterMessage]) -> ScooterData:
    """Convert protocol messages into one data object."""
    data = ScooterData()
    for message in messages:
        apply_message(data, message)
    data.raw_packets = tuple(message.raw.hex() for message in messages)[-20:]
    return data
