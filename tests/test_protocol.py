import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "custom_components" / "ninebot_e_scooters"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Stub only the tiny Home Assistant surface needed by const.py.
ha_const = types.ModuleType("homeassistant.const")


class Platform:
    SENSOR = "sensor"
    BINARY_SENSOR = "binary_sensor"
    SWITCH = "switch"
    LOCK = "lock"
    SELECT = "select"


ha_const.Platform = Platform
sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
sys.modules["homeassistant.const"] = ha_const

package = types.ModuleType("custom_components.ninebot_e_scooters")
package.__path__ = [str(PACKAGE_PATH)]
sys.modules["custom_components.ninebot_e_scooters"] = package

const = load_module(
    "custom_components.ninebot_e_scooters.const",
    PACKAGE_PATH / "const.py",
)
protocol = load_module(
    "custom_components.ninebot_e_scooters.protocol",
    PACKAGE_PATH / "protocol.py",
)

PacketParser = protocol.PacketParser
ScooterCommand = protocol.ScooterCommand
ScooterData = protocol.ScooterData
apply_message = protocol.apply_message
parse_message = protocol.parse_message

MOTOR_TO_MASTER = const.MOTOR_TO_MASTER
READ = const.READ


def test_packet_roundtrip() -> None:
    packet = ScooterCommand(MOTOR_TO_MASTER, READ, 0x25, b"\x02").build()
    parsed = parse_message(packet)

    assert parsed is not None
    assert parsed.direction == MOTOR_TO_MASTER
    assert parsed.attribute == 0x25
    assert parsed.payload == b"\x02"


def test_packet_parser_handles_fragments() -> None:
    packet = ScooterCommand(MOTOR_TO_MASTER, READ, 0x7D, b"\x02").build()
    parser = PacketParser()

    assert parser.feed(packet[:3]) == []

    result = parser.feed(packet[3:])

    assert len(result) == 1
    assert result[0].attribute == 0x7D


def test_motor_info_mapping_matches_m365py_layout() -> None:
    # m365py decodes the telemetry fields starting at payload offset 8.
    payload = (
        b"\x00" * 8
        + b"\x50\x00"       # battery 80 %
        + b"\x2C\x01"       # 3.00 km/h
        + b"\x90\x01"       # 4.00 km/h average
        + b"\x00\x10\x00\x00"  # odometer 4.096 km
        + b"\x2A\x00"       # trip 42 m
        + b"\x78\x00"       # uptime 120 s
        + b"\x18\x01"       # 28.0 C
        + b"\x00" * 8
    )

    packet = ScooterCommand(MOTOR_TO_MASTER, READ, 0xB0, payload).build()
    message = parse_message(packet)

    assert message is not None

    data = ScooterData()
    assert apply_message(data, message)

    assert data.battery_percent == 80
    assert data.speed_kmh == 3.0
    assert data.speed_average_kmh == 4.0
    assert data.odometer_km == 4.096
    assert data.trip_distance_m == 42
    assert data.uptime_s == 120
    assert data.frame_temperature_c == 28.0


def test_battery_info_current_scales_by_100_not_10() -> None:
    import struct

    payload = struct.pack("<HHhHBB", 7500, 81, -345, 3692, 43, 42)
    data = ScooterData()
    message = protocol.ScooterMessage(
        direction=0x22, read_write=0x01, attribute=0x31,
        payload=payload, raw=b"",
    )
    assert apply_message(data, message)
    assert data.battery_current_a == -3.45
    assert data.battery_voltage_v == 36.92
    assert data.battery_percent == 81
