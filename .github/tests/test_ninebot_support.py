"""Behavioral checks for model boundaries and the new read-only adapter."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.ninebot_e_scooters.helpers.discovery import is_scooter_advertisement, needs_explicit_model
from custom_components.ninebot_e_scooters.models.profiles import PROFILES_BY_NAME, identify_model, supports_write
from custom_components.ninebot_e_scooters.models.transports import transport_for_family
from custom_components.ninebot_e_scooters.protocols.data import ScooterData
from custom_components.ninebot_e_scooters.protocols.ninebot.crypto import NinebotCrypto
from custom_components.ninebot_e_scooters.protocols.ninebot.packet import CMD_INIT, CMD_PAIR, CMD_PING, CMD_READ_ACK, DeviceId, NinebotPacket
from custom_components.ninebot_e_scooters.protocols.ninebot.registers import (
    CLASSIC_REGISTERS, REGISTER_BY_ADDRESS, REGISTER_MAPS, apply_packet,
)
from custom_components.ninebot_e_scooters.runtime.ninebot import NinebotMixin
from custom_components.ninebot_e_scooters.helpers.utilities import ConnectionBackoff, parse_app_key
from scooter_simulator import DashboardCrypto

MANIFEST = Path(__file__).parents[2] / "custom_components" / "ninebot_e_scooters" / "manifest.json"


@pytest.mark.parametrize("name", ["MIScooter1234", "Ninebot1234", "NBScooter1234", "Segway1234"])
def test_named_scooters_are_discoverable(name):
    assert is_scooter_advertisement(SimpleNamespace(name=name))


@pytest.mark.parametrize("company", [0x424E, 0x434E])
def test_renamed_scooters_are_found_by_their_ble_module(company):
    renamed = SimpleNamespace(name="Kellerflitzer", manufacturer_data={company: b"\x21\x00"})
    assert is_scooter_advertisement(renamed)
    assert is_scooter_advertisement(SimpleNamespace(name=None, manufacturer_data={company: b""}))


MIBEACON_1S = bytes.fromhex("30581c060125dd50b19bd808")
XIAOMI_UUID = "0000fe95-0000-1000-8000-00805f9b34fb"


def test_renamed_xiaomi_scooter_is_found_by_its_mibeacon_product_id():
    beacon_only = SimpleNamespace(name="Rfxpro2", manufacturer_data={}, service_data={XIAOMI_UUID: MIBEACON_1S})
    assert is_scooter_advertisement(beacon_only)


def test_other_xiaomi_beacons_and_truncated_frames_are_ignored():
    thermometer = bytes.fromhex("5020aa01") + b"\x00" * 8
    assert not is_scooter_advertisement(SimpleNamespace(name="LYWSD03MMC", service_data={XIAOMI_UUID: thermometer}))
    assert not is_scooter_advertisement(SimpleNamespace(name="x", service_data={XIAOMI_UUID: MIBEACON_1S[:3]}))
    assert not is_scooter_advertisement(SimpleNamespace(name="x", service_data={}))


def test_manifest_matches_the_xiaomi_beacon_uuid():
    manifest = json.loads(MANIFEST.read_text())
    assert {"connectable": True, "service_data_uuid": XIAOMI_UUID} in manifest["bluetooth"]


def test_serial_style_names_of_newer_ninebot_generations_are_discoverable():
    assert is_scooter_advertisement(SimpleNamespace(name="1TEFE2517C0419"))
    assert not is_scooter_advertisement(SimpleNamespace(name="1TEFE2517C041"))


def test_uart_alone_cannot_trigger_scooter_pairing():
    assert not is_scooter_advertisement(SimpleNamespace(name="HeartRate", service_uuids=["6e400001-b5a3-f393-e0a9-e50e24dcca9e"]))
    assert not is_scooter_advertisement(SimpleNamespace(name="Kellerflitzer", manufacturer_data={0x004C: b"\x02"}))
    assert needs_explicit_model("NBScooter1234")
    assert not needs_explicit_model("MIScooter1234")


@pytest.mark.parametrize("model", ["Ninebot ES2", "Ninebot G30D", "Ninebot E25", "Ninebot F40"])
def test_ninebot_models_select_implemented_read_only_adapters(model):
    profile = PROFILES_BY_NAME[model]
    assert transport_for_family(profile.protocol).adapter_implemented
    assert not profile.writable_settings
    assert not profile.hardware_tested


def test_ninebot_serial_can_identify_a_g30_variant():
    finding = identify_model("N4GEC2110C1234", "NBScooter1234")
    assert finding.model == "Ninebot G30D"
    assert finding.brand == "Segway-Ninebot"
    assert finding.evidence == "ninebot_serial"


def test_ninebot_brand_evidence_blocks_a_manually_selected_xiaomi_write_profile():
    finding = identify_model(None, "NBScooter1234")
    assert not supports_write("Mi Electric Scooter 1S", finding, "is_lock_on")


@pytest.mark.parametrize("source,index,raw,field,expected", [
    (DeviceId.BMS, 0x32, (80).to_bytes(2, "little"), "battery_percent", 80),
    (DeviceId.BMS, 0x33, (-123).to_bytes(2, "little", signed=True), "battery_current_a", -1.23),
    (DeviceId.BMS, 0x34, (4120).to_bytes(2, "little"), "battery_voltage_v", 41.2),
    (DeviceId.BMS, 0x35, bytes((45, 46)), "battery_temperature_1_c", 25),
    (DeviceId.ESC, 0x29, (120123).to_bytes(4, "little"), "odometer_km", 120.123),
    (DeviceId.ESC, 0x1D, bytes((2, 0)), "is_lock_on", True),
    (DeviceId.ESC, 0x1A, bytes((0x28, 1)), "firmware_version", "V1.2.8"),
])
def test_word_register_decoding(source, index, raw, field, expected):
    data = ScooterData()
    assert apply_packet(data, NinebotPacket(source, DeviceId.PHONE, CMD_READ_ACK, index, raw))
    assert getattr(data, field) == expected


def test_wrong_source_destination_and_incomplete_words_do_not_update_data():
    data = ScooterData(battery_percent=70)
    packet = NinebotPacket(DeviceId.BMS, DeviceId.PHONE, CMD_READ_ACK, 0x32, bytes((80, 0)))
    for invalid in (replace(packet, source=DeviceId.ESC), replace(packet, target=0),
                    replace(packet, data=b"\x50"), replace(packet, data=b"\xff\xff"),
                    replace(packet, command=5)):
        assert not apply_packet(data, invalid)
        assert data.battery_percent == 70


def test_ninebot_tables_are_ordered_and_never_read_controller_password():
    for register_map in REGISTER_MAPS:
        optional = [(int(spec.target), spec.index) for spec in register_map.optional]
        assert optional == sorted(optional)
    every_register = [spec for register_map in REGISTER_MAPS
                      for spec in (*register_map.core, *register_map.optional)]
    # One lookup table decodes both generations, so no address may repeat.
    assert len(REGISTER_BY_ADDRESS) == len(every_register)
    assert all(spec.target != DeviceId.ESC or not (spec.index <= 0x17 < spec.index + spec.words)
               for spec in every_register)


def test_no_register_block_overlaps_its_neighbour():
    for register_map in REGISTER_MAPS:
        claimed = {}
        for spec in (*register_map.core, *register_map.optional):
            for index in range(spec.index, spec.index + spec.words):
                assert claimed.setdefault((spec.target, index), spec) is spec


def test_classic_session_probe_is_the_battery_level():
    probe = CLASSIC_REGISTERS.session_probe
    assert (probe.target, probe.index, probe.fields) == (DeviceId.BMS, 0x32, ("battery_percent",))


def test_block_reads_use_word_offsets_and_discard_partial_blocks():
    async def check(missing_word):
        adapter = NinebotMixin()
        adapter._host_id = DeviceId.PHONE
        requests = []

        async def request(packet, **kwargs):
            requests.append(packet)
            if packet.index == missing_word:
                return None
            return NinebotPacket(packet.target, packet.source, CMD_READ_ACK, packet.index,
                                 bytes((packet.index, 0)))

        adapter._async_crypto_request = request
        result = await adapter._async_read_ninebot_block(REGISTER_BY_ADDRESS[DeviceId.ESC, 0x29])
        assert [packet.index for packet in requests] == [0x29, 0x2A]
        assert all(packet.data == b"\x02" for packet in requests)
        if missing_word is not None:
            assert result is None
        else:
            assert result.data == b"\x29\x00\x2a\x00"
            assert result.index == 0x29
    asyncio.run(check(None))
    asyncio.run(check(0x2A))


@pytest.mark.parametrize("host", [DeviceId.PHONE, DeviceId.PC])
def test_crypto_tracks_host_address_for_ble_and_app_key_transitions(host):
    dashboard = DashboardCrypto("NBScooter1234", host_id=host)
    session = NinebotCrypto("NBScooter1234", host_id=host)

    def to_dashboard(packet):
        assert dashboard.decrypt(session.encrypt(packet.pack())) == packet.pack()

    def to_host(packet):
        assert session.decrypt(dashboard.encrypt(packet.pack())) == packet.pack()

    to_dashboard(NinebotPacket(host, DeviceId.DASHBOARD, CMD_INIT, 0))
    to_host(NinebotPacket(DeviceId.DASHBOARD, host, CMD_INIT, 0, bytes(range(16)) + b"N4GEC2110C1234"))
    # Each step below only opens if both sides moved to the same next key.
    to_dashboard(NinebotPacket(host, DeviceId.DASHBOARD, CMD_PING, 0, bytes(reversed(range(16)))))
    to_host(NinebotPacket(DeviceId.DASHBOARD, host, CMD_PING, 1))
    to_dashboard(NinebotPacket(host, DeviceId.DASHBOARD, CMD_PAIR, 0, b"N4GEC2110C1234"))
    to_host(NinebotPacket(DeviceId.DASHBOARD, host, CMD_PAIR, 1))
    to_dashboard(NinebotPacket(host, DeviceId.BMS, 1, 0x32, b"\x02"))
    to_host(NinebotPacket(DeviceId.BMS, host, CMD_READ_ACK, 0x32, b"\x50\x00"))


def test_a_session_for_the_other_host_address_does_not_follow_the_handshake():
    dashboard = DashboardCrypto("NBScooter1234", host_id=DeviceId.PC)
    session = NinebotCrypto("NBScooter1234", host_id=DeviceId.PHONE)
    challenge = NinebotPacket(DeviceId.DASHBOARD, DeviceId.PC, CMD_INIT, 0, bytes(range(16)) + b"N4GEC2110C1234")
    assert session.decrypt(dashboard.encrypt(challenge.pack())) == challenge.pack()
    reply = NinebotPacket(DeviceId.BMS, DeviceId.PC, CMD_READ_ACK, 0x32, b"\x50\x00")
    assert session.decrypt(dashboard.encrypt(reply.pack())) is None


def test_connection_backoff_grows_only_after_failure_and_resets_after_recovery():
    backoff = ConnectionBackoff()
    assert [backoff.failed(5) for _ in range(7)] == [5, 10, 20, 40, 80, 120, 120]
    backoff.reset()
    assert backoff.failed(25) == 25
    backoff.reset()
    assert [backoff.failed(15, needs_confirmation=True) for _ in range(5)] == [60, 120, 240, 300, 300]


@pytest.mark.parametrize("key", [None, 123, "ff", "g" * 32, "ff" * 17])
def test_invalid_saved_keys_fail_before_ble_io(key):
    with pytest.raises(ValueError):
        parse_app_key(key)


def test_valid_saved_key_is_never_replaced():
    assert parse_app_key("aB" * 16) == bytes.fromhex("ab" * 16)
