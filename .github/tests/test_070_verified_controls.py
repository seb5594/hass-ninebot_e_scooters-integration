from source_helpers import parse_source
"""Checks for the 1S write opcode and defensive register decoding."""

import ast
import asyncio
from dataclasses import replace
from datetime import datetime
from protocol_scope import UTC
from pathlib import Path
import struct
from types import SimpleNamespace

from test_protocol import protocol
from test_pairing_queue import PKT
from test_ninebot_crypto import NinebotCrypto
from protocol_scope import add_protocol_symbols
from custom_components.ninebot_e_scooters.sensor_groups import selected_sensor_groups


ROOT = Path(__file__).resolve().parents[2] / "custom_components" / "ninebot_e_scooters"


def test_short_kers_reply_does_not_claim_cruise_or_light():
    data = protocol.ScooterData(is_cruise_on=True, is_tail_light_on=True)
    reply = protocol.ScooterMessage(0x20, 1, 0x7B, b"\x02\x00", b"")
    assert protocol.apply_message(data, reply)
    assert data.kers_mode == 2
    assert data.is_cruise_on is True and data.is_tail_light_on is True


def test_unknown_lock_word_does_not_unlock_a_locked_scooter():
    data = protocol.ScooterData(is_lock_on=True)
    reply = protocol.ScooterMessage(0x20, 1, 0xB2, b"\x00\x08", b"")
    assert not protocol.apply_message(data, reply)
    assert data.is_lock_on is True


def test_1s_write_uses_03_and_waits_for_verified_readback():
    tree = parse_source((ROOT / "coordinator.py").read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "ScooterCoordinator")
    method = next(node for node in cls.body if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == "_async_write_setting")
    module = ast.Module(body=[ast.ImportFrom(module="__future__",
        names=[ast.alias(name="annotations")], level=0),
        ast.ClassDef(name="Harness", bases=[], keywords=[], body=[method],
                     decorator_list=[])], type_ignores=[])
    namespace = dict(asyncio=asyncio, replace=replace, datetime=datetime, UTC=UTC,
        NinebotPacket=PKT.NinebotPacket, ScooterMessage=protocol.ScooterMessage,
        apply_message=protocol.apply_message, make_read=PKT.make_read,
        ScooterConnectionError=RuntimeError, SOURCE_PHONE=0x3E, TARGET_ESC=0x20,
        CMD_READ=1, CMD_READ_ACK=4, CMD_WRITE=2, CMD_WRITE_NO_REPLY=3,
        CMD_WRITE_ACK=5, _LOGGER=SimpleNamespace(info=lambda *args: None))
    add_protocol_symbols(namespace)
    exec(compile(ast.fix_missing_locations(module), "<control-test>", "exec"), namespace)

    async def check():
        obj = namespace["Harness"]()
        obj.control_ready = True
        obj.supports_action = lambda _field: True
        obj._command_lock = asyncio.Lock()
        obj._setting_read_at = {}
        obj.data = protocol.ScooterData(speed_kmh=0, kers_mode=1)
        sent = []
        readback_count = 0
        speed_data = bytearray(24)
        struct.pack_into("<HhHIhhh", speed_data, 8, 84, 0, 0, 2000, 0, 20, 210)

        async def request(packet, **kwargs):
            nonlocal readback_count
            sent.append(packet)
            if packet.command == 3:
                return None
            if packet.index == 0xB0:
                return PKT.NinebotPacket(0x20, 0x3E, 1, 0xB0, bytes(speed_data))
            readback_count += 1
            return (None if readback_count == 1 else
                    PKT.NinebotPacket(0x20, 0x3E, 1, 0x7B, b"\x02\x00"))

        obj._async_crypto_request = request
        obj.async_set_updated_data = lambda data: setattr(obj, "data", data)
        await obj._async_write_setting(0x7B, 2, 0x7B, 6, "kers_mode", 2)
        assert [packet.command for packet in sent] == [1, 3, 1, 1]
        assert obj.data.kers_mode == 2
        assert "kers_mode" in obj._setting_read_at

    asyncio.run(check())


