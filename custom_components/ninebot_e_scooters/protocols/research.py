"""Inert research catalog for possible scooter adapters.

Nothing in this module is imported by discovery, pairing, polling, entities or
controls. Each record is a candidate for a future, separately tested adapter;
it does not establish compatibility with an existing one. Families that have
an adapter are described in models/transports.py instead.

Sources: https://github.com/ownbee/ninebot-ble/tree/main/ninebot_ble
         https://github.com/dnandha/miauth (and the miauth 0.9.7 release)
         https://github.com/scooterhacking/NinebotCrypto
         https://wiki.scooterhacking.org/doku.php?id=nbdocs
         https://nootnooot.codeberg.page/segway-ninebot-ble/ (device tables)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProtocolCandidate:
    """Describe a protocol to investigate, without enabling an adapter."""

    family: str
    frame_prefix: str
    authentication: str
    known_ble_versions: tuple[str, ...]
    gatt_transport: str
    adapter_implemented: bool = False


# BLE versions indicate reported examples, not a complete compatibility list.
# 5A AB and 55 AB are different packet prefixes; neither is Ninebot 5A A5.
PROTOCOL_CANDIDATES: tuple[ProtocolCandidate, ...] = (
    ProtocolCandidate("xiaomi_ble132_nb", "5A A5", "ninebot_chained", ("BLE132",), "nordic_uart"),
    ProtocolCandidate("xiaomi_ble132_5aab", "5A AB", "to_be_verified", ("BLE132",), "to_be_verified"),
    ProtocolCandidate("xiaomi_mi_ec", "55 AB", "mi_ec_register_or_login", (), "mi_auth_services_and_uart"),
    # F2, F2 Plus, F2 Pro, E2, E2 Plus and E2 Pro: the vendor device table
    # lists them with XOR-obfuscated frames instead of the chained crypto.
    ProtocolCandidate("ninebot_f2_e2", "5A A5", "xor_obfuscation", (), "to_be_verified"),
    # GT1, GT2, P65 and P100S: same chained crypto, but two motors and an
    # unknown register layout.
    ProtocolCandidate("segway_gt_p", "5A A5", "ninebot_chained", (), "ninebot_uart"),
    # ZT3 Pro and GT3 number their boards like the F3, but their registers
    # have not been compared with it.
    ProtocolCandidate("segway_zt3_gt3", "5A A5", "ninebot_chained", (), "nordic_uart"),
    # Described in the public documentation without naming a scooter: the
    # first key starts from a zero block instead of the firmware constant.
    ProtocolCandidate("segway_zero_seed", "5A A5", "ninebot_chained_zero_seed", (), "to_be_verified"),
)


@dataclass(frozen=True, slots=True)
class RegisterCandidate:
    """Record a potential future read without performing any I/O."""

    target: int
    index: int
    label: str
    words: int = 1
    kind: str = "dynamic"
    note: str = ""


# From ownbee/ninebot-ble register.py. Target 0x20 is the controller and 0x22
# the BMS; most reads request two bytes per word. Shapes and scale factors
# must be verified per scooter before adding entities. Never expose 0x17
# (Bluetooth password) as an entity or through diagnostics.
NINEBOT_READ_CANDIDATES: tuple[RegisterCandidate, ...] = (
    RegisterCandidate(0x20, 0x10, "controller_serial", 7, "static", "Read seven adjacent 2-byte words."),
    RegisterCandidate(0x20, 0x1A, "controller_firmware", kind="static"),
    RegisterCandidate(0x20, 0x1B, "controller_error_code"),
    RegisterCandidate(0x20, 0x1C, "controller_alarm_code"),
    RegisterCandidate(0x20, 0x1D, "controller_status_bits", note="Bit 1 is a lock hint; validate per model."),
    RegisterCandidate(0x20, 0x29, "total_distance", 2, "slow", "Two words; source scales by 1/1000 km."),
    RegisterCandidate(0x20, 0x32, "total_operation_time", 2, "slow"),
    RegisterCandidate(0x20, 0x34, "total_riding_time", 2, "slow"),
    RegisterCandidate(0x20, 0x3E, "controller_temperature", note="Signedness must be validated."),
    RegisterCandidate(0x20, 0x47, "controller_voltage"),
    RegisterCandidate(0x20, 0x68, "ble_firmware", kind="static"),
    RegisterCandidate(0x20, 0x75, "operation_mode", note="Do not reuse Xiaomi 1S mode values."),
    RegisterCandidate(0x20, 0x7B, "kers_level"),
    RegisterCandidate(0x20, 0x7C, "cruise_state"),
    RegisterCandidate(0x20, 0x7D, "rear_light_state"),
    RegisterCandidate(0x22, 0x10, "bms_serial", 7, "static"),
    RegisterCandidate(0x22, 0x17, "bms_firmware", kind="static"),
    RegisterCandidate(
        0x22, 0x20, "battery_manufacture_date", kind="static",
        note="M365 BMS stores a packed battery date; verify the epoch per model before decoding.",
    ),
    RegisterCandidate(0x22, 0x31, "remaining_battery_capacity"),
    RegisterCandidate(0x22, 0x32, "battery_charge_percent"),
    RegisterCandidate(0x22, 0x33, "battery_current", note="Signed 16-bit; source scales by 1/100 A."),
    RegisterCandidate(0x22, 0x34, "battery_voltage", note="Source scales by 1/100 V."),
    RegisterCandidate(0x22, 0x35, "battery_temperatures", note="Two temperatures share one 16-bit word."),
    RegisterCandidate(0x22, 0x3B, "battery_health"),
)
