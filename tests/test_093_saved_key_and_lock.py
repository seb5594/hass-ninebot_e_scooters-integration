from source_helpers import parse_source
"""Verify saved-key recovery and 1S control-state decoding."""

import ast
import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from test_090_reconnect_mode import method
from test_pairing_queue import PKT, ScooterConnectionError
from test_protocol import protocol
from protocol_scope import add_protocol_symbols


COORD = Path(__file__).resolve().parents[1] / "custom_components/ninebot_e_scooters/coordinator.py"


def _connected_client():
    class Services:
        def __iter__(self):
            return iter(())

        def get_characteristic(self, uuid):
            return SimpleNamespace(uuid=uuid, handle=1, properties=("notify",))

    class Client:
        is_connected = True
        services = Services()

        async def start_notify(self, *_args, **_kwargs):
            return None

    return Client()


def test_5c00_saved_key_5d_proof_skips_button_but_requires_live_telemetry():
    scope = dict(asyncio=asyncio, datetime=datetime, UTC=UTC, PKT=PKT,
                 NinebotCrypto=lambda _name: SimpleNamespace(encrypt=lambda frame: frame),
                 NUS_WRITE_UUID="write", NUS_NOTIFY_UUID="notify", MAX_ADVERTISEMENT_AGE=5,
                 ScooterConnectionError=ScooterConnectionError, BleakError=RuntimeError,
                 CMD_INIT=0x5B, CMD_READ=1, CMD_READ_ACK=4, CMD_PING=0x5C, CMD_PAIR=0x5D,
                 make_init=PKT.make_init, make_read=PKT.make_read,
                 make_ping=PKT.make_ping, make_pair=PKT.make_pair, TARGET_ESC=0x20,
                 _LOGGER=SimpleNamespace(info=lambda *args: None, debug=lambda *args, **kwargs: None))
    ensure = method("_async_ensure_session", scope)

    async def check(allow_confirm: bool, allow_readback: bool):
        obj = SimpleNamespace(_session_ready=False, _client=None,
                              _pending_ble_device=SimpleNamespace(name="MIScooter5977"),
                              _pending_ble_name="MIScooter5977",
                              _pending_seen_at=asyncio.get_running_loop().time(),
                              address="AA:BB", device_name="MIScooter5977",
                              _rx_buffer=bytearray(), _packet_queue=asyncio.Queue(),
                              _next_setting_read_at={}, _pairing_completed=True,
                              _app_key=bytes(range(16)))
        obj._identify_serial = lambda _serial: None
        client = _connected_client()
        obj._async_establish_client = lambda _device: asyncio.sleep(0, result=client)
        commands = []
        manual_prompts = []

        async def request(packet, **_kwargs):
            commands.append(packet.command)
            if packet.command == 0x5B:
                return PKT.NinebotPacket(0x21, 0x3E, 0x5B, 0, bytes(range(30)))
            if packet.command == 0x5C:
                assert packet.data == obj._app_key
                return PKT.NinebotPacket(0x21, 0x3E, 0x5C, 0)
            if packet.command == 0x5D:
                assert packet.data == bytes(range(16, 30))
                return PKT.NinebotPacket(0x21, 0x3E, 0x5D, 1) if allow_confirm else None
            if packet.command == 1:
                if allow_confirm and allow_readback and commands.count(1) == 3:
                    return PKT.NinebotPacket(0x20, 0x3E, 1, 0xB0, bytes(32))
                return None
            raise AssertionError(packet.command)

        async def manual(*, reuse_stored_key):
            manual_prompts.append(reuse_stored_key)

        obj._async_crypto_request = request
        obj._async_pair_current_session = manual
        await ensure(obj)
        if allow_confirm and allow_readback:
            assert commands == [0x5B, 1, 0x5C, 1, 0x5D, 1]
        else:
            assert commands[:5] == [0x5B, 1, 0x5C, 1, 0x5D]
            assert commands.count(0x5D) >= 2
        if allow_confirm and allow_readback:
            assert manual_prompts == []
            assert obj._authentication_mode == "stored_key_5d_verified"
            assert obj._initial_telemetry.index == 0xB0
        else:
            assert manual_prompts == [True]
            assert obj._authentication_mode == "stored_key_reconfirmed"
        assert obj._session_ready
        assert obj._app_key == bytes(range(16))

    asyncio.run(check(True, True))
    asyncio.run(check(True, False))
    asyncio.run(check(False, False))


def test_b0_lock_field_known_states_only():
    """The documented M365 byte never turns an unfamiliar value into unlocked."""
    for status_byte, expected in ((0, False), (2, True), (6, True), (8, None)):
        payload = bytearray(32)
        payload[4] = status_byte
        data = protocol.ScooterData()
        assert protocol.apply_message(data, protocol.ScooterMessage(0x20, 1, 0xB0, bytes(payload), b""))
        assert data.is_lock_on is expected


