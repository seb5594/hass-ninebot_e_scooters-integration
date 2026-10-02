from source_helpers import parse_source
"""Regression tests for controls added atop the proven 0.5.5 direct GATT transport."""
import ast
import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_protocol import protocol

ROOT = Path(__file__).resolve().parents[1] / 'custom_components' / 'ninebot_e_scooters'




def reply(index, payload, source=0x20):
    return protocol.ScooterMessage(direction=source, read_write=1, attribute=index, payload=payload, raw=b'')


def test_legacy_12x_ble_version_and_invalid_unknown():
    data = protocol.ScooterData()
    assert protocol.apply_message(data, reply(0x68, b'\x29\x01'))
    assert data.ble_version == 'V1.2.9'
    assert not protocol.apply_message(data, reply(0x68, b'\x00\x00'))
    assert data.ble_version == 'V1.2.9'


def test_controller_flags_and_bms_cycle_are_distinct_even_for_same_register():
    data = protocol.ScooterData()
    assert protocol.apply_message(data, reply(0x1B, b'\x05\x00', source=0x20))
    assert protocol.apply_message(data, reply(0x1B, b'\x10\x00', source=0x22))
    assert data.error_flags == 5
    assert data.battery_charge_cycles == 16
    assert protocol.apply_message(data, reply(0x1C, b'\x02\x00'))
    assert data.warning_flags == 2
    assert protocol.apply_message(data, reply(0xB2, b'\x02\x00'))
    assert data.status_flags == 2 and data.is_lock_on is True
    assert protocol.apply_message(data, reply(0xB2, b'\x00\x00'))
    assert data.is_lock_on is False


def test_bms_health_and_status_do_not_guess_values():
    data = protocol.ScooterData()
    assert protocol.apply_message(data, reply(0x30, b'\x40\x00', source=0x22))
    assert data.bms_status_flags == 0x40
    assert protocol.apply_message(data, reply(0x3B, b'\x59\x00', source=0x22))
    assert data.battery_health_percent == 89
    assert not protocol.apply_message(data, reply(0x3B, b'\x65\x00', source=0x22))
    assert data.battery_health_percent == 89


def test_kers_read_support_preserved_and_shows_three_settings():
    data = protocol.ScooterData()
    assert protocol.apply_message(data, reply(0x7B, b'\x02\x00\x01\x00\x02\x00'))
    assert (data.kers_mode, data.is_cruise_on, data.is_tail_light_on) == (2, True, True)
    assert 'Platform.LOCK' in (ROOT / 'const.py').read_text()
    assert 'Platform.SELECT' in (ROOT / 'const.py').read_text()
    assert 'Platform.BUTTON' not in (ROOT / 'const.py').read_text()


def test_native_lock_has_no_optimistic_state_and_one_entity():
    text = (ROOT/'lock.py').read_text()
    tree = parse_source(text)
    cl = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ScooterLock')
    names = {n.name: ast.unparse(n) for n in cl.body if isinstance(n, ast.AsyncFunctionDef)}
    assert 'await self.coordinator.async_set_lock(True)' in names['async_lock']
    assert 'await self.coordinator.async_set_lock(False)' in names['async_unlock']
    assert 'self._attr_is_locked = ' not in text


def test_control_does_not_attempt_reconnection_when_offline():
    tree = parse_source((ROOT/'coordinator.py').read_text())
    cl = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ScooterCoordinator')
    fn = next(n for n in cl.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_async_write_setting')
    source = ast.unparse(fn)
    assert '_async_ensure_session' not in source
    assert 'async with self._command_lock' in source
    assert ('make_read(TARGET_ESC, 176, 32)' in source
            or 'make_read(TARGET_ESC, 0xB0, 0x20)' in source
            or 'make_read(TARGET_ESC, Xiaomi1sEscRegister.FAST_TELEMETRY, RegisterReadSize.FAST_TELEMETRY)' in source)
    assert 'self.async_set_updated_data(updated)' in source
