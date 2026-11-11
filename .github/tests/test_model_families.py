"""Every selectable model, driven through a full session against a simulated scooter.

Only the Xiaomi 1S has been checked on hardware. For the other models these
tests are the closest substitute: the simulator holds a register file laid out
as the public sources document it (docs/PROTOCOL_SOURCES.md) and answers the
real coordinator over fragmented, encrypted GATT. They prove that each model
resolves to its adapter, asks only for documented registers and decodes them;
they cannot prove that the sources match every firmware.
"""

import asyncio
import struct

import pytest

from custom_components.ninebot_e_scooters.models.profiles import (
    AUTO_MODEL,
    CONFIGURABLE_MODELS,
    BLE129,
    M365_LEGACY,
    M365_PRO_CRYPTO,
    NINEBOT_E,
    NINEBOT_ES,
    NINEBOT_F,
    NINEBOT_MAX,
    NINEBOT_MAX_G2,
    NINEBOT_VCU,
    PROFILES,
    PROFILES_BY_NAME,
    UNVERIFIED,
    XIAOMI_1S_WRITABLE_SETTINGS,
    identify_model,
    uses_ninebot_word_registers,
)
from custom_components.ninebot_e_scooters.models.serials import FAMILY_BY_PRODUCT, SERIAL_VARIANTS
from custom_components.ninebot_e_scooters.models.transports import TRANSPORT_PROFILES, transport_for_family
from custom_components.ninebot_e_scooters.protocols.gatt import (
    NINEBOT_UART,
    NORDIC_UART,
    find_uart_characteristics,
)
from custom_components.ninebot_e_scooters.protocols.ninebot.packet import (
    CMD_INIT,
    CMD_PAIR,
    CMD_PING,
    CMD_READ,
    DeviceId,
)
from custom_components.ninebot_e_scooters.protocols.ninebot.registers import CLASSIC_REGISTERS
from scooter_simulator import (
    SimulatedGattClient,
    SimulatedScooter,
    answer_quickly,
    bring_into_range,
    poll,
    words,
)
from test_runtime_import import runtime  # noqa: F401  (pytest fixture)

READ_ONLY_SESSION_COMMANDS = {CMD_INIT, CMD_PING, CMD_PAIR, CMD_READ}
NINEBOT_NAME = "NBScooter1234"


def classic_ninebot_boards(serial: bytes) -> dict:
    """Register file of a classic Ninebot with a locked, parked scooter."""
    return {
        DeviceId.ESC: {
            0x10: serial,
            0x1A: words(0x0128),                      # firmware 1.2.8
            0x1B: words(0, 0, 0x0002),                # no error, no warning, locked
            0x25: words(2350),                        # 23.5 km left
            0x29: (120123).to_bytes(4, "little"),     # 120.123 km in total
            0x3E: words(265),                         # 26.5 degrees
            0x65: words(183),                         # 18.3 km/h on average
            0x68: words(0x0110),                      # Bluetooth firmware 1.1.0
            0x75: words(1),                           # eco
        },
        DeviceId.BMS: {
            0x17: words(0x0136),                      # BMS firmware 1.3.6
            0x1B: words(42),                          # charge cycles
            0x31: words(7650, 80, -123, 4120),        # 7.65 Ah, 80 %, -1.23 A, 41.2 V
            0x35: bytes((45, 46)),                    # 25 and 26 degrees
            0x3B: words(97),                          # 97 % health
        },
    }


CLASSIC_NINEBOT_READINGS = {
    "firmware_version": "V1.2.8", "ble_version": "V1.1.0", "bms_version": "V1.3.6",
    "error_flags": 0, "warning_flags": 0, "status_flags": 2, "is_lock_on": True,
    "distance_left_km": 23.5, "odometer_km": 120.123, "frame_temperature_c": 26.5,
    "speed_average_kmh": 18.3, "work_mode": 1, "battery_charge_cycles": 42,
    "battery_capacity_ah": 7.65, "battery_percent": 80, "battery_current_a": -1.23,
    "battery_voltage_v": 41.2, "battery_temperature_1_c": 25.0, "battery_temperature_2_c": 26.0,
    "battery_health_percent": 97,
}

# Model, a serial of that model line (or an unlisted one) and the model the serial reveals.
CLASSIC_NINEBOT_SCOOTERS = [
    ("Ninebot ES4", b"N2GSF2126K2577", "Ninebot ES4"),
    ("Ninebot ES", b"N2GTA1939C0123", "Ninebot ES2"),
    ("Ninebot G30D", b"N4GEC2110C1234", "Ninebot G30D"),
    ("Ninebot G30LP", b"N4GNA2110C1234", "Ninebot G30LP"),
    ("Ninebot E25", b"N2GVA2140C0001", "Ninebot E25"),
    ("Ninebot E45", b"N2GQA2140C0001", "Ninebot E45"),
    ("Ninebot F40", b"N5GEC2110C1234", "Ninebot F40"),
    ("Ninebot F25", b"N5GNC2110C1234", "Ninebot F25"),
    ("Ninebot Max G2", b"01GXE2319C0338", "Ninebot Max G2"),
    ("Ninebot F65", b"A1B2C2319C0338", None),
    ("Ninebot D38", b"A1B2C2319C0338", None),
]


