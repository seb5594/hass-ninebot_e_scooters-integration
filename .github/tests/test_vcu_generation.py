"""Ninebot F3 and Max G3: other board numbers, other registers, one stored password.

Register contents below are raw values with the readings an F3 owner compared
with the vendor app (https://github.com/BobMcGlobus/ha-ninebot/issues/9).
"""

import asyncio

import pytest

from custom_components.ninebot_e_scooters.models.profiles import (
    PROFILES_BY_NAME,
    VCU_GENERATION,
    effective_profile,
    identify_generation,
    identify_model,
    supports_write,
)
from custom_components.ninebot_e_scooters.models.transports import TRANSPORT_PROFILES, transport_for_family
from custom_components.ninebot_e_scooters.protocols.data import ScooterData
from custom_components.ninebot_e_scooters.protocols.gatt import NINEBOT_UART, NORDIC_UART
from custom_components.ninebot_e_scooters.protocols.ninebot.packet import CMD_READ_ACK, DeviceId, NinebotPacket
from custom_components.ninebot_e_scooters.protocols.ninebot.registers import VCU_REGISTERS, apply_packet
from scooter_simulator import (
    SimulatedGattClient,
    SimulatedScooter,
    answer_quickly,
    bring_into_range,
    poll,
    words,
)
from test_runtime_import import runtime  # noqa: F401  (pytest fixture)

SERIAL = b"1EFB02519C0042"
NAME = SERIAL.decode()  # This generation advertises its serial as Bluetooth name.
SAVED_PASSWORD = bytes.fromhex("ab" * 16)  # The key the runtime fixture stores.

F3_BOARDS = {
    DeviceId.VCU: {
        0x10: SERIAL,
        0x55: words(87),                              # battery 87 %
        0x58: words(0, 0),                            # no error, no warning
        0x5F: words(3120),                            # 31.2 km left
        0x62: (12345).to_bytes(4, "little"),          # 1234.5 km in total
        0x6B: words(215),                             # 21.5 degrees
    },
    DeviceId.VCU_BATTERY: {
        0x59: words(12),                              # charge cycles
        0x5B: words(948),                             # 9480 mAh left
        0x8C: words(5352),                            # 53.52 V
        0x8D: words(150),                             # charging with 1.5 A
        0x96: bytes((25, 0xFF)),                      # one sensor at 25 degrees, one missing
    },
}


def f3(**options) -> SimulatedScooter:
    return SimulatedScooter(NAME, SERIAL, F3_BOARDS, handshake_board=DeviceId.VCU_BLUETOOTH, **options)


def test_app_password_logs_in_without_a_new_pairing(runtime):  # noqa: F811
    async def check():
        scooter, updates = runtime("Ninebot F3 Pro")
        simulated = f3(stored_password=SAVED_PASSWORD)
        await bring_into_range(scooter, SimulatedGattClient(simulated), NAME)

        data = await poll(scooter)

        assert scooter._authentication_mode == "stored_password_login"
        # 0x5C would overwrite the password the vendor app relies on.
        assert simulated.commands()[:2] == [0x5B, 0x5D]
        assert 0x5C not in simulated.commands()
        assert simulated.stored_password == SAVED_PASSWORD
        assert data.battery_percent == 87
        assert data.distance_left_km == pytest.approx(31.2)
        assert data.odometer_km == pytest.approx(1234.5)
        assert scooter.diagnostics["handshake_board"] == "0x04"
        assert scooter.diagnostics["scooter_has_session_password"] is True

        data = await poll(scooter, times=len(VCU_REGISTERS.optional))
        assert data.battery_voltage_v == pytest.approx(53.52)
        assert data.battery_current_a == pytest.approx(-1.5)
        assert data.battery_power_w == pytest.approx(-80.28)
        assert data.battery_capacity_ah == pytest.approx(9.48)
        assert data.battery_charge_cycles == 12
        assert (data.battery_temperature_1_c, data.battery_temperature_2_c) == (25.0, None)
        assert data.frame_temperature_c == pytest.approx(21.5)
        assert (data.error_flags, data.warning_flags) == (0, 0)
        assert data.serial == NAME
        assert not any(scooter.supports_action(setting) for setting in ("is_lock_on", "work_mode"))
        await scooter.async_shutdown()
    asyncio.run(check())


