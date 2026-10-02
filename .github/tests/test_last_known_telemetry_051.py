from source_helpers import parse_source
"""Verify the cached-reading fix, without requiring a running HA/BlueZ host."""
import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2] / "custom_components/ninebot_e_scooters"


def method(file: str, cls: str, meth: str, *, props=False, extra=None):
    tree = parse_source((ROOT / file).read_text())
    klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    node = next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == meth)
    ns = {"datetime": datetime, "UTC": UTC, "TELEMETRY_CACHE_SECONDS": 600}
    if extra:
        ns.update(extra)
    unit = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(unit), str(ROOT / file), "exec"), ns)
    return ns[meth].fget if isinstance(ns[meth], property) else ns[meth]


def test_cache_only_after_verified_telemetry_and_expires_after_ten_minutes():
    cache = method("coordinator.py", "ScooterCoordinator", "telemetry_cache_valid")
    state = SimpleNamespace(_last_telemetry_at=None)
    assert cache(state) is False
    state._last_telemetry_at = datetime.now(UTC) - timedelta(seconds=9)
    assert cache(state) is True
    state._last_telemetry_at = datetime.now(UTC) - timedelta(minutes=11)
    assert cache(state) is False


def test_stale_when_disconnected_even_if_coordinator_reports_success():
    stale = method("coordinator.py", "ScooterCoordinator", "telemetry_stale")
    state = SimpleNamespace(_last_telemetry_at=datetime.now(UTC), last_update_success=True, _session_ready=True)
    assert stale(state) is False
    state._session_ready = False
    assert stale(state) is True
    state._session_ready = True
    state.last_update_success = False
    assert stale(state) is True


def test_sensor_availability_does_not_follow_last_update_success():
    available = method("sensor.py", "ScooterSensor", "available")
    state = SimpleNamespace(entity_description=SimpleNamespace(key="odometer"),
                            coordinator=SimpleNamespace(telemetry_cache_valid=True, last_update_success=False, data=object()))
    assert available(state) is True
    state.coordinator.telemetry_cache_valid = False
    assert available(state) is True
    state.coordinator.data = None
    assert available(state) is False
    state.entity_description.key = "last_telemetry"
    assert available(state) is True


def test_binary_freshness_indicator_visible_without_telemetry():
    available = method("binary_sensor.py", "ScooterBinarySensor", "available")
    is_on = method("binary_sensor.py", "ScooterBinarySensor", "is_on")
    coordinator = SimpleNamespace(data=None, telemetry_stale=True, telemetry_cache_valid=False)
    state = SimpleNamespace(entity_description=SimpleNamespace(key="telemetry_stale"), coordinator=coordinator)
    assert available(state) is True and is_on(state) is True
    state.entity_description.key = "connected"
    coordinator._client = None
    coordinator._session_ready = False
    assert available(state) is True and is_on(state) is False
    coordinator._client = SimpleNamespace(is_connected=True)
    coordinator._session_ready = True
    assert is_on(state) is True


def test_only_successfully_decoded_registers_mark_last_success():
    tree = parse_source((ROOT / "coordinator.py").read_text())
    cl = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ScooterCoordinator")
    update = next(n for n in cl.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_async_update_data")
    src = ast.unparse(update)
    assert src.index("if decoded_count == 0:") < src.index("self._last_telemetry_at = datetime.now(UTC)")