@pytest.mark.parametrize("model,serial,revealed_model", CLASSIC_NINEBOT_SCOOTERS,
                         ids=[scooter[0] for scooter in CLASSIC_NINEBOT_SCOOTERS])
def test_classic_ninebot_pairs_and_reads_every_documented_register(
        runtime, model, serial, revealed_model):  # noqa: F811
    async def check():
        scooter, _ = runtime(model)
        scooter._pairing_completed = False
        answer_quickly(scooter)
        transport = scooter.transport_profile
        simulated = SimulatedScooter(NINEBOT_NAME, serial, classic_ninebot_boards(serial),
                                     host_id=transport.host_id)
        await bring_into_range(scooter, SimulatedGattClient(simulated, transport.uart), NINEBOT_NAME)

        data = await poll(scooter, times=1 + len(CLASSIC_REGISTERS.optional))

        assert scooter._authentication_mode == "first_pairing"
        assert data.serial == serial.decode()
        for field, expected in CLASSIC_NINEBOT_READINGS.items():
            assert getattr(data, field) == pytest.approx(expected), field
        assert scooter.detected_model == revealed_model
        assert not scooter._model_conflict

        assert {request.command for request in simulated.requests} == READ_ONLY_SESSION_COMMANDS
        reads = [request for request in simulated.requests if request.command == CMD_READ]
        assert {request.target for request in reads} == {DeviceId.ESC, DeviceId.BMS}
        assert all(request.data == b"\x02" for request in reads), "one register word per request"
        assert not any((request.target, request.index) == (DeviceId.ESC, 0x17) for request in reads)
        assert not any(scooter.supports_action(setting) for setting in XIAOMI_1S_WRITABLE_SETTINGS)
        await scooter.async_shutdown()
    asyncio.run(check())


def xiaomi_boards() -> dict:
    """Register file of a parked, unlocked Xiaomi scooter as the 1S lays it out."""
    lock_and_flags = bytes(8)
    ride_values = struct.pack("<HhHIhhh", 76, 0, 1520, 345678, 1200, 600, 235)
    return {
        DeviceId.ESC: {0xB0: (lock_and_flags + ride_values).ljust(32, b"\x00")},
        DeviceId.BMS: {0x31: struct.pack("<HHhHBB", 6100, 76, -50, 3980, 45, 46)},
    }


@pytest.mark.parametrize("model,name,serial", [
    ("Mi Electric Scooter Pro 2", "MIScooter4321", b"26354/00012345"),
    ("Mi Electric Scooter Essential", "MIScooter4321", b"25702/00012345"),
    ("Mi Electric Scooter Pro", "MIScooter4321", b"18832/00012345"),
])
def test_untested_xiaomi_models_read_the_shared_blocks_and_stay_read_only(
        runtime, model, name, serial):  # noqa: F811
    async def check():
        scooter, _ = runtime(model)
        answer_quickly(scooter)
        simulated = SimulatedScooter(name, serial, xiaomi_boards(), read_reply_command=CMD_READ)
        await bring_into_range(scooter, SimulatedGattClient(simulated), name)

        data = await poll(scooter, times=2)

        assert scooter.detected_model == model
        assert (data.battery_percent, data.is_lock_on) == (76, False)
        assert data.odometer_km == pytest.approx(345.678)
        assert data.speed_average_kmh == pytest.approx(15.2)
        assert data.frame_temperature_c == pytest.approx(23.5)
        assert data.battery_voltage_v == pytest.approx(39.8)
        assert data.battery_current_a == pytest.approx(-0.5)
        assert data.battery_capacity_ah == pytest.approx(6.1)
        # Writes were confirmed on the 1S only; nothing may reach another model.
        assert {request.command for request in simulated.requests} <= READ_ONLY_SESSION_COMMANDS
        assert not any(scooter.supports_action(setting) for setting in XIAOMI_1S_WRITABLE_SETTINGS)
        await scooter.async_shutdown()
    asyncio.run(check())


def test_every_model_in_the_setup_form_has_a_working_adapter():
    assert CONFIGURABLE_MODELS[0] == AUTO_MODEL
    for name in CONFIGURABLE_MODELS[1:]:
        profile = PROFILES_BY_NAME[name]
        transport = transport_for_family(profile.protocol)
        assert transport is not None and transport.adapter_implemented, name
        assert transport.uart is not None, name
        assert uses_ninebot_word_registers(profile) == (transport.registers is not None), name