def test_every_block_is_fetched_with_one_request_like_the_vendor_app(runtime):  # noqa: F811
    async def check():
        scooter, _ = runtime("Ninebot F3")
        simulated = f3(stored_password=SAVED_PASSWORD)
        await bring_into_range(scooter, SimulatedGattClient(simulated), NAME)
        await poll(scooter)
        odometer_reads = [request for request in simulated.requests
                          if (request.target, request.index) == (DeviceId.VCU, 0x62)]
        assert [request.data for request in odometer_reads] == [b"\x04"]
        await scooter.async_shutdown()
    asyncio.run(check())


def test_unknown_password_falls_back_to_pairing_with_the_power_button(runtime):  # noqa: F811
    async def check():
        scooter, _ = runtime("Ninebot F3")
        answer_quickly(scooter)
        simulated = f3(stored_password=bytes(16))
        await bring_into_range(scooter, SimulatedGattClient(simulated), NAME)

        data = await poll(scooter)

        assert scooter._authentication_mode == "stored_key_reconfirmed"
        # The login frames were unreadable for the scooter and left no trace.
        assert simulated.commands()[:3] == [0x5B, 0x5C, 0x5D]
        assert simulated.stored_password == SAVED_PASSWORD
        assert data.battery_percent == 87
        await scooter.async_shutdown()
    asyncio.run(check())


def test_unidentified_ninebot_is_recognized_by_the_board_that_answers(runtime):  # noqa: F811
    async def check():
        scooter, updates = runtime("Automatisch")
        scooter._pairing_completed = False
        answer_quickly(scooter)
        simulated = f3()
        await bring_into_range(scooter, SimulatedGattClient(simulated), NAME)

        data = await poll(scooter)

        # The dashboard address of older scooters stayed silent, board 0x04 answered.
        assert scooter.diagnostics["handshake_board"] == "0x04"
        assert scooter.diagnostics["scooter_has_session_password"] is False
        assert scooter.detected_model == VCU_GENERATION
        assert scooter._authentication_mode == "first_pairing"
        assert simulated.stored_password == SAVED_PASSWORD
        assert data.battery_percent == 87
        assert {"data": {"app_key": "ab" * 16, "paired": True}} in updates
        await scooter.async_shutdown()
    asyncio.run(check())


def test_wrong_ninebot_family_is_corrected_by_the_board_that_answers(runtime):  # noqa: F811
    async def check():
        scooter, _ = runtime("Ninebot Max G2")
        answer_quickly(scooter)
        simulated = f3(stored_password=SAVED_PASSWORD)
        await bring_into_range(scooter, SimulatedGattClient(simulated), NAME)

        data = await poll(scooter)

        assert scooter.model == "Ninebot Max G2", "the saved selection is left alone"
        assert scooter.display_model == VCU_GENERATION
        assert scooter.diagnostics["model_protocol"] == "ninebot_vcu"
        assert scooter._authentication_mode == "stored_password_login"
        assert data.battery_percent == 87
        # Nothing was asked of the ESC or BMS the selected family would have used.
        read_targets = {request.target for request in simulated.requests if request.command == 1}
        assert read_targets <= {DeviceId.VCU, DeviceId.VCU_BATTERY}
        await scooter.async_shutdown()
    asyncio.run(check())


