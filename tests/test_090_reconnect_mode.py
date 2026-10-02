from source_helpers import parse_source
"""Checks for reconnect authentication, immediate link loss and 1S mode."""

import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_pairing_queue import PKT, ScooterConnectionError, harness
from test_protocol import protocol
from protocol_scope import add_protocol_symbols


COORD = Path(__file__).resolve().parents[1] / "custom_components/ninebot_e_scooters/coordinator.py"
TREE = parse_source(COORD.read_text())
CLS = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "ScooterCoordinator")


def method(name, namespace):
    node = next(node for node in CLS.body if isinstance(node, ast.AsyncFunctionDef) and node.name == name)
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    add_protocol_symbols(namespace)
    exec(compile(ast.fix_missing_locations(module), str(COORD), "exec"), namespace)
    return namespace[name]


def test_controller_mode_accepts_only_known_two_byte_values():
    data = protocol.ScooterData(work_mode=0)
    reply = lambda source, raw: protocol.ScooterMessage(source, 1, 0x75, raw, b"")
    assert protocol.apply_message(data, reply(0x20, b"\x02\x00"))
    assert data.work_mode == 2
    assert not protocol.apply_message(data, reply(0x22, b"\x01\x00"))
    assert not protocol.apply_message(data, reply(0x20, b"\x04\x00"))
    assert data.work_mode == 2


def test_1s_mode_write_requires_live_register_and_verified_readback():
    func = method("async_set_ride_mode", {"MODEL": "1S", "ScooterConnectionError": ScooterConnectionError})

    async def check():
        writes = []
        state = SimpleNamespace(model="1S", data=SimpleNamespace(work_mode=0))
        state.supports_action = lambda _field: state.model == "1S"

        async def write(*args):
            writes.append(args)

        state._async_write_setting = write
        await func(state, 2)
        assert writes == [(0x75, 2, 0x75, 2, "work_mode", 2)]
        state.data.work_mode = None
        with pytest.raises(ScooterConnectionError):
            await func(state, 1)
        state.model = "another scooter"
        with pytest.raises(ScooterConnectionError):
            await func(state, 1)

    asyncio.run(check())


def test_disconnect_marker_aborts_pending_5b_without_six_second_timeout():
    async def check():
        state = harness()

        async def write(_payload):
            state._client.is_connected = False
            state._packet_queue.put_nowait(None)

        state._async_write_packet = write
        with pytest.raises(ScooterConnectionError, match="link was lost"):
            await state._async_crypto_request(PKT.make_init(), expected_commands={0x5B}, timeout=6.0)

    asyncio.run(check())


def test_split_write_stops_when_link_drops_between_fragments():
    func = method("_async_write_packet", {"asyncio": asyncio, "ScooterConnectionError": ScooterConnectionError,
        "BleakError": RuntimeError, "_LOGGER": SimpleNamespace(warning=lambda *args: None)})

    async def check():
        calls = []

        class Client:
            is_connected = True

            async def write_gatt_char(self, _tx, data, *, response):
                calls.append((bytes(data), response))
                self.is_connected = False

        state = SimpleNamespace(_client=Client(), _tx_char=SimpleNamespace(properties=("write", "write-without-response")))
        with pytest.raises(ScooterConnectionError, match="byte 20/29"):
            await func(state, bytes(range(29)))
        assert len(calls) == 1 and calls[0][1] is False

    asyncio.run(check())


