from source_helpers import parse_source
"""Regression coverage for v0.4.7's boot isolation / stored-key retry."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ninebot_e_scooters"


def test_bluetooth_registration_is_only_in_after_start_callback():
    tree = parse_source((ROOT / "__init__.py").read_text())
    setup = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_setup_entry")
    register_owners = []
    for n in ast.walk(setup):
        if isinstance(n, ast.FunctionDef) and n.name == "_activate_bluetooth":
            register_owners.append(ast.unparse(n))
    assert len(register_owners) == 1
    assert "async_register_callback" in register_owners[0]
    assert "async_clear_advertisement_history" in register_owners[0]
    assert "CoreState.running" in register_owners[0]
    assert "async_forward_entry_setups" in ast.unparse(setup)


def test_stored_key_kept_on_missing_ack():
    s = (ROOT / "runtime/session.py").read_text()
    start = s.index("if self._pairing_completed:", s.index("async def _async_ensure_session"))
    end = s.index('self._stage = "ble129_pairing_5c_5d"', start)
    block = s[start:end]
    assert "for attempt in range(2):" in block
    assert "accept_timeout=True" in block
    assert "quiet_timeout=True" in block
    assert "self._app_key" in block
    assert "self._pairing_completed = False" not in block
    assert "secrets.token_bytes" not in block