def test_profiles_without_an_adapter_cannot_be_selected():
    unverified = [profile.name for profile in PROFILES if profile.protocol == UNVERIFIED]
    assert unverified and not set(unverified) & set(CONFIGURABLE_MODELS)
    assert not transport_for_family(UNVERIFIED).adapter_implemented


def test_every_profile_names_a_known_family_and_names_are_unique():
    assert len(PROFILES_BY_NAME) == len(PROFILES)
    assert {profile.protocol for profile in PROFILES} == set(TRANSPORT_PROFILES)


def test_only_the_reference_scooter_is_hardware_tested_and_writable():
    tested = [profile.name for profile in PROFILES if profile.hardware_tested]
    writable = [profile.name for profile in PROFILES if profile.writable_settings]
    assert tested == writable == ["Mi Electric Scooter 1S"]
    assert PROFILES_BY_NAME["Mi Electric Scooter 1S"].protocol == BLE129


def test_serial_prefixes_belong_to_exactly_one_xiaomi_model():
    prefixes = [prefix for profile in PROFILES for prefix in profile.serial_prefixes]
    assert len(prefixes) == len(set(prefixes))
    assert all(len(prefix) == 5 and prefix.isdigit() for prefix in prefixes)
    for profile in PROFILES:
        for prefix in profile.serial_prefixes:
            assert identify_model(f"{prefix}/00012345").model == profile.name


FAMILY_PROTOCOLS = {
    "Ninebot ES": NINEBOT_ES, "Ninebot E series": NINEBOT_E, "Ninebot Max": NINEBOT_MAX,
    "Ninebot F series": NINEBOT_F, "Ninebot Max G2": NINEBOT_MAX_G2,
}


def test_every_serial_variant_resolves_to_a_profile_of_its_own_family():
    for product, variants in SERIAL_VARIANTS.items():
        for letter, (family, model) in variants.items():
            finding = identify_model(f"{product}{letter}A2110C1234")
            profile = PROFILES_BY_NAME[finding.model]
            assert finding.model == f"Ninebot {model}", (product, letter)
            assert profile.protocol == FAMILY_PROTOCOLS[family], (product, letter)
            assert not profile.writable_settings


def test_unlisted_variant_of_a_single_family_product_falls_back_to_the_family():
    for product, family in FAMILY_BY_PRODUCT.items():
        unlisted = next(letter for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                        if letter not in SERIAL_VARIANTS[product])
        finding = identify_model(f"{product}{unlisted}A2110C1234")
        assert finding.model == family
        assert PROFILES_BY_NAME[family].protocol == FAMILY_PROTOCOLS[family]


class BothSerialServices:
    """Service collection of a scooter that offers the Nordic and the Ninebot UART."""

    def get_characteristic(self, uuid):
        return uuid


@pytest.mark.parametrize("model,expected", [
    ("Ninebot Max G2", NINEBOT_UART), ("Ninebot D38", NINEBOT_UART),
    ("Ninebot G30D", NORDIC_UART), ("Ninebot F3 Pro", NORDIC_UART),
    ("Mi Electric Scooter 1S", NORDIC_UART),
])
def test_documented_serial_service_wins_when_a_scooter_offers_both(model, expected):
    transport = transport_for_family(PROFILES_BY_NAME[model].protocol)
    chosen = find_uart_characteristics(BothSerialServices(), transport.uart)
    assert chosen == (expected.write_uuid, expected.notify_uuid)
    assert find_uart_characteristics(BothSerialServices()) == (NORDIC_UART.write_uuid, NORDIC_UART.notify_uuid)


@pytest.mark.parametrize("model", [
    "Ninebot F2", "Ninebot F2 Plus", "Ninebot F2 Pro", "Ninebot E2", "Ninebot E2 Plus", "Ninebot E2 Pro",
])
def test_models_the_vendor_app_reaches_without_the_chained_crypto_are_not_offered(model):
    assert PROFILES_BY_NAME[model].protocol == UNVERIFIED
    assert model not in CONFIGURABLE_MODELS


def test_families_differ_only_where_the_sources_say_so():
    assert transport_for_family(NINEBOT_F).host_id == DeviceId.PC
    others = [family for family, transport in TRANSPORT_PROFILES.items()
              if transport.adapter_implemented and family != NINEBOT_F]
    assert all(transport_for_family(family).host_id == DeviceId.PHONE for family in others)
    assert transport_for_family(M365_LEGACY).registers is None
    assert transport_for_family(M365_PRO_CRYPTO).registers is None
    assert transport_for_family(NINEBOT_VCU).registers is not CLASSIC_REGISTERS