def test_5c00_does_not_fake_authenticated_reconnect():
    func = method("_async_ensure_session", dict(
        asyncio=asyncio, PKT=PKT, NinebotCrypto=lambda name: SimpleNamespace(name=name, encrypt=lambda raw: raw),
        NUS_WRITE_UUID="write", NUS_NOTIFY_UUID="notify", MAX_ADVERTISEMENT_AGE=5,
        ScooterConnectionError=ScooterConnectionError, BleakError=RuntimeError,
        CMD_INIT=0x5B, CMD_READ=1, CMD_READ_ACK=4, CMD_PING=0x5C, CMD_PAIR=0x5D,
        make_init=PKT.make_init, make_read=PKT.make_read, make_ping=PKT.make_ping, make_pair=PKT.make_pair,
        TARGET_ESC=0x20, datetime=__import__("datetime").datetime,
        UTC=__import__("datetime").UTC,
        _LOGGER=SimpleNamespace(info=lambda *args: None, debug=lambda *args, **kwargs: None)))

    async def check(accept_read_after_5c00):
        class Client:
            is_connected = True
            services = SimpleNamespace(
                __iter__=lambda self: iter(()),
                get_characteristic=lambda uuid: SimpleNamespace(uuid=uuid, handle=1, properties=("notify",)))

            async def start_notify(self, *_args, **_kwargs):
                pass

        # The client service collection must also be iterable.
        class Services:
            def __iter__(self):
                return iter(())

            def get_characteristic(self, uuid):
                return SimpleNamespace(uuid=uuid, handle=1, properties=("notify",))

        client = Client()
        client.services = Services()
        obj = SimpleNamespace(_session_ready=False, _client=None,
            _pending_ble_device=SimpleNamespace(name="MIScooter"), _pending_ble_name="MIScooter",
            _pending_seen_at=asyncio.get_running_loop().time(), address="AA:BB",
            device_name="MIScooter", _rx_buffer=bytearray(), _packet_queue=asyncio.Queue(),
            _next_setting_read_at={}, _pairing_completed=True, _app_key=bytes(16))
        obj._identify_serial = lambda _serial: None

        reads = []

        async def request(packet, **_kwargs):
            if packet.command == 0x5B:
                return PKT.NinebotPacket(0x21, 0x3E, 0x5B, 0, bytes(30))
            if packet.command == 1:
                reads.append(packet)
                if len(reads) == 2 and accept_read_after_5c00:
                    return PKT.NinebotPacket(0x20, 0x3E, 1, 0xB0, bytes(24))
                return None
            if packet.command == 0x5C:
                return PKT.NinebotPacket(0x21, 0x3E, 0x5C, 0)
            if packet.command == 0x5D:
                return None
            raise AssertionError(packet.command)

        paired = []

        async def pair(*, reuse_stored_key):
            paired.append(reuse_stored_key)
            assert not obj._session_ready

        obj._async_establish_client = lambda _device: asyncio.sleep(0, result=client)
        obj._async_crypto_request = request
        obj._async_pair_current_session = pair
        await func(obj)
        assert paired == ([] if accept_read_after_5c00 else [True])
        assert obj._authentication_mode == (
            "verified_read_after_5c00" if accept_read_after_5c00 else "stored_key_reconfirmed"
        )

    asyncio.run(check(False))
    asyncio.run(check(True))


def test_connection_slot_exhaustion_gets_separate_cooldown():
    class SlotsUnavailable(Exception):
        pass

    async def connect(*_args, **_kwargs):
        raise SlotsUnavailable("No backend with an available connection slot")

    func = method("_async_establish_client", dict(asyncio=asyncio,
        establish_connection=connect, BleakClientWithServiceCache=object,
        BleakOutOfConnectionSlotsError=SlotsUnavailable,
        DIRECT_GATT_TIMEOUT=18.0, GATT_RETRY_COOLDOWN=5.0,
        GATT_CLEANUP_COOLDOWN=25.0, BleakError=RuntimeError,
        _LOGGER=logging.getLogger("test_scooter_slots")))

    async def check():
        state = SimpleNamespace(_stage="idle", _gatt_retry_cooldown=5.0,
            _gatt_attempts=0, _pending_seen_at=asyncio.get_running_loop().time(),
            _last_seen_rssi=-60, _gatt_last_failure=None, device_name="MIScooter",
            _pairing_completed=True)
        with pytest.raises(SlotsUnavailable):
            await func(state, SimpleNamespace(details={}))
        assert state._gatt_retry_cooldown == 25.0
        assert state._gatt_last_failure["connection_slots_exhausted"] is True

    asyncio.run(check())