def test_lock_uses_b0_readback_instead_of_unsupported_b2_status():
    func = method("async_set_lock", {"ScooterConnectionError": ScooterConnectionError})

    async def check():
        calls = []
        obj = SimpleNamespace(data=protocol.ScooterData(is_lock_on=False))
        obj.supports_action = lambda _field: True
        obj._async_reconnect_for_lock = lambda: asyncio.sleep(0)

        async def write(*args):
            calls.append(args)

        obj._async_write_setting = write
        await func(obj, True)
        assert calls == [(0x70, 1, 0xB0, 0x20, "is_lock_on", True)]
        obj.data.is_lock_on = True
        await func(obj, False)
        assert calls[1] == (0x71, 1, 0xB0, 0x20, "is_lock_on", False)

    asyncio.run(check())


def test_lock_write_requires_b0_status_transition():
    """A write alone never claims the scooter has locked."""
    write = method("_async_write_setting", dict(asyncio=asyncio, replace=replace,
                datetime=datetime, UTC=UTC, NinebotPacket=PKT.NinebotPacket,
                ScooterMessage=protocol.ScooterMessage, apply_message=protocol.apply_message,
                make_read=PKT.make_read, ScooterConnectionError=ScooterConnectionError,
                SOURCE_PHONE=0x3E, TARGET_ESC=0x20, CMD_READ=1, CMD_READ_ACK=4,
                CMD_WRITE=2, CMD_WRITE_NO_REPLY=3, CMD_WRITE_ACK=5,
                _LOGGER=SimpleNamespace(info=lambda *args: None)))

    async def check(lock_byte):
        obj = SimpleNamespace(control_ready=True, _command_lock=asyncio.Lock(),
                              _setting_read_at={}, data=protocol.ScooterData(speed_kmh=0, is_lock_on=False))
        obj.supports_action = lambda _field: True
        requests = []

        async def request(packet, **_kwargs):
            requests.append(packet)
            if packet.command == 3:
                return None
            payload = bytearray(32)
            payload[4] = 0 if len(requests) == 1 else lock_byte
            return PKT.NinebotPacket(0x20, 0x3E, 1, 0xB0, bytes(payload))

        obj._async_crypto_request = request
        obj.async_set_updated_data = lambda data: setattr(obj, "data", data)
        if lock_byte == 2:
            await write(obj, 0x70, 1, 0xB0, 0x20, "is_lock_on", True)
            assert obj.data.is_lock_on is True
            assert "is_lock_on" in obj._setting_read_at
        else:
            try:
                await write(obj, 0x70, 1, 0xB0, 0x20, "is_lock_on", True)
            except ScooterConnectionError as err:
                assert "Status nicht bestätigt" in str(err)
            else:
                raise AssertionError("Unrecognized 1S lock status must not be accepted")
            assert obj.data.is_lock_on is False
        assert len([packet for packet in requests if packet.command == 3]) == 1

    asyncio.run(check(2))
    asyncio.run(check(8))


def test_mode_and_kers_get_read_in_same_refresh():
    """A fresh mode reply must not postpone the KERS control for another poll."""
    tree = parse_source(COORD.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ScooterCoordinator")
    read = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_async_read_registers")
    scope = dict(asyncio=asyncio, datetime=datetime, UTC=UTC, PKT=PKT,
                 make_read=PKT.make_read, TARGET_ESC=0x20,
                 CMD_READ=1, CMD_READ_ACK=4, EXTRA_READ_REGISTERS=())
    add_protocol_symbols(scope)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), read], type_ignores=[])), str(COORD), "exec"), scope)

    async def check():
        obj = SimpleNamespace(_initial_telemetry=None, _next_setting_read_at={},
                              _setting_read_at={}, _extra_index=0, data=None,
                              poll_interval=10)
        requested = []

        async def request(packet, **_kwargs):
            requested.append(packet.index)
            if packet.index == 0xB0:
                return PKT.NinebotPacket(0x20, 0x3E, 1, 0xB0, bytes(32))
            if packet.index in (0x75, 0x7B):
                return PKT.NinebotPacket(0x20, 0x3E, 1, packet.index, bytes(packet.data[0]))
            return None

        obj._async_crypto_request = request
        replies = await scope["_async_read_registers"](obj)
        assert 0x75 in requested and 0x7B in requested
        assert 0xB2 not in requested
        assert {packet.index for packet in replies} >= {0xB0, 0x75, 0x7B}

    asyncio.run(check())


def test_settings_show_current_session_state_while_action_remains_guarded():
    tree = parse_source(COORD.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ScooterCoordinator")
    getter = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "setting_fresh")
    scope = {"datetime": datetime, "UTC": UTC}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[getter], type_ignores=[])), str(COORD), "exec"), scope)

    async def check():
        now = datetime.now(UTC)
        obj = SimpleNamespace(_shutting_down=False, _session_ready=True,
                              _client=SimpleNamespace(is_connected=True),
                              _control_session_started_at=now - timedelta(seconds=2),
                              _setting_read_at={"work_mode": now}, poll_interval=10,
                              control_ready=False)
        assert scope["setting_fresh"](obj, "work_mode")
        obj._client.is_connected = False
        assert not scope["setting_fresh"](obj, "work_mode")
        obj._client.is_connected = True
        obj._setting_read_at["work_mode"] = now - timedelta(seconds=3)
        assert not scope["setting_fresh"](obj, "work_mode")

    asyncio.run(check())
