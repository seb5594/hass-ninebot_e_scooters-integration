"""GATT identifiers and legacy wire constants without Home Assistant imports."""

from __future__ import annotations

from .gatt import NORDIC_UART
from .ninebot.packet import (
    DeviceId,
    LegacyM365Reply,
    PacketOpcode,
    Xiaomi1sBmsRegister,
    Xiaomi1sEscRegister,
)

# Nordic UART Service used by the M365/1S BLE protocol.
NUS_SERVICE_UUID = NORDIC_UART.service_uuid
NUS_TX_UUID = NORDIC_UART.write_uuid
NUS_RX_UUID = NORDIC_UART.notify_uuid
NUS_WRITE_UUID = NUS_TX_UUID  # Scooter RX characteristic: host writes here.
NUS_NOTIFY_UUID = NUS_RX_UUID  # Scooter TX characteristic: host subscribes here.

# Xiaomi Mijia authentication service used by newer BLE generations. The two
# handles a session on it would use next are research-only; see research.py.
AUTH_SERVICE_UUID = "0000fe95-0000-1000-8000-00805f9b34fb"

# M365 protocol directions.
MASTER_TO_MOTOR = DeviceId.ESC.value
MASTER_TO_BATTERY = DeviceId.BMS.value
MOTOR_TO_MASTER = LegacyM365Reply.ESC.value
BATTERY_TO_MASTER = LegacyM365Reply.BMS.value

READ = PacketOpcode.READ.value
WRITE = PacketOpcode.WRITE_NO_REPLY.value

# M365/1S attribute IDs.
# Provenance is documented in ninebot/packet.py. The Ninebot ES table has
# different meanings at 0xB0/0x7B.
ATTR_GENERAL_INFO = Xiaomi1sEscRegister.GENERAL_INFO.value
ATTR_BMS_VERSION = Xiaomi1sBmsRegister.VERSION_STANDARD.value
ATTR_DISTANCE_LEFT = Xiaomi1sEscRegister.DISTANCE_LEFT.value
ATTR_BATTERY_INFO = Xiaomi1sBmsRegister.BATTERY_INFO.value
ATTR_BATTERY_PERCENT = Xiaomi1sBmsRegister.BATTERY_PERCENT.value
ATTR_BATTERY_CURRENT = Xiaomi1sBmsRegister.BATTERY_CURRENT.value
ATTR_BATTERY_VOLTAGE = Xiaomi1sBmsRegister.BATTERY_VOLTAGE.value
ATTR_BATTERY_CELL_VOLTAGES = Xiaomi1sBmsRegister.CELL_VOLTAGES.value
ATTR_TRIP_INFO = Xiaomi1sEscRegister.TRIP_INFO.value
ATTR_SPEED = Xiaomi1sEscRegister.QUICK_SPEED.value
ATTR_TRIP_DISTANCE = Xiaomi1sEscRegister.TRIP_DISTANCE.value
ATTR_CRUISE = Xiaomi1sEscRegister.CRUISE.value
ATTR_TAIL_LIGHT = Xiaomi1sEscRegister.TAIL_LIGHT.value
ATTR_MOTOR_INFO = Xiaomi1sEscRegister.FAST_TELEMETRY.value
ATTR_GET_LOCK = Xiaomi1sEscRegister.LOCK_STATUS.value
ATTR_SET_LOCK = Xiaomi1sEscRegister.LOCK.value
ATTR_UNSET_LOCK = Xiaomi1sEscRegister.UNLOCK.value
ATTR_SUPPLEMENTARY = Xiaomi1sEscRegister.SUPPLEMENTARY_KERS.value
ATTR_KERS = ATTR_SUPPLEMENTARY
