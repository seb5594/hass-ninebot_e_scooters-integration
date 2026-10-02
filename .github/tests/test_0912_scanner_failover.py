from source_helpers import parse_source
"""Keep scanner failover experimental; restore the successful paired GATT path."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

from unittest.mock import Mock

import pytest

from compat_scope import add_compat_symbols
from protocol_scope import add_utility_symbols


COORD = Path(__file__).resolve().parents[2] / "custom_components/ninebot_e_scooters/coordinator.py"
tree = parse_source(COORD.read_text())
klass = next(node for node in tree.body if isinstance(node, ast.ClassDef)
             and node.name == "ScooterCoordinator")
methods = [node for node in klass.body if isinstance(node, ast.FunctionDef)
           and node.name in ("async_note_scanner_advertisement", "async_on_live_advertisement")]
unit = ast.Module(body=[
    ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
    ast.ClassDef(name="Harness", bases=[], keywords=[], body=methods, decorator_list=[]),
], type_ignores=[])
namespace = {
    "asyncio": asyncio,
    "SCANNER_RECENT_SECONDS": 20.0,
    "SCANNER_ALTERNATIVE_MIN_RSSI": -85,
    "_LOGGER": Mock(),
}
exec(compile(ast.fix_missing_locations(unit), str(COORD), "exec"), namespace)


def test_recent_backup_scanner_can_replace_failing_scanner():
    async def check():
        coordinator = namespace["Harness"]()
        coordinator.address = "D8:9B:B1:50:DD:25"
        coordinator._shutting_down = False
        coordinator._client = None
        coordinator._command_lock = asyncio.Lock()
        coordinator._pending_ble_device = None
        coordinator._retry_not_before = 0
        coordinator._scanner_last_seen = {}
        coordinator._scanner_avoid_until = {}
        coordinator._enable_scanner_failover = True
        primary = SimpleNamespace(
            address=coordinator.address, connectable=True, source="proxy-a",
            device=object(), rssi=-50, name="MIScooter5977",
        )
        backup = SimpleNamespace(
            address=coordinator.address, connectable=True, source="hci0",
            device=object(), rssi=-67, name="MIScooter5977",
        )
        coordinator.async_note_scanner_advertisement(backup)
        coordinator._scanner_avoid_until["proxy-a"] = asyncio.get_running_loop().time() + 90
        assert coordinator.async_on_live_advertisement(primary) is False
        assert coordinator.async_on_live_advertisement(backup) is True
        assert coordinator._pending_ble_device is backup.device
        assert coordinator._last_seen_scanner_source == "hci0"

    asyncio.run(check())


def test_alone_or_unreachable_backup_cannot_block_reconnect():
    async def check():
        coordinator = namespace["Harness"]()
        coordinator.address = "D8:9B:B1:50:DD:25"
        coordinator._shutting_down = False
        coordinator._client = None
        coordinator._command_lock = asyncio.Lock()
        coordinator._pending_ble_device = None
        coordinator._retry_not_before = 0
        coordinator._scanner_last_seen = {}
        now = asyncio.get_running_loop().time()
        coordinator._scanner_avoid_until = {"proxy-a": now + 90}
        primary = SimpleNamespace(
            address=coordinator.address, connectable=True, source="proxy-a",
            device=object(), rssi=-55, name="MIScooter5977",
        )
        coordinator._scanner_last_seen["hci0"] = (now - 30, -60)
        assert coordinator.async_on_live_advertisement(primary) is True
        coordinator._pending_ble_device = None
        coordinator._scanner_last_seen["hci0"] = (now, -91)
        assert coordinator.async_on_live_advertisement(primary) is True
        coordinator._pending_ble_device = None
        coordinator._scanner_last_seen["hci0"] = (now, -60)
        coordinator._scanner_avoid_until["hci0"] = now + 90
        assert coordinator.async_on_live_advertisement(primary) is True

    asyncio.run(check())


def test_gatt_failure_marks_scanner_for_an_alternative_on_next_sighting():
    establish_node = next(node for node in klass.body
                          if isinstance(node, ast.AsyncFunctionDef)
                          and node.name == "_async_establish_client")
    source = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        establish_node,
    ], type_ignores=[])

    class FakeBleakError(Exception):
        pass

    async def connect(_client_type, _device, _name, **kwargs):
        assert kwargs["max_attempts"] == 2
        raise FakeBleakError("No connection on this scanner")

    scope = {
        "asyncio": asyncio,
        "establish_connection": connect,
        "BleakClientWithServiceCache": object,
        "BleakError": FakeBleakError,
        "BleakOutOfConnectionSlotsError": type("NoSlots", (Exception,), {}),
        "GATT_RETRY_COOLDOWN": 5.0,
        "GATT_CLEANUP_COOLDOWN": 25.0,
        "DIRECT_GATT_TIMEOUT": 18.0,
        "SCANNER_SOURCE_COOLDOWN": 90.0,
        "_LOGGER": Mock(),
    }
    add_utility_symbols(scope)
    add_compat_symbols(scope)
    exec(compile(ast.fix_missing_locations(source), str(COORD), "exec"), scope)

    async def check():
        now = asyncio.get_running_loop().time()
        state = SimpleNamespace(
            _gatt_attempts=0, _pending_seen_at=now,
            _last_seen_rssi=-60, _last_seen_scanner_source="proxy-a",
            _scanner_avoid_until={}, _gatt_last_failure=None,
            _pairing_completed=True, device_name="MIScooter5977",
            _enable_scanner_failover=True,
        )
        with pytest.raises(FakeBleakError):
            await scope["_async_establish_client"](state, SimpleNamespace(details={}))
        assert state._scanner_avoid_until["proxy-a"] > now
        assert state._gatt_last_failure["scanner_source"] == "proxy-a"

    asyncio.run(check())


def test_default_scanner_selection_does_not_skip_live_primary_advertisement():
    async def check():
        coordinator = namespace["Harness"]()
        coordinator.address = "D8:9B:B1:50:DD:25"
        coordinator._shutting_down = False
        coordinator._client = None
        coordinator._command_lock = asyncio.Lock()
        coordinator._pending_ble_device = None
        coordinator._retry_not_before = 0
        coordinator._scanner_last_seen = {}
        coordinator._scanner_avoid_until = {}
        primary = SimpleNamespace(
            address=coordinator.address, connectable=True, source="proxy-a",
            device=object(), rssi=-50, name="MIScooter5977",
        )
        backup = SimpleNamespace(
            address=coordinator.address, connectable=True, source="hci0",
            device=object(), rssi=-67, name="MIScooter5977",
        )
        coordinator.async_note_scanner_advertisement(backup)
        coordinator._scanner_avoid_until["proxy-a"] = asyncio.get_running_loop().time() + 90
        assert coordinator.async_on_live_advertisement(primary) is True
        assert coordinator._pending_ble_device is primary.device

    asyncio.run(check())


def test_scanner_failover_is_disabled_for_new_coordinators():
    init = next(node for node in klass.body if isinstance(node, ast.FunctionDef)
                and node.name == "__init__")
    assert "self._enable_scanner_failover = False" in ast.unparse(init)
