from source_helpers import parse_source
"""Regression tests for resuming a previously paired BLE129 key in v0.5.0."""
import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from custom_components.ninebot_e_scooters.ninebot_packet import NinebotPacket
from protocol_scope import add_protocol_symbols

SRC = Path(__file__).resolve().parents[2] / 'custom_components/ninebot_e_scooters/coordinator.py'
CL = next(n for n in parse_source(SRC.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'ScooterCoordinator')
METHODS = {n.name: n for n in CL.body if isinstance(n, ast.AsyncFunctionDef)}

class ScooterConnectionError(Exception):
    pass


def _load(name, **values):
    ns = {'NinebotPacket': NinebotPacket, 'asyncio': asyncio,
          'ScooterConnectionError': ScooterConnectionError,
          'make_pair': lambda serial: NinebotPacket(0x3E, 0x21, 0x5D, 0, serial),
          'CMD_PAIR': 0x5D, '_LOGGER': logging.getLogger(__name__), **values}
    node = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), METHODS[name]], type_ignores=[])
    add_protocol_symbols(ns)
    exec(compile(ast.fix_missing_locations(node), str(SRC), 'exec'), ns)
    return ns[name]


def test_existing_key_continues_on_same_gatt_after_short_ack_timeouts():
    src = ast.unparse(METHODS['_async_ensure_session'])
    portion = src[src.index('if self._pairing_completed:'):src.index('self._stage = \'ble129_pairing_5c_5d\'')]
    assert 'range(2)' in portion
    assert 'await self._async_pair_current_session(reuse_stored_key=True)' in portion
    assert 'await self._async_confirm_pairing_5d()' in portion
    assert 'self._app_key' in portion
    assert 'self._pairing_completed = False' not in portion
    assert 'await self._async_disconnect()' not in portion
    assert 'secrets.token_bytes' not in portion


def test_5d_retries_then_acknowledges_on_same_key_and_serial():
    confirm = _load('_async_confirm_pairing_5d')
    sent = []
    key = bytes.fromhex('aa' * 16)
    serial = b'12345678901234'
    async def request(packet, **kwargs):
        sent.append(packet)
        return None if len(sent) < 3 else NinebotPacket(0x21, 0x3E, 0x5D, 1)
    state = SimpleNamespace(_pairing_serial=serial, _app_key=key, _async_crypto_request=request)
    asyncio.run(confirm(state))
    assert [p.command for p in sent] == [0x5D, 0x5D, 0x5D]
    assert [p.data for p in sent] == [serial] * 3
    assert state._app_key == key


def test_5d_absent_raises_without_mutating_saved_key():
    confirm = _load('_async_confirm_pairing_5d')
    key = bytes.fromhex('af' * 16)
    serial = b'12345678901234'
    count = 0
    async def request(packet, **kwargs):
        nonlocal count
        count += 1
        return None
    state = SimpleNamespace(_pairing_serial=serial, _app_key=key, _async_crypto_request=request)
    async def run():
        try:
            await confirm(state)
        except ScooterConnectionError as exc:
            assert '0x5D01' in str(exc)
        else:
            raise AssertionError('missing 0x5D ack accepted')
    asyncio.run(run())
    assert count == 3 and state._app_key == key


def test_saved_key_reconfirmation_prompts_but_does_not_rotate_key():
    class Notifications:
        def __init__(self): self.created = []; self.dismissed = []
        def async_create(self, hass, message, title, notification_id): self.created.append((message, title))
        def async_dismiss(self, hass, notification_id): self.dismissed.append(notification_id)
    notify = Notifications()
    key = bytes.fromhex('ab' * 16)
    entry = SimpleNamespace(entry_id='e1', data={'paired': True, 'app_key': key.hex()})
    updates = []
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=lambda *a, **kw: updates.append(kw)))
    request_commands = []
    async def request(packet, **kw):
        request_commands.append(packet.command)
        return NinebotPacket(0x21, 0x3E, packet.command, 1)
    confirm_called = []
    async def confirm(): confirm_called.append(True)
    state = SimpleNamespace(_app_key=key, _pairing_serial=b'12345678901234',
                            _pairing_completed=True, entry=entry, hass=hass,
                            _async_crypto_request=request, _async_confirm_pairing_5d=confirm)
    run = _load('_async_pair_current_session', persistent_notification=notify,
                STORED_KEY_RECOVERY_TIMEOUT=0.05, PAIRING_TIMEOUT=1.0,
                PAIRING_REPLY_TIMEOUT=0.85, PAIRING_RETRY_PAUSE=0.01, PAIRING_RETRY_INTERVAL=0.01,
                make_ping=lambda k: NinebotPacket(0x3E, 0x21, 0x5C, 0, k), CMD_PING=0x5C)
    asyncio.run(run(state, reuse_stored_key=True))
    assert request_commands == [0x5C]
    assert confirm_called == [True]
    assert state._app_key == key
    assert updates == []
    assert notify.created == [], "An immediate 0x5C01 must not ask for another button press"
    assert notify.dismissed == ['ninebot_e_scooters_pair_e1']


