from source_helpers import parse_source
"""0.4.8: optional reads do not gate core data; explicit parser additions."""
import ast
import asyncio
from pathlib import Path
import struct
from types import SimpleNamespace

from test_protocol import protocol

ScooterData = protocol.ScooterData
ScooterMessage = protocol.ScooterMessage
apply_message = protocol.apply_message

ROOT = Path(__file__).resolve().parents[2] / 'custom_components' / 'ninebot_e_scooters'
COORD = parse_source((ROOT / 'coordinator.py').read_text())
CLASS = next(n for n in COORD.body if isinstance(n, ast.ClassDef) and n.name == 'ScooterCoordinator')
METHOD = next(n for n in CLASS.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_async_read_registers')




def test_cell_voltages_use_millivolts_and_reject_unphysical_frames():
    data = ScooterData()
    msg = ScooterMessage(direction=0x22, read_write=0x01, attribute=0x40,
                         payload=struct.pack('<10H', *range(3671, 3681)),raw=b'')
    assert apply_message(data, msg) is True
    assert data.battery_cell_voltages[0] == 3.671
    assert data.battery_cell_voltages[9] == 3.68
    assert abs(data.battery_cell_delta_v - 0.009) < 1e-9
    malformed = ScooterMessage(direction=0x22, read_write=0x01, attribute=0x40,
                               payload=struct.pack('<10H', *(40000 for _ in range(10))),raw=b'')
    assert apply_message(data, malformed) is False
    assert data.battery_cell_voltages[0] == 3.671


def test_optional_bms_version_and_kers_do_not_replace_battery_motor():
    data = ScooterData(battery_percent=87, odometer_km=2057.10)
    version = ScooterMessage(direction=0x22,read_write=1,attribute=0x17,
                             payload=struct.pack('<H',0x115),raw=b'')
    assert apply_message(data,version)
    assert data.bms_version == 'V1.1.5'
    flags = ScooterMessage(direction=0x20,read_write=1,attribute=0x7B,
                           payload=struct.pack('<HHH',1,1,2),raw=b'')
    assert apply_message(data,flags)
    assert data.kers_mode == 1
    assert data.is_cruise_on is True
    assert data.is_tail_light_on is True
    assert data.battery_percent == 87
    assert data.odometer_km == 2057.10


def test_listener_is_regular_and_cancel_is_guarded():
    src=(ROOT/'__init__.py').read_text()
    assert 'hass.bus.async_listen_once' not in src
    assert 'hass.bus.async_listen(' in src
    assert 'nonlocal unsub_started' in src
    assert 'unsub_started = None' in src
    assert 'coordinator.async_refresh()' in src
    assert 'coordinator.async_request_refresh()' not in src
