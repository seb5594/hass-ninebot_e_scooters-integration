from source_helpers import parse_source
"""v0.6.0: native ad recovery, BlueZ cleanup backoff, preserved BLE129 wire."""
import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'custom_components' / 'ninebot_e_scooters'
COORD = (PKG / 'coordinator.py').read_text()
INIT = (PKG / '__init__.py').read_text()


def _extract_function(source, name, *, cls=None):
    tree = parse_source(source)
    if cls:
        tree = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == cls)
    node = next(x for x in tree.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x.name == name)
    unit = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), node], type_ignores=[])
    return compile(ast.fix_missing_locations(unit), '<coordinator-regression>', 'exec')


def test_fresh_ad_timestamp_epoch_and_monotonic_replay_rejection():
    ns = {'time': SimpleNamespace(time=lambda: 1_790_000_000., monotonic=lambda: 2000.),
          'MAX_LIVE_ADVERTISEMENT_AGE_SECONDS': 4.0}
    exec(_extract_function(INIT, '_recent_connectable_info'), ns)
    accept = ns['_recent_connectable_info']
    obj = object()
    assert accept(SimpleNamespace(connectable=True, device=obj, time=1998.5))
    assert accept(SimpleNamespace(connectable=True, device=obj, time=1_789_999_998.))
    assert not accept(SimpleNamespace(connectable=True, device=obj, time=1990.))
    assert not accept(SimpleNamespace(connectable=True, device=obj, time=1_789_999_950.))
    assert not accept(SimpleNamespace(connectable=False, device=obj, time=1999.))
    assert not accept(SimpleNamespace(connectable=True, device=None, time=1999.))
    assert not accept(None)


def test_ha_scanner_checked_post_start_for_unchanged_advertisement():
    assert 'async_last_service_info(' in INIT
    assert 'async_track_time_interval(' in INIT
    assert 'ADVERTISEMENT_CHECK_INTERVAL = timedelta(seconds=3)' in INIT
    assert 'eager_start=False' in INIT
    assert 'async_request_refresh()' not in INIT.replace('async_request_refresh() here', '')
    assert 'scan_interval=60.0' in INIT
    assert 'scan_duration=10.0' in INIT
    assert '_activate_bluetooth()' in INIT
    assert 'CoreState.running' in INIT
    assert 'BleakScanner(' not in INIT


def test_failed_bluez_connect_enters_long_cleanup_quarantine():
    class FakeBleakClient:
        def __init__(self, ble_device, disconnected_callback, timeout):
            self.is_connected = False
            assert timeout == 18.0
        async def connect(self):
            raise TimeoutError('Timeout waiting for connect response after 18.0s, disconnect timed out: False, after 20.0s')
    async def fake_establish(client_class, device, name, **kwargs):
        assert client_class is FakeBleakClient
        assert kwargs['max_attempts'] == 1
        assert kwargs['use_services_cache'] is False
        client = client_class(device, kwargs['disconnected_callback'], kwargs['timeout'])
        await client.connect()
        return client
    ns = {
        'asyncio': asyncio, 'BleakClient': FakeBleakClient,
        'BleakClientWithServiceCache': FakeBleakClient,
        'establish_connection': fake_establish,
        'BleakOutOfConnectionSlotsError': type('BleakOutOfConnectionSlotsError', (Exception,), {}),
        'GATT_RETRY_COOLDOWN': 5.0, 'GATT_CLEANUP_COOLDOWN': 25.0,
        'DIRECT_GATT_TIMEOUT': 18.0, 'BleakError': Exception,
        '_LOGGER': logging.getLogger('scooter_060_test'),
    }
    exec(_extract_function(COORD, '_async_establish_client', cls='ScooterCoordinator'), ns)
    func = ns['_async_establish_client']
    async def check():
        state = SimpleNamespace(
            _stage='idle', _gatt_retry_cooldown=5., _gatt_attempts=0,
            _pending_seen_at=asyncio.get_running_loop().time(),
            _last_seen_rssi=-42, _shutting_down=False,
            device_name="MIScooter9999",
            _gatt_successes=0, _gatt_last_duration_s=None,
            _gatt_last_failure=None,
            _pairing_completed=False,
        )
        device = SimpleNamespace(details={'path':'/org/bluez/hci0/dev_test','props':{'AddressType':'random'}})
        with pytest.raises(TimeoutError):
            await func(state, device)
        assert state._stage == 'gatt_connect'
        assert state._gatt_attempts == 1
        assert state._gatt_retry_cooldown == 25.
        assert state._gatt_last_failure['bluez_cleanup_after_connect_timeout'] is True
        assert state._gatt_last_failure['rssi'] == -42
        assert state._gatt_successes == 0
    asyncio.run(check())




def test_last_ble129_failure_snapshot_survives_transport_reset():
    import datetime
    ns = {'datetime': datetime.datetime, 'UTC': datetime.UTC}
    exec(_extract_function(COORD, '_remember_failed_session', cls='ScooterCoordinator'), ns)
    state = SimpleNamespace(
        _stage='ble129_pairing_5c_5d',
        _crypto=SimpleNamespace(message_counter=15),
        _last_reply_command='0x5B/0x01',
        _raw_notification_count=12,
        _rejected_crypto_frames=2,
        _last_rejected_frame_counter16=13,
        _last_frame_issue='integrity_or_counter',
        _gatt_last_failure=None,
    )
    ns['_remember_failed_session'](state, 'ScooterConnectionError')
    state._crypto = None  # transport disconnected, but snapshot must remain
    assert state._last_failure_snapshot['message_counter'] == 15
    assert state._last_failure_snapshot['rejected_crypto_frames'] == 2
    assert state._last_failure_snapshot['last_rejected_frame_counter16'] == 13
    assert 'app_key' not in str(state._last_failure_snapshot)
