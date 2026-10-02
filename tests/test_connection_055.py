from source_helpers import parse_source

import ast
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COORD = ROOT / "custom_components/ninebot_e_scooters/coordinator.py"

def test_direct_fresh_bledevice_connection_strategy():
    src = COORD.read_text()
    tree = parse_source(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ScooterCoordinator")
    fn = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_async_establish_client")
    code = ast.unparse(fn)
    assert "establish_connection(" in code
    assert "max_attempts=2 if self._pairing_completed else 1" in code
    assert "use_services_cache=False" in code
    assert "DIRECT_GATT_TIMEOUT" in code

def test_gatt_cooldown_is_preserved_by_both_exception_handlers():
    src = COORD.read_text()
    constants = (COORD.parent / "runtime/constants.py").read_text()
    assert 'GATT_RETRY_COOLDOWN = 5.0' in constants
    update = ast.unparse(next(node for node in ast.walk(parse_source(src))
                              if isinstance(node, ast.AsyncFunctionDef)
                              and node.name == '_async_update_data'))
    assert "self._stage in ('gatt_connect', 'gatt_disconnected')" in update
    assert 'else 15.0' in update