def test_max_g3_without_a_battery_board_still_reports_vehicle_values(runtime):  # noqa: F811
    async def check():
        scooter, _ = runtime("Ninebot Max G3")
        answer_quickly(scooter)
        simulated = SimulatedScooter(NAME, SERIAL, {DeviceId.VCU: F3_BOARDS[DeviceId.VCU]},
                                     handshake_board=DeviceId.VCU_BLUETOOTH, stored_password=SAVED_PASSWORD)
        await bring_into_range(scooter, SimulatedGattClient(simulated), NAME)
        data = await poll(scooter, times=1 + len(VCU_REGISTERS.optional))
        assert (data.battery_percent, data.battery_voltage_v) == (87, None)
        assert data.frame_temperature_c == pytest.approx(21.5)
        assert scooter._session_ready
        await scooter.async_shutdown()
    asyncio.run(check())


@pytest.mark.parametrize("board,index,raw,field,expected", [
    (DeviceId.VCU, 0x55, words(100), "battery_percent", 100),
    (DeviceId.VCU, 0x5F, words(4550), "distance_left_km", 45.5),
    (DeviceId.VCU, 0x62, (7).to_bytes(4, "little"), "odometer_km", 0.7),
    (DeviceId.VCU, 0x6B, words(-35), "frame_temperature_c", -3.5),
    (DeviceId.VCU_BATTERY, 0x8C, words(5352), "battery_voltage_v", 53.52),
    (DeviceId.VCU_BATTERY, 0x8D, words(-6), "battery_current_a", 0.06),
    (DeviceId.VCU_BATTERY, 0x5B, words(948), "battery_capacity_ah", 9.48),
])
def test_vcu_register_decoding(board, index, raw, field, expected):
    data = ScooterData()
    assert apply_packet(data, NinebotPacket(board, DeviceId.PHONE, CMD_READ_ACK, index, raw))
    assert getattr(data, field) == pytest.approx(expected)


def test_implausible_battery_level_is_not_shown():
    data = ScooterData(battery_percent=55)
    assert not apply_packet(data, NinebotPacket(DeviceId.VCU, DeviceId.PHONE, CMD_READ_ACK, 0x55, words(5388)))
    assert data.battery_percent == 55


@pytest.mark.parametrize("model", ["Ninebot F3", "Ninebot F3 Pro", "Ninebot Max G3", VCU_GENERATION])
def test_vcu_models_are_read_only_and_marked_as_unconfirmed(model):
    profile = PROFILES_BY_NAME[model]
    transport = transport_for_family(profile.protocol)
    assert transport.adapter_implemented and transport.registers is VCU_REGISTERS
    assert transport.handshake_boards[0] == DeviceId.VCU_BLUETOOTH
    assert transport.uart is NORDIC_UART and transport.resumes_with_password
    assert not profile.writable_settings and not profile.hardware_tested


def test_serial_as_bluetooth_name_reveals_the_brand_before_connecting():
    assert identify_model(None, NAME).brand == "Segway-Ninebot"
    assert identify_model(None, "N4GEC2110C1234").model == "Ninebot G30D"
    assert identify_model(None, "Kellerflitzer").brand is None


def test_only_the_vcu_bluetooth_module_names_a_generation():
    assert identify_generation(DeviceId.VCU_BLUETOOTH).model == VCU_GENERATION
    assert identify_generation(DeviceId.DASHBOARD) is None


def test_proven_generation_never_replaces_a_xiaomi_selection():
    proven = identify_generation(DeviceId.VCU_BLUETOOTH)
    assert effective_profile("Mi Electric Scooter 1S", proven).name == "Mi Electric Scooter 1S"
    assert effective_profile("Ninebot F3 Pro", proven).name == "Ninebot F3 Pro"
    assert effective_profile("Ninebot G30D", proven).name == VCU_GENERATION
    assert effective_profile("Automatisch", proven).name == VCU_GENERATION
    assert not supports_write("Mi Electric Scooter 1S", proven, "is_lock_on")


def test_xiaomi_scooters_are_never_asked_on_another_board():
    for family, transport in TRANSPORT_PROFILES.items():
        if family.startswith("xiaomi"):
            assert transport.handshake_boards == (DeviceId.DASHBOARD,), family
            assert transport.registers is None and transport.uart in (NORDIC_UART, NINEBOT_UART)
