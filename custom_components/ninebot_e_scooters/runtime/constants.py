"""Connection timing and the existing Xiaomi read schedule."""

from __future__ import annotations
from ..protocols.ninebot.packet import (
    DeviceId,
    RegisterReadSize,
    Xiaomi1sBmsRegister,
    Xiaomi1sDashboardRegister,
    Xiaomi1sEscRegister,
)

PAIRING_TIMEOUT = 75.0

STORED_KEY_RECOVERY_TIMEOUT = 35.0

PAIRING_REPLY_TIMEOUT = 0.85

PAIRING_RETRY_PAUSE = 0.15

PAIRING_RETRY_INTERVAL = 1.0

MAX_BLE129_PAYLOAD = 128

MAX_BLE129_BUFFER = 512

TELEMETRY_CACHE_SECONDS = 600

DIRECT_GATT_TIMEOUT = 18.0

GATT_RETRY_COOLDOWN = 5.0

GATT_CLEANUP_COOLDOWN = 25.0

MAX_ADVERTISEMENT_AGE = 5.0

SCANNER_RECENT_SECONDS = 20.0

SCANNER_ALTERNATIVE_MIN_RSSI = -85

SCANNER_SOURCE_COOLDOWN = 90.0

SHORT_SESSION_SECONDS = 120.0

EXTRA_READ_REGISTERS: tuple[tuple[str, int, int, int], ...] = (
    # On the first successful sessions prioritise readings requested by the
    # user. Only ONE optional request is issued after each core refresh.
    # Active control registers are read on their own refresh schedule below.
    ("controller_general_info", DeviceId.ESC, Xiaomi1sEscRegister.GENERAL_INFO, RegisterReadSize.GENERAL_INFO),
    ("ble_version_esc", DeviceId.ESC, Xiaomi1sEscRegister.BLE_VERSION, RegisterReadSize.WORD),
    ("bms_battery_health", DeviceId.BMS, Xiaomi1sBmsRegister.BATTERY_HEALTH, RegisterReadSize.WORD),
    ("bms_manufacture_date", DeviceId.BMS, Xiaomi1sBmsRegister.MANUFACTURE_DATE, RegisterReadSize.BMS_MANUFACTURE_DATE),
    ("esc_error_code", DeviceId.ESC, Xiaomi1sEscRegister.ERROR, RegisterReadSize.WORD),
    ("esc_warning_code", DeviceId.ESC, Xiaomi1sEscRegister.ALARM, RegisterReadSize.WORD),
    ("esc_status_word", DeviceId.ESC, Xiaomi1sEscRegister.STATUS_BITS, RegisterReadSize.WORD),
    # Some BLE129 variants may answer controller version reads from the BLE
    # module itself; if not, BLE version honestly remains unknown.
    ("ble_version_module", DeviceId.DASHBOARD, Xiaomi1sDashboardRegister.BLE_VERSION, RegisterReadSize.WORD),
    ("esc_warning_quick", DeviceId.ESC, Xiaomi1sEscRegister.QUICK_WARNING, RegisterReadSize.WORD),
    ("battery_cell_voltages", DeviceId.BMS, Xiaomi1sBmsRegister.CELL_VOLTAGES, RegisterReadSize.BMS_CELLS),
    ("bms_version", DeviceId.BMS, Xiaomi1sBmsRegister.VERSION_LEGACY, RegisterReadSize.WORD),
    ("bms_version_standard", DeviceId.BMS, Xiaomi1sBmsRegister.VERSION_STANDARD, RegisterReadSize.WORD),
    ("bms_status", DeviceId.BMS, Xiaomi1sBmsRegister.STATUS, RegisterReadSize.WORD),
    ("bms_charge_cycles", DeviceId.BMS, Xiaomi1sBmsRegister.CHARGE_CYCLES, RegisterReadSize.WORD),
)

STATIC_EXTRA_NAMES = frozenset({
    "controller_general_info", "ble_version_esc", "ble_version_module",
    "bms_version", "bms_version_standard", "bms_manufacture_date",
})
