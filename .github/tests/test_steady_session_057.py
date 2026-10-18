from source_helpers import parse_source
"""Regression checks for the v0.5.7 link lifecycle and unmodified protocol."""
import ast
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
COMP = ROOT / "custom_components" / "ninebot_e_scooters"
COORD = (COMP / "coordinator.py").read_text()
TREE = parse_source(COORD)

def method(name):
    return next(n for n in ast.walk(TREE) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)

def test_native_bluez_timeout_and_no_outer_cancellation():
    s = ast.unparse(method("_async_establish_client"))
    assert "establish_connection(" in s
    assert "asyncio.timeout" not in s
    assert "max_attempts=2 if self._pairing_completed else 1" in s
    assert "DIRECT_GATT_TIMEOUT = 18.0" in (COMP / "runtime/constants.py").read_text()

def test_gatt_retry_not_overwritten_to_15_seconds():
    s = ast.unparse(method("_async_update_data"))
    assert "self._stage in ('gatt_connect', 'gatt_disconnected')" in s
    assert 'else 15.0' in s
    assert "max(self._retry_not_before" in s
    assert "GATT_RETRY_COOLDOWN = 5.0" in (COMP / "runtime/constants.py").read_text()

def test_session_is_reused_and_no_mac_lookup():
    s = ast.unparse(method("_async_ensure_session"))
    assert "self._session_ready and self._client and self._client.is_connected" in s
    assert "async_ble_device_from_address" not in s
    assert "self._pending_ble_device" in s