def test_saved_key_reads_before_requesting_pairing_again():
    """A verified 1S ESC reply resumes the GATT session without 0x5C."""
    tree = parse_source((ROOT / "coordinator.py").read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "ScooterCoordinator")
    method = next(node for node in cls.body if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == "_async_ensure_session")
    module = ast.Module(body=[ast.ImportFrom(module="__future__",
        names=[ast.alias(name="annotations")], level=0),
        ast.ClassDef(name="Harness", bases=[], keywords=[], body=[method],
                     decorator_list=[])], type_ignores=[])

    class FakeClient:
        is_connected = True
        class Services:
            def __iter__(self):
                return iter((SimpleNamespace(uuid="uart"),))

            def get_characteristic(self, _uuid):
                return SimpleNamespace(uuid="uart", handle=1, properties=("notify",))

        services = Services()

        async def start_notify(self, *_args, **_kwargs):
            pass

    crypto_names = []

    def make_crypto(name):
        crypto_names.append(name)
        return SimpleNamespace(encrypt=lambda raw: raw)

    namespace = dict(asyncio=asyncio, datetime=datetime, UTC=UTC,
        NinebotCrypto=make_crypto, NUS_WRITE_UUID="write",
        NUS_NOTIFY_UUID="notify", MAX_ADVERTISEMENT_AGE=5,
        ScooterConnectionError=RuntimeError, BleakError=RuntimeError,
        TARGET_ESC=0x20,
        CMD_INIT=0x5B, CMD_READ=1, CMD_READ_ACK=4, CMD_PING=0x5C,
        make_init=PKT.make_init, make_read=PKT.make_read, make_ping=PKT.make_ping,
        _LOGGER=SimpleNamespace(info=lambda *args: None, debug=lambda *args, **kwargs: None))
    add_protocol_symbols(namespace)
    exec(compile(ast.fix_missing_locations(module), "<saved-session-test>", "exec"), namespace)

    async def check():
        obj = namespace["Harness"]()
        obj._session_ready = False
        obj._identify_serial = lambda _serial: None
        obj._client = None
        obj._pending_ble_device = SimpleNamespace(name="MIScooter9999")
        obj._pending_ble_name = "MIScooter9999"
        obj.address = "D8:9B:B1:50:DD:25"
        obj._pending_seen_at = asyncio.get_running_loop().time()
        obj._rx_buffer = bytearray()
        obj._packet_queue = asyncio.Queue()
        obj.device_name = "MIScooter1234"
        obj._extra_index = 0
        obj._extra_supported = {}
        obj._extra_payload_lengths = {}
        obj._next_setting_read_at = {}
        obj._pairing_completed = True
        obj._app_key = bytes(16)
        obj._last_seen_rssi = -40
        obj._async_establish_client = lambda _ble_device: asyncio.sleep(0, result=FakeClient())
        seen = []

        async def request(packet, **_kwargs):
            seen.append(packet.command)
            if packet.command == 0x5B:
                return PKT.NinebotPacket(0x21, 0x3E, 0x5B, 0, bytes(30))
            if packet.command == 1:
                return PKT.NinebotPacket(0x20, 0x3E, 1, 0xB0, bytes(24))
            raise AssertionError("A confirmed session must not request key exchange")

        obj._async_crypto_request = request
        await obj._async_ensure_session()
        assert seen == [0x5B, 1]
        assert obj._session_ready
        assert obj._authentication_mode == "verified_read_after_5b"
        assert obj._initial_telemetry.index == 0xB0
        assert crypto_names == ["MIScooter9999"]
        assert obj._crypto_name_source == "live_advertisement"
        assert not obj._crypto_name_matches_saved

    asyncio.run(check())


def test_saved_pairing_key_does_not_reload_scooter_entry():
    tree = parse_source((ROOT / "__init__.py").read_text())
    method = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == "_async_options_updated")
    module = ast.Module(body=[ast.ImportFrom(module="__future__",
        names=[ast.alias(name="annotations")], level=0), method], type_ignores=[])
    namespace = dict(CONF_POLL_INTERVAL="poll_interval", DEFAULT_POLL_INTERVAL=10,
                     CONF_MODEL="model", MODEL="Mi Electric Scooter 1S",
                     selected_sensor_groups=selected_sensor_groups)
    exec(compile(ast.fix_missing_locations(module), "<options-test>", "exec"), namespace)

    async def check():
        reloaded = []

        async def reload(entry_id):
            reloaded.append(entry_id)

        hass = SimpleNamespace(config_entries=SimpleNamespace(async_reload=reload))
        entry = SimpleNamespace(entry_id="scooter", options={},
            runtime_data=SimpleNamespace(poll_interval=10, model="Mi Electric Scooter 1S"))
        await namespace["_async_options_updated"](hass, entry)
        assert reloaded == []
        entry.options = {"poll_interval": 15}
        await namespace["_async_options_updated"](hass, entry)
        assert reloaded == ["scooter"]

        # Ticking or unticking a sensor group adds or removes entities.
        reloaded.clear()
        entry.options = {"sensor_groups": ["riding"]}
        await namespace["_async_options_updated"](
            hass, entry, applied_sensor_groups=frozenset({"riding"}))
        assert reloaded == []
        await namespace["_async_options_updated"](hass, entry)
        assert reloaded == ["scooter"]

    asyncio.run(check())


def test_nus_29_byte_login_uses_command_writes():
    tree = parse_source((ROOT / "coordinator.py").read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == "ScooterCoordinator")
    method = next(node for node in cls.body if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == "_async_write_packet")
    module = ast.Module(body=[ast.ImportFrom(module="__future__",
        names=[ast.alias(name="annotations")], level=0),
        ast.ClassDef(name="Harness", bases=[], keywords=[], body=[method],
                     decorator_list=[])], type_ignores=[])
    namespace = dict(asyncio=asyncio, BleakError=RuntimeError,
        ScooterConnectionError=RuntimeError,
        _LOGGER=SimpleNamespace(warning=lambda *args: None))
    exec(compile(ast.fix_missing_locations(module), "<write-test>", "exec"), namespace)

    async def check(properties, expected_mode):
        writes = []

        class Client:
            is_connected = True

            async def write_gatt_char(self, _characteristic, data, *, response):
                if response != expected_mode:
                    raise RuntimeError("GATT Protocol Error: Unlikely Error")
                writes.append((bytes(data), response))

        obj = namespace["Harness"]()
        obj._client = Client()
        obj._tx_char = SimpleNamespace(properties=properties)
        await obj._async_write_packet(bytes(range(29)))
        assert [len(data) for data, _response in writes] == [20, 9]
        assert all(response == expected_mode for _data, response in writes)
        assert obj._last_write_mode == ("request" if expected_mode else "command")

    asyncio.run(check(["write", "write-without-response"], False))
    asyncio.run(check(["write"], True))


def test_wrong_live_bluetooth_name_explains_first_crc_failure():
    packet = PKT.NinebotPacket(0x21, 0x3E, 0x5B, 0,
                              bytes(range(16)) + b"12345678901234").pack()
    encrypted = NinebotCrypto("MIScooter9999").encrypt(packet)
    wrong = NinebotCrypto("MIScooter1234")
    assert wrong.decrypt(encrypted) is None
    assert wrong.last_rejection_reason == "first_frame_crc_or_name"
    assert NinebotCrypto("MIScooter9999").decrypt(encrypted) == packet
