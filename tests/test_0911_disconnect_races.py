from source_helpers import parse_source
"""Exercise a lost GATT link during a BLE129 request and unload."""

import ast
import asyncio
from datetime import UTC, datetime
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_pairing_queue import PKT, ScooterConnectionError, harness
from test_090_reconnect_mode import method


COORD = Path(__file__).resolve().parents[1] / "custom_components/ninebot_e_scooters/coordinator.py"


def test_saved_session_probe_timeout_after_transport_reset_reports_disconnection():
    async def check():
        state = harness()
        crypto = state._crypto
        old_queue = state._packet_queue

        async def write(_payload):
            async def reset_transport():
                await asyncio.sleep(0.002)
                state._crypto = None
                state._client = None
                state._packet_queue = asyncio.Queue()

            asyncio.create_task(reset_transport())

        state._async_write_packet = write
        state._stage = "ble129_saved_session_probe"
        with pytest.raises(ScooterConnectionError, match="link was lost during BLE129 response"):
            await state._async_crypto_request(
                PKT.make_read(0x20, 0xB0, 0x20),
                expected_commands={PKT.CMD_READ, PKT.CMD_READ_ACK},
                timeout=0.01,
                accept_timeout=True,
            )
        assert crypto.message_counter == 2
        assert old_queue is not state._packet_queue

    asyncio.run(check())


def test_link_lost_during_packet_write_never_starts_waiting_on_replaced_queue():
    async def check():
        state = harness()

        async def write(_payload):
            state._crypto = None
            state._client = None
            state._packet_queue = asyncio.Queue()

        state._async_write_packet = write
        with pytest.raises(ScooterConnectionError, match="link was lost during BLE129 write"):
            await state._async_crypto_request(
                PKT.make_read(0x20, 0xB0, 0x20),
                expected_commands={PKT.CMD_READ},
                timeout=0.01,
            )

    asyncio.run(check())


def test_config_entry_unload_waits_until_in_flight_request_finishes():
    tree = parse_source(COORD.read_text())
    klass = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                 and node.name == "ScooterCoordinator")
    shutdown = next(node for node in klass.body if isinstance(node, ast.AsyncFunctionDef)
                    and node.name == "async_shutdown")
    unit = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                            shutdown], type_ignores=[])
    namespace = {"asyncio": asyncio}
    exec(compile(ast.fix_missing_locations(unit), str(COORD), "exec"), namespace)

    async def check():
        lock = asyncio.Lock()
        calls = []

        async def disconnect():
            calls.append("disconnected")

        state = SimpleNamespace(
            _shutting_down=False, data=None, _saved_snapshot=None,
            _rearm_task=None, _command_lock=lock, _async_disconnect=disconnect,
            _packet_queue=asyncio.Queue(),
        )
        async with lock:
            unload = asyncio.create_task(namespace["async_shutdown"](state))
            await asyncio.sleep(0)
            assert state._shutting_down and not calls
            assert state._packet_queue.get_nowait() is None
        await unload
        assert calls == ["disconnected"]

    asyncio.run(check())


def test_connected_translation_is_renamed_without_changing_entity_identity():
    import json

    root = COORD.parent
    de = json.loads((root / "translations/de.json").read_text())
    en = json.loads((root / "translations/en.json").read_text())
    assert de["entity"]["binary_sensor"]["connected"]["name"] == "Verbindung"
    assert en["entity"]["binary_sensor"]["connected"]["name"] == "Connection"
    source = (root / "binary_sensor.py").read_text()
    assert 'key="connected"' in source


def test_sensor_marks_last_known_values_when_pairing_failed():
    tree = parse_source((COORD.parent / "sensor.py").read_text())
    klass = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                 and node.name == "ScooterSensor")
    attributes = next(node for node in klass.body if isinstance(node, ast.FunctionDef)
                      and node.name == "extra_state_attributes")
    unit = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                            attributes], type_ignores=[])
    namespace = {}
    exec(compile(ast.fix_missing_locations(unit), "<cached_sensor_test>", "exec"), namespace)
    timestamp = datetime.now(UTC)
    coordinator = SimpleNamespace(_last_telemetry_at=timestamp, telemetry_stale=True)
    state = SimpleNamespace(entity_description=SimpleNamespace(key="speed"), coordinator=coordinator)
    attributes_for_sensor = namespace["extra_state_attributes"].fget
    assert attributes_for_sensor(state) == {
        "last_live_telemetry": timestamp.isoformat(), "value_is_cached": True,
    }
    coordinator.telemetry_stale = False
    assert attributes_for_sensor(state)["value_is_cached"] is False


def test_optional_read_does_not_hide_an_actual_gatt_disconnection():
    extras = (("optional_test", 0x22, 0x1B, 2),)
    read = method("_async_read_registers", {
        "asyncio": asyncio,
        "datetime": datetime,
        "UTC": UTC,
        "make_read": PKT.make_read,
        "TARGET_ESC": 0x20,
        "CMD_READ": PKT.CMD_READ,
        "CMD_READ_ACK": PKT.CMD_READ_ACK,
        "EXTRA_READ_REGISTERS": extras,
        "STATIC_EXTRA_NAMES": set(),
        "ScooterConnectionError": ScooterConnectionError,
        "_LOGGER": logging.getLogger("test_0911_optional_disconnect"),
    })

    async def check():
        state = SimpleNamespace(
            _legacy_link=None,
            _initial_telemetry=PKT.NinebotPacket(0x20, 0x3E, 0x01, 0xB0, bytes(24)),
            _next_setting_read_at={key: 10**12 for key in
                                   ("ride_mode", "supplementary", "cruise", "tail_light")},
            _setting_read_at={},
            _extra_index=0, _dynamic_extra_index=0,
            _extra_supported={}, _extra_payload_lengths={},
            _stage="ble129_session_ready",
            data=SimpleNamespace(battery_health_percent=90,
                                 battery_manufacture_date="2021-08-17"),
            poll_interval=15,
        )

        async def request(packet, **_kwargs):
            if packet.index == 0x1B:
                state._stage = "gatt_disconnected"
                raise ScooterConnectionError("Scooter GATT link was lost during BLE129 response")
            return None

        state._async_crypto_request = request
        assert len(await read(state)) == 1
        assert state._stage == "gatt_disconnected"

    asyncio.run(check())
