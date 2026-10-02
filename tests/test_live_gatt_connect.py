from source_helpers import parse_source
"""Regression tests for advertisement-only GATT entry, dedup rearm and crypto base."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "custom_components" / "ninebot_e_scooters" / "coordinator.py"
mod = parse_source(FILE.read_text())
cls = next(node for node in mod.body if isinstance(node, ast.ClassDef) and node.name == "ScooterCoordinator")
methods = {node.name: node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def method_func(name, namespace):
    m = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), methods[name]], type_ignores=[])
    exec(compile(ast.fix_missing_locations(m), str(FILE), "exec"), namespace)
    return namespace[name]


def test_no_mac_cache_lookup_during_gatt_connect():
    ensure = ast.unparse(methods["_async_ensure_session"])
    assert "async_ble_device_from_address" not in ensure
    assert "async_request_active_scan" not in ensure
    assert "self._pending_ble_device" in ensure
    assert "self._pending_ble_device = None" in ensure
    connect = ast.unparse(methods["_async_establish_client"])
    assert "establish_connection(" in connect
    assert "max_attempts=2 if self._pairing_completed else 1" in connect
    assert "DIRECT_GATT_TIMEOUT" in connect


def test_live_advertisement_is_claimed_once_and_cooldown_obeyed():
    ns = {"asyncio": asyncio, "_LOGGER": Mock()}
    on_ad = method_func("async_on_live_advertisement", ns)

    async def run():
        addr = "D8:9B:B1:50:DD:25"
        dev = object()
        info = SimpleNamespace(address=addr, connectable=True, device=dev)
        o = SimpleNamespace(_shutting_down=False, _command_lock=asyncio.Lock(),
                            _client=None, _pairing_failed=False, address=addr,
                            _retry_not_before=0, _pending_ble_device=None,
                            _pending_seen_at=0,
                            async_note_scanner_advertisement=lambda _info: None)
        assert on_ad(o, info) is True
        assert o._pending_ble_device is dev
        assert on_ad(o, info) is False  # no double connect
        o._pending_ble_device = None
        o._retry_not_before = asyncio.get_running_loop().time() + 2
        assert on_ad(o, info) is False  # cooldown not bypassed
        assert o._pending_ble_device is None
    asyncio.run(run())


def test_history_is_rearmed_only_after_cooldown():
    calls = []
    bt = SimpleNamespace(async_clear_advertisement_history=lambda hass, addr: calls.append(addr))
    rearm = method_func("_async_rearm_after_cooldown", {"asyncio": asyncio, "bluetooth": bt, "_LOGGER": Mock()})

    async def run():
        obj = SimpleNamespace(address="D8:9B:B1:50:DD:25", hass=object(),
                              _retry_not_before=asyncio.get_running_loop().time()+0.04,
                              _shutting_down=False, _rearm_task=object())
        await rearm(obj)
        assert calls == [obj.address]
        assert obj._rearm_task is None
    asyncio.run(run())




def test_disconnect_after_failed_gatt_rearms_despite_no_client():
    rearm = Mock()
    disconnect = method_func("_async_disconnect", {"asyncio": asyncio, "BleakError": RuntimeError})
    class Obj:
        _client = None
        _rx_char = None
        _gatt_attempt_active = True
        _session_ready = False
        _crypto = None
        _pending_ble_device = object()
        _packet_queue = None
        _rx_buffer = bytearray(b"junk")
        _rearm_advertisements = rearm
    o = Obj()
    asyncio.run(disconnect(o))
    assert o._pending_ble_device is None
    assert o._gatt_attempt_active is False
    rearm.assert_called_once()


def test_no_history_rearm_when_disconnecting_before_gatt_attempt():
    rearm = Mock()
    disconnect = method_func("_async_disconnect", {"asyncio": asyncio, "BleakError": RuntimeError})
    class Obj:
        _client = None
        _rx_char = None
        _gatt_attempt_active = False
        _session_ready = False
        _crypto = None
        _pending_ble_device = None
        _packet_queue = None
        _rx_buffer = bytearray()
        _rearm_advertisements = rearm
    asyncio.run(disconnect(Obj()))
    rearm.assert_not_called()
