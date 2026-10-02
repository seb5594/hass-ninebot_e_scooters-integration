from source_helpers import parse_source
"""Check BMS date decoding, cache boundaries and retained entity semantics."""

from datetime import UTC, datetime
import asyncio
import ast
from pathlib import Path
import json
from types import SimpleNamespace

from test_protocol import PACKAGE_PATH, ScooterData, apply_message, load_module, protocol
from test_ninebot_crypto import packet_module as packet


state = load_module(
    "custom_components.ninebot_e_scooters.saved_state",
    PACKAGE_PATH / "saved_state.py",
)


def _reply(source: int, payload: bytes) -> protocol.ScooterMessage:
    return protocol.ScooterMessage(
        direction=source, read_write=packet.CMD_READ,
        attribute=packet.Xiaomi1sBmsRegister.MANUFACTURE_DATE,
        payload=payload, raw=b"",
    )


def test_bms_manufacture_date_is_packed_date_not_scooter_date():
    data = ScooterData()
    packed = (21 << 9) | (8 << 5) | 17
    assert apply_message(data, _reply(packet.DeviceId.BMS, packed.to_bytes(2, "little")))
    assert data.battery_manufacture_date == "2021-08-17"
    assert apply_message(data, _reply(packet.DeviceId.BMS, packed.to_bytes(2, "little") + b"\x00\x00\x00\x00"))
    assert data.battery_manufacture_date == "2021-08-17"
    assert not apply_message(data, _reply(packet.DeviceId.ESC, packed.to_bytes(2, "little")))
    assert not apply_message(data, _reply(packet.DeviceId.BMS, b"\x00\x00"))
    assert not apply_message(data, _reply(packet.DeviceId.BMS, ((24 << 9) | (2 << 5) | 30).to_bytes(2, "little")))
    assert not apply_message(data, _reply(packet.DeviceId.BMS, b"\x01"))
    assert data.battery_manufacture_date == "2021-08-17"


def test_saved_readings_restore_without_raw_packets_or_secrets():
    original = ScooterData(
        serial="25700/12345678", speed_kmh=0.0, battery_percent=81,
        battery_health_percent=92, battery_manufacture_date="2021-08-17",
        battery_cell_voltages=(3.85, 3.88), raw_packets=("5aa5secret",),
    )
    saved_at = datetime.now(UTC)
    payload = state.snapshot("AA:BB:CC:DD:EE:FF", original, saved_at)
    assert "raw_packets" not in json.dumps(payload)
    assert "5aa5secret" not in json.dumps(payload)
    restored, when = state.restore(payload, "AA:BB:CC:DD:EE:FF")
    assert when == saved_at
    assert restored == ScooterData(
        serial=original.serial, speed_kmh=0, battery_percent=81,
        battery_health_percent=92, battery_manufacture_date="2021-08-17",
        battery_cell_voltages=(3.85, 3.88),
    )
    assert state.restore(payload, "11:22:33:44:55:66") == (None, None)
    payload["values"]["battery_manufacture_date"] = "tomorrow"
    payload["values"]["serial"] = 12345
    recovered, _ = state.restore(payload, "AA:BB:CC:DD:EE:FF")
    assert recovered.battery_manufacture_date is None and recovered.serial is None


def test_date_diagnostic_and_lock_view_share_no_control_logic():
    sensor = parse_source((PACKAGE_PATH / "sensor.py").read_text())
    date_description = ast.unparse(sensor)
    assert "battery_manufacture_date" in date_description
    assert "SensorDeviceClass.DATE" in date_description
    binary = (PACKAGE_PATH / "binary_sensor.py").read_text()
    assert 'key="connected"' in binary
    assert "registry.async_remove(obsolete)" in binary
    assert json.loads((PACKAGE_PATH / "translations/de.json").read_text())["entity"]["sensor"]["battery_manufacture_date"]["name"] == "Batterie-Herstellungsdatum"


def test_no_button_request_before_successful_5b_reply():
    tree = parse_source((PACKAGE_PATH / "coordinator.py").read_text())
    coordinator = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "ScooterCoordinator")
    method = next(item for item in coordinator.body if isinstance(item, ast.FunctionDef) and item.name == "_show_transport_notice")
    unit = ast.Module(body=[method], type_ignores=[])
    notes = []
    scope = {
        "asyncio": asyncio,
        "persistent_notification": SimpleNamespace(async_create=lambda _hass, message, **kw: notes.append((message, kw))),
    }
    exec(compile(ast.fix_missing_locations(unit), "<notice>", "exec"), scope)

    async def check():
        obj = SimpleNamespace(_last_transport_notice_at=0, _stage="ble129_init_5b",
                              hass=object(), entry=SimpleNamespace(entry_id="test"))
        scope["_show_transport_notice"](obj)
        scope["_show_transport_notice"](obj)
        assert len(notes) == 1
        assert "Bluetooth-Verbindung" in notes[0][1]["title"]
        assert "sobald der Scooter die Initialisierung bestätigt" in notes[0][0]
        assert "jetzt einmal" not in notes[0][0]

    asyncio.run(check())
