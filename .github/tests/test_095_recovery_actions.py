"""Regression checks for verified reconnects and responsive scooter controls."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import logging
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from test_090_reconnect_mode import method
from test_pairing_queue import PKT, ScooterConnectionError, harness
from test_pairing_recovery_045 import setup as pairing_setup
from test_protocol import PACKAGE_PATH, const, load_module, protocol


def test_late_button_confirmation_is_retained_across_unmatched_requests():
    """A button event during register polling must satisfy the next 0x5C."""
    async def check():
        state = harness()
        state._pending_pair_confirmation = PKT.NinebotPacket(0x21, 0x3E, 0x5C, 1)
        calls = []

        async def write(_frame):
            calls.append("write")

        state._async_write_packet = write
        packet = await state._async_crypto_request(PKT.make_ping(bytes(16)),
                                                   expected_commands={0x5C}, timeout=0.01)
        assert packet.index == 1
        assert state._pending_pair_confirmation is None
        assert calls == []

    asyncio.run(check())


def test_pair_notice_appears_after_first_unanswered_ping_only():
    run, state, notices, _updates = pairing_setup()
    sent = []

    async def request(packet, **_kwargs):
        sent.append(packet.command)
        if packet.command == 0x5C:
            return None if len(sent) == 1 else PKT.NinebotPacket(0x21, 0x3E, 0x5C, 1)
        return PKT.NinebotPacket(0x21, 0x3E, 0x5D, 1)

    async def confirm():
        assert (await request(PKT.make_pair(state._pairing_serial))).index == 1

    state._async_crypto_request = request
    state._async_confirm_pairing_5d = confirm
    asyncio.run(run(state, reuse_stored_key=True))
    assert sent == [0x5C, 0x5C, 0x5D]
    assert len(notices.created) == 1
    assert notices.dismissed == ["ninebot_e_scooters_pair_e1"]


def test_lock_action_fresh_gatt_session_precedes_write():
    """The B0 response from the new link is checked before the lock command."""
    reconnect = method("_async_reconnect_for_lock", dict(
        asyncio=asyncio, bluetooth=SimpleNamespace(), time=time,
        MAX_ADVERTISEMENT_AGE=5.0, ScooterConnectionError=ScooterConnectionError,
        make_read=PKT.make_read, TARGET_ESC=0x20, CMD_READ=1, CMD_READ_ACK=4,
        replace=replace, apply_message=protocol.apply_message,
        ScooterMessage=protocol.ScooterMessage, datetime=datetime, UTC=UTC,
    ))
    action = method("async_set_lock", dict(ScooterConnectionError=ScooterConnectionError))
    bt = reconnect.__globals__["bluetooth"]

    async def check():
        events = []
        info = SimpleNamespace(time=asyncio.get_running_loop().time(),
                               connectable=True, device=object(), name="MIScooter5977", rssi=-50)
        bt.async_last_service_info = lambda *_args, **_kw: info
        async def scan(*_args, **_kw):
            events.append("scan")
        bt.async_request_active_scan = scan
        obj = SimpleNamespace(_command_lock=asyncio.Lock(), _shutting_down=False,
                              address="AA:BB", hass=object(), data=protocol.ScooterData(
                                  speed_kmh=0, is_lock_on=False), _setting_read_at={})
        obj.supports_action = lambda _field: True

        async def disconnect():
            events.append("disconnect")
        async def ensure():
            events.append("connect")
        async def request(packet, **_kwargs):
            events.append(f"read:{packet.index:02X}")
            data = bytearray(32)
            data[4] = 0
            return PKT.NinebotPacket(0x20, 0x3E, 1, 0xB0, bytes(data))
        async def write(*args):
            events.append(f"write:{args[0]:02X}")

        obj._async_disconnect = disconnect
        obj._async_ensure_session = ensure
        obj._async_crypto_request = request
        obj._async_write_setting = write
        obj.async_set_updated_data = lambda data: setattr(obj, "data", data)
        obj._async_reconnect_for_lock = lambda: reconnect(obj)
        await action(obj, True)
        assert events == ["disconnect", "connect", "read:B0", "write:70"]

    asyncio.run(check())


def test_mode_write_falls_back_once_and_only_on_stationary_readback():
    write = method("_async_write_setting", dict(
        asyncio=asyncio, replace=replace, datetime=datetime, UTC=UTC,
        NinebotPacket=PKT.NinebotPacket, ScooterMessage=protocol.ScooterMessage,
        apply_message=protocol.apply_message, make_read=PKT.make_read,
        ScooterConnectionError=ScooterConnectionError, SOURCE_PHONE=0x3E,
        TARGET_ESC=0x20, CMD_READ=1, CMD_READ_ACK=4, CMD_WRITE=2,
        CMD_WRITE_NO_REPLY=3, CMD_WRITE_ACK=5, _LOGGER=logging.getLogger("test"),
    ))

    async def check(moving: bool):
        state = SimpleNamespace(control_ready=True, _command_lock=asyncio.Lock(),
                                _setting_read_at={}, data=protocol.ScooterData(speed_kmh=0, work_mode=0))
        state.supports_action = lambda _field: True
        sent = []

        async def request(packet, **_kw):
            sent.append((packet.command, packet.index))
            if packet.index == 0xB0:
                payload = bytearray(32)
                if moving and len([p for p in sent if p[1] == 0xB0]) > 1:
                    payload[10] = 0x64  # The second speed check sees 1 km/h.
                return PKT.NinebotPacket(0x20, 0x3E, 1, 0xB0, bytes(payload))
            if packet.command in (2, 3):
                return None
            return PKT.NinebotPacket(0x20, 0x3E, 1, 0x75,
                                    b"\x02\x00" if (2, 0x75) in sent else b"\x00\x00")

        state._async_crypto_request = request
        state.async_set_updated_data = lambda data: setattr(state, "data", data)
        if moving:
            with pytest.raises(ScooterConnectionError, match="bewegt sich"):
                await write(state, 0x75, 2, 0x75, 2, "work_mode", 2)
            assert (2, 0x75) not in sent
        else:
            await write(state, 0x75, 2, 0x75, 2, "work_mode", 2)
            assert sent.count((3, 0x75)) == 1
            assert sent.count((2, 0x75)) == 1
            assert state.data.work_mode == 2

    asyncio.run(check(False))
    asyncio.run(check(True))


def test_ninebot_families_have_independent_read_only_transport_records():
    transports = load_module("custom_components.ninebot_e_scooters.transport_profiles",
                             PACKAGE_PATH / "transport_profiles.py")
    profiles = load_module("custom_components.ninebot_e_scooters.model_profiles",
                           PACKAGE_PATH / "model_profiles.py")
    assert transports.transport_for_family("xiaomi_ble129").adapter_implemented
    assert transports.transport_for_family("xiaomi_ble129").write_uuid == const.NUS_WRITE_UUID
    for model, version in (("Ninebot ES", "BLE109"), ("Ninebot Max", "BLE114"),
                           ("Ninebot E series", "BLE213"), ("Ninebot F series", "BLE307")):
        profile = profiles.PROFILES_BY_NAME[model]
        record = transports.transport_for_family(profile.protocol)
        assert record is not None and record.adapter_implemented
        assert not profile.writable_settings
        assert not profile.hardware_tested
        assert version in record.documented_ble_versions
        assert not profiles.supports_write(model, profiles.ModelIdentification(model, "Segway-Ninebot", "test"), "is_lock_on")


def test_static_versions_run_once_while_cell_data_gets_fresh_reads():
    extras = (("controller_general_info", 0x20, 0x10, 0x16),
              ("ble_version_esc", 0x20, 0x68, 2),
              ("battery_cell_voltages", 0x22, 0x40, 0x1B))
    read = method("_async_read_registers", dict(
        asyncio=asyncio, datetime=datetime, UTC=UTC, make_read=PKT.make_read,
        TARGET_ESC=0x20, CMD_READ=1, CMD_READ_ACK=4,
        EXTRA_READ_REGISTERS=extras,
        STATIC_EXTRA_NAMES={"controller_general_info", "ble_version_esc"},
        ScooterConnectionError=ScooterConnectionError,
        _LOGGER=logging.getLogger("test"),
    ))

    async def check():
        obj = SimpleNamespace(_initial_telemetry=None, _next_setting_read_at={
            key: 10**12 for key in ("ride_mode", "supplementary", "cruise", "tail_light")},
            _setting_read_at={}, _extra_index=0, _dynamic_extra_index=0,
            _extra_supported={}, _extra_payload_lengths={}, _stage="ready",
            data=None, poll_interval=10)
        registers = []

        async def request(packet, **_kwargs):
            registers.append(packet.index)
            return PKT.NinebotPacket(packet.target, 0x3E, 1, packet.index,
                                    bytes(32 if packet.index == 0xB0 else packet.data[0]))

        obj._async_crypto_request = request
        for _ in range(5):
            await read(obj)
        assert registers.count(0xB0) == 5
        assert registers.count(0x10) == 1
        assert registers.count(0x68) == 1
        assert registers.count(0x40) == 3
        assert obj._extra_index == 3 and obj._dynamic_extra_index == 2

    asyncio.run(check())


def test_untrusted_range_is_disabled_and_lock_is_a_regular_control():
    source = (PACKAGE_PATH / "sensor.py").read_text()
    section = source.split('key="remaining_range"', 1)[1].split("),", 1)[0]
    assert "entity_registry_enabled_default=False" in section
    lock = (PACKAGE_PATH / "lock.py").read_text()
    assert "_attr_entity_category = EntityCategory.CONFIG" not in [
        line.strip() for line in lock.splitlines() if not line.lstrip().startswith("#")
    ]
