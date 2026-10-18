from source_helpers import parse_source
"""0.4.9 regression: Home Assistant's mapping redaction contract and JSON safety."""
import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

COMPONENT = Path(__file__).resolve().parents[2] / 'custom_components' / 'ninebot_e_scooters'
MOD = parse_source((COMPONENT / 'diagnostics.py').read_text())


def home_assistant_redact_data(data, to_redact):
    # Mirrors HA helper's crucial behavior: mapping values MUST be callable.
    from collections.abc import Mapping
    if not isinstance(data, (Mapping, list)):
        return data
    if isinstance(data, list):
        return [home_assistant_redact_data(item, to_redact) for item in data]
    redacted = dict(data)
    for key, value in redacted.items():
        if value is None or (isinstance(value, str) and not value):
            continue
        if key in to_redact:
            if isinstance(to_redact, Mapping):
                redacted[key] = to_redact[key](value)
            else:
                redacted[key] = '**REDACTED**'
        elif isinstance(value, (Mapping, list)):
            redacted[key] = home_assistant_redact_data(value, to_redact)
    return redacted


def load_function():
    future = next(n for n in MOD.body if isinstance(n, ast.ImportFrom) and n.module == '__future__')
    rule = next(n for n in MOD.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'TO_REDACT' for t in n.targets))
    function = next(n for n in MOD.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'async_get_config_entry_diagnostics')
    tree = ast.fix_missing_locations(ast.Module(body=[future, rule, function], type_ignores=[]))
    ns = {'async_redact_data': home_assistant_redact_data, 'CONF_POLL_INTERVAL': 'poll_interval'}
    exec(compile(tree, str(COMPONENT / 'diagnostics.py'), 'exec'), ns)
    return ns['async_get_config_entry_diagnostics'], ns['TO_REDACT']


def fake_entry(runtime_data):
    data = {'address': 'D8:9B:B1:50:DD:25', 'app_key': 'very_secret_key', 'paired': True, 'bluetooth_name':'MIScooter5977'}
    return SimpleNamespace(runtime_data=runtime_data, title='MIScooter5977',data=data,options={'poll_interval':10})


def test_http_500_redaction_regression_and_json():
    get_diag, to_redact = load_function()
    assert not isinstance(to_redact, dict)
    coordinator=SimpleNamespace(_last_services=('6e400001-b5a3-f393-e0a9-e50e24dcca9e',), diagnostics={
        'address':'D8:9B:B1:50:DD:25', 'serial':'PRIVATE_SERIAL', 'app_key':'very_secret_key',
        'stage':'ble129_existing_key_5c','raw_notification_count':3,'message_counter':2,
        'last_error':'Device D8:9B:B1:50:DD:25 timed out',
        'last_notification':'secret_notification_hex','raw_packets':['secret_raw_packets'],
        'data':{'serial':'PRIVATE_SERIAL','battery_percent':87},
    })
    result=asyncio.run(get_diag(None,fake_entry(coordinator)))
    payload=json.dumps(result)
    assert result['legacy_m365_nus_present'] is True
    assert result['coordinator']['stage']=='ble129_existing_key_5c'
    assert result['coordinator']['raw_notification_count']==3
    assert result['coordinator']['data']['battery_percent']==87
    assert result['coordinator']['address']=='**REDACTED**'
    assert result['entry']['data']['app_key']=='**REDACTED**'
    for sensitive in ('very_secret_key','PRIVATE_SERIAL','D8:9B:B1:50:DD:25','secret_notification_hex','secret_raw_packets'):
        assert sensitive not in payload


def test_diagnostics_work_without_runtime_data():
    get_diag,_ = load_function()
    result=asyncio.run(get_diag(None,fake_entry(None)))
    assert result['coordinator']=={}
    assert result['entry']['data']['paired'] is True
    assert result['legacy_m365_nus_present'] is False
    json.dumps(result)


def test_diagnostics_remove_scanner_addresses_in_values_and_dictionary_keys():
    get_diag, _ = load_function()
    private = 'AA:BB:CC:DD:EE:FF'
    coordinator = SimpleNamespace(_last_services=(), diagnostics={
        'device_name': private, 'connected_scanner_source': private,
        'last_bluez_path': '/org/bluez/dev_AA_BB_CC_DD_EE_FF',
        'scanner_short_disconnects': {private: 2},
        'last_failure_snapshot': {'gatt_failure': {'scanner_source': private}},
    })
    result = asyncio.run(get_diag(None, fake_entry(coordinator)))
    payload = json.dumps(result)
    assert private not in payload
    assert 'dev_AA_BB_CC_DD_EE_FF' not in payload
    assert result['coordinator']['scanner_short_disconnects'] == {'scanner_1': 2}
