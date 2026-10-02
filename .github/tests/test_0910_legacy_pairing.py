"""Exercise M365's separate frame adapter and the dashboard prompt."""

import asyncio
from datetime import UTC, datetime
import logging
import shutil
import subprocess

import pytest

from test_protocol import PACKAGE_PATH, ScooterCommand, ScooterData, load_module, parse_message, protocol
from custom_components.ninebot_e_scooters.ninebot_packet import DeviceId, RegisterReadSize, Xiaomi1sBmsRegister
from custom_components.ninebot_e_scooters.ninebot_packet import NinebotPacket, make_read
from test_090_reconnect_mode import method


legacy = load_module(
    "custom_components.ninebot_e_scooters.legacy_transport",
    PACKAGE_PATH / "legacy_transport.py",
)
models = load_module(
    "custom_components.ninebot_e_scooters.model_profiles",
    PACKAGE_PATH / "model_profiles.py",
)
transports = load_module(
    "custom_components.ninebot_e_scooters.transport_profiles",
    PACKAGE_PATH / "transport_profiles.py",
)


def test_m365_55aa_reads_fragmented_checksum_validated_bms_date():
    async def check():
        sent = []
        adapter = None

        async def write(frame):
            sent.append(frame)
            query = parse_message(frame)
            assert query.direction == DeviceId.BMS
            assert query.attribute == Xiaomi1sBmsRegister.MANUFACTURE_DATE
            assert query.payload == bytes((RegisterReadSize.BMS_MANUFACTURE_DATE,))
            wrong_source = ScooterCommand(0x23, 1, query.attribute, b"\x00\x00").build()
            adapter.on_notification(wrong_source)
            packed = ((21 << 9) | (8 << 5) | 17).to_bytes(2, "little")
            reply = ScooterCommand(0x25, 1, query.attribute, packed + bytes(4)).build()
            invalid_checksum = reply[:-1] + bytes((reply[-1] ^ 0x01,))
            adapter.on_notification(invalid_checksum)
            adapter.on_notification(reply[:4])
            adapter.on_notification(reply[4:])

        adapter = legacy.LegacyM365Link(write)
        reply = await adapter.read(DeviceId.BMS, Xiaomi1sBmsRegister.MANUFACTURE_DATE,
                                   RegisterReadSize.BMS_MANUFACTURE_DATE)
        assert reply is not None and reply.direction == 0x25
        data = ScooterData()
        assert protocol.apply_message(data, reply)
        assert data.battery_manufacture_date == "2021-08-17"
        assert len(sent) == 1

    asyncio.run(check())


def test_m365_legacy_timeout_and_no_setting_writes():
    async def check():
        frames = []

        async def write(frame):
            frames.append(parse_message(frame))

        adapter = legacy.LegacyM365Link(write)
        assert await adapter.read(DeviceId.ESC, 0xB0, 32, timeout=0.005) is None
        assert frames[0].direction == 0x20 and frames[0].read_write == 1
        with pytest.raises(ValueError):
            await adapter.read(DeviceId.DASHBOARD, 0xB0, 32)

    asyncio.run(check())


def test_m365_models_use_distinct_live_read_only_transport_profiles():
    classic = models.identify_model("16133/00015977", "MIScooter5977")
    pro = models.identify_model("21886/00015977", "MIScooter5977")
    assert models.effective_profile(models.AUTO_MODEL, classic).protocol == models.M365_LEGACY
    assert models.effective_profile(models.AUTO_MODEL, pro).protocol == models.M365_PRO_CRYPTO
    assert transports.transport_for_family(models.M365_LEGACY).adapter_implemented
    assert transports.transport_for_family(models.M365_PRO_CRYPTO).documented_ble_versions == ("BLE110", "BLE122")
    for model in (classic, pro):
        assert not models.supports_write(models.AUTO_MODEL, model, "is_lock_on")


def test_unavailable_battery_date_is_retried_after_cooldown():
    extras = (
        ("bms_manufacture_date", DeviceId.BMS, Xiaomi1sBmsRegister.MANUFACTURE_DATE, 6),
        ("esc_error_code", DeviceId.ESC, 0x1B, 2),
    )
    read = method("_async_read_registers", dict(
        asyncio=asyncio, datetime=datetime, UTC=UTC, make_read=make_read,
        TARGET_ESC=DeviceId.ESC, CMD_READ=1, CMD_READ_ACK=4,
        EXTRA_READ_REGISTERS=extras, STATIC_EXTRA_NAMES={"bms_manufacture_date"},
        ScooterConnectionError=RuntimeError, _LOGGER=logging.getLogger("test-date-retry"),
    ))

    async def check():
        from types import SimpleNamespace
        seen = []
        state = SimpleNamespace(
            _initial_telemetry=None, _next_setting_read_at={key: 10**12 for key in
                ("ride_mode", "supplementary", "cruise", "tail_light")},
            _setting_read_at={}, _extra_index=0, _dynamic_extra_index=0,
            _extra_supported={}, _extra_payload_lengths={}, _stage="ready",
            data=ScooterData(battery_health_percent=90), poll_interval=10,
        )

        async def request(packet, **_kwargs):
            seen.append((packet.index, packet.data[0]))
            if packet.index == Xiaomi1sBmsRegister.MANUFACTURE_DATE:
                return None
            return NinebotPacket(packet.target, DeviceId.PHONE, 1, packet.index,
                                 bytes(packet.data[0]))

        state._async_crypto_request = request
        await read(state)
        assert seen[-1] == (Xiaomi1sBmsRegister.MANUFACTURE_DATE, 6)
        await read(state)
        await read(state)
        assert [register for register, _ in seen].count(Xiaomi1sBmsRegister.MANUFACTURE_DATE) == 1
        state._next_setting_read_at["battery_date_retry"] = 0
        await read(state)
        assert [register for register, _ in seen].count(Xiaomi1sBmsRegister.MANUFACTURE_DATE) == 2

    asyncio.run(check())


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_pairing_modal_opens_and_closes_with_ha_notification_stream():
    source = (PACKAGE_PATH / "assets/pairing_dialog.js").read_text()
    script = r'''
const vm = require("vm");
const assert = require("assert");
let handler, opened = 0, currentDialog;
const connection = { connected:true, subscribeMessage(callback, message) {
  assert.equal(message.type, "persistent_notification/subscribe");
  handler = callback;
  return Promise.resolve(() => {});
}};
const document = {
  visibilityState: "visible", body:{append(node){ currentDialog=node; }},
  querySelector() {return {hass:{connection}};}, addEventListener() {},
  createElement(tag) {return {
    tag, style:{}, open:false, append(){}, setAttribute(){},
    addEventListener(name, callback){this[`on_${name}`]=callback;},
    showModal(){this.open=true;opened++;},
    close(){this.open=false;this.on_close?.();}
  };}
};
vm.runInNewContext(process.argv[1], {document, setInterval() {}, Promise});
const id="ninebot_e_scooters_pair_test";
handler({type:"current", notifications:{[id]:{title:"Xiaomi Scooter – Pairing jetzt bestätigen"}}});
assert.equal(opened,1);
handler({type:"updated", notifications:{[id]:{title:"Xiaomi Scooter – Pairing nicht abgeschlossen"}}});
assert.equal(currentDialog.open,false);
handler({type:"updated", notifications:{[id]:{title:"Xiaomi Scooter – Gespeicherten Schlüssel bestätigen"}}});
assert.equal(opened,2);
handler({type:"removed", notifications:{[id]:{}}});
assert.equal(currentDialog.open,false);
'''
    subprocess.run([shutil.which("node"), "-e", script, source], check=True, timeout=5)
