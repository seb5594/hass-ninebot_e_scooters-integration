"""Inert research catalog for possible scooter adapters.

Nothing in this module is imported by discovery, pairing, polling, entities or
controls. Each record is a candidate for a future, separately tested adapter;
it does not establish compatibility with the existing Xiaomi 1S adapter.

Sources: https://github.com/ownbee/ninebot-ble/tree/main/ninebot_ble
         https://github.com/dnandha/miauth (and the miauth 0.9.7 release)
         https://github.com/scooterhacking/NinebotCrypto
         https://wiki.scooterhacking.org/doku.php?id=nbdocs
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re


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
    ProtocolCandidate("ninebot_es", "5A A5", "ninebot_chained", ("BLE109", "BLE110"), "nordic_uart"),
    ProtocolCandidate("ninebot_max", "5A A5", "ninebot_chained", ("BLE110", "BLE113", "BLE114"), "nordic_uart"),
    ProtocolCandidate("ninebot_e", "5A A5", "ninebot_chained", ("BLE209", "BLE213"), "nordic_uart"),
    ProtocolCandidate("ninebot_f", "5A A5", "ninebot_chained", ("BLE307",), "nordic_uart"),
    ProtocolCandidate("xiaomi_ble132_nb", "5A A5", "ninebot_chained", ("BLE132",), "nordic_uart"),
    ProtocolCandidate("xiaomi_ble132_5aab", "5A AB", "to_be_verified", ("BLE132",), "to_be_verified"),
    ProtocolCandidate("xiaomi_mi_ec", "55 AB", "mi_ec_register_or_login", (), "mi_auth_services_and_uart"),
)


# The fourth serial character is a product variant. Only unambiguous variants
# confirmed against the ScooterHacking model pages are listed. Custom firmware
# can change the serial, so this is an identity hint rather than proof.
# N2G: https://wiki.scooterhacking.org/doku.php?id=nbeseries
# N4G: https://wiki.scooterhacking.org/doku.php?id=nbmax
# N5G: https://wiki.scooterhacking.org/doku.php?id=nbfseries
NINEBOT_SERIAL_HINTS: dict[str, tuple[str, dict[str, str]]] = {
    "N2G": ("Ninebot E series", {
        "D": "E22", "G": "E22E", "I": "E22D", "V": "E25",
        "Y": "E25D", "X": "E25E", "Z": "E25A", "R": "E45D",
        "O": "E45E", "M": "E45E", "Q": "E45",
    }),
    "N4G": ("Ninebot Max", {
        "S": "G30P", "C": "G30", "E": "G30D", "P": "G30E",
        "N": "G30LP", "A": "G30LE", "O": "G30LE", "M": "G30LD",
    }),
    "N5G": ("Ninebot F series", {
        "A": "F20", "B": "F20D", "C": "F30", "D": "F30D",
        "E": "F40", "F": "F40E", "G": "F40D", "H": "F60",
        "N": "F25", "O": "F20A", "Q": "F30E", "R": "F40A",
        "V": "F40",
    }),
}


@dataclass(frozen=True, slots=True)
class NinebotSerialHint:
    """A read-only hint extracted from a complete legacy ESC serial."""

    series: str
    family: str
    variant: str
    model_hint: str | None
    production_year: int
    production_week: int
    revision: str


def inspect_ninebot_serial(serial: str | bytes | None) -> NinebotSerialHint | None:
    """Inspect a legacy 14-character serial without changing live discovery."""
    if isinstance(serial, bytes):
        try:
            serial = serial.rstrip(b"\x00").decode("ascii")
        except UnicodeDecodeError:
            return None
    if not isinstance(serial, str) or not re.fullmatch(r"[A-Z0-9]{5}[0-9]{4}[A-Z0-9][0-9]{4}", serial):
        return None
    known = NINEBOT_SERIAL_HINTS.get(serial[:3])
    if known is None:
        return None
    year, week = 2000 + int(serial[5:7]), int(serial[7:9])
    try:
        date.fromisocalendar(year, week, 1)
    except ValueError:
        return None
    family, variants = known
    return NinebotSerialHint(serial[:3], family, serial[3], variants.get(serial[3]), year, week, serial[9])


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
