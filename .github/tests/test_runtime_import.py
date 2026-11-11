"""Import and exercise the assembled coordinator with Home Assistant doubles.

The doubles provide HA's boundaries; production mixins and codecs are imported
normally. These checks do not require an adapter, BlueZ or a physical scooter.
"""

import asyncio
import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest

from scooter_simulator import SimulatedGattClient, SimulatedScooter, words


@pytest.fixture
def runtime(monkeypatch):
    def module(name, **attributes):
        value = ModuleType(name)
        value.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, value)
        return value

    class HAError(Exception):
        pass

    class BleakError(Exception):
        pass

    class Store:
        def __init__(self, *args, **kwargs):
            self.saved = None

        def async_delay_save(self, callback, delay):
            self.saved = callback()

        async def async_save(self, data):
            self.saved = data

    class Coordinator:
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, hass, logger, **kwargs):
            self.hass = hass
            self.data = None
            self.last_update_success = True

        def async_set_updated_data(self, data):
            self.data = data

        def async_update_listeners(self):
            pass

    async def no_connect(*args, **kwargs):
        raise AssertionError("Tests must not access Bluetooth hardware")

    module("bleak", BleakClient=object)
    module("bleak.exc", BleakError=BleakError)
    module("bleak_retry_connector", BleakClientWithServiceCache=object,
           BleakOutOfConnectionSlotsError=BleakError, establish_connection=no_connect)
    module("homeassistant", __path__=[])
    module("homeassistant.const", MAJOR_VERSION=2026, MINOR_VERSION=9, Platform=SimpleNamespace(
        SENSOR="sensor", BINARY_SENSOR="binary_sensor", SWITCH="switch", LOCK="lock", SELECT="select"))
    notification = module("homeassistant.components.persistent_notification",
                          async_create=lambda *args, **kwargs: None,
                          async_dismiss=lambda *args, **kwargs: None)
    bluetooth = module("homeassistant.components.bluetooth")
    module("homeassistant.components", bluetooth=bluetooth, persistent_notification=notification)
    module("homeassistant.config_entries", ConfigEntry=object, ConfigFlowResult=dict)
    state = SimpleNamespace(running="running")
    module("homeassistant.core", CoreState=state, HomeAssistant=object)
    module("homeassistant.exceptions", HomeAssistantError=HAError)
    registry = module("homeassistant.helpers.device_registry", DeviceInfo=dict,
                      async_get=lambda hass: SimpleNamespace(async_get_device=lambda **kwargs: None))
    issues = module("homeassistant.helpers.issue_registry", async_create_issue=lambda *args, **kwargs: None,
                    async_delete_issue=lambda *args, **kwargs: None, IssueSeverity=SimpleNamespace(WARNING="warning"))
    module("homeassistant.helpers", device_registry=registry, issue_registry=issues)
    module("homeassistant.helpers.entity", Entity=type("Entity", (), {"_name_translation_key": None}))
    module("homeassistant.helpers.redact", async_redact_data=lambda data, keys: data)
    module("homeassistant.helpers.storage", Store=Store)
    module("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=Coordinator, UpdateFailed=HAError)
    # Reload only the HA-facing modules so every dependency uses these doubles.
    names = ["custom_components.ninebot_e_scooters.runtime." + name
             for name in ("errors", "device", "connection", "session", "requests", "telemetry", "controls")]
    names.extend(("custom_components.ninebot_e_scooters.helpers.feedback", "custom_components.ninebot_e_scooters.coordinator"))
    for name in names:
        monkeypatch.delitem(sys.modules, name, raising=False)
    implementation = importlib.import_module(names[-1])
    updates = []
    hass = SimpleNamespace(state=state.running, config_entries=SimpleNamespace(
        async_update_entry=lambda entry, **kwargs: updates.append(kwargs)))

    def create(model):
        entry = SimpleNamespace(data={"app_key": "ab" * 16, "paired": True},
                                options={"model": model}, entry_id="test")
        return implementation.ScooterCoordinator(hass, entry, "AA:BB:CC:DD:EE:FF", "NBScooter1234"), updates
    return create


def test_real_coordinator_imports_and_keeps_saved_credentials(runtime):
    scooter, updates = runtime("Mi Electric Scooter 1S")
    assert scooter._app_key == bytes.fromhex("ab" * 16)
    assert updates == []
    assert scooter._host_id == 0x3E
    assert scooter._packet_queue.maxsize == 128


def test_ninebot_f_session_selects_pc_host_and_decodes_word_telemetry(runtime):
    from custom_components.ninebot_e_scooters.protocols.ninebot.packet import NinebotPacket

    async def check():
        scooter, updates = runtime("Ninebot F40")
        scooter._session_ready = True
        scooter._client = SimpleNamespace(is_connected=True)

        async def connected():
            pass

        async def read():
            return [NinebotPacket(0x22, 0x3D, 4, 0x32, b"\x50\x00")]

        scooter._async_ensure_session = connected
        scooter._async_read_registers = read
        scooter._backoff.failures = 3
        data = await scooter._async_update_data()
        assert data.battery_percent == 80
        assert scooter._host_id == 0x3D
        assert scooter._backoff.failures == 0
        assert not scooter.supports_action("is_lock_on")
        assert updates == []
    asyncio.run(check())


def test_offline_poll_does_not_attempt_gatt_or_rotate_keys(runtime):
    async def check():
        scooter, updates = runtime("Mi Electric Scooter 1S")
        result = await scooter._async_update_data()
        assert result.serial is None
        assert scooter._stage == "waiting_for_live_advertisement"
        assert scooter._gatt_attempts == 0
        assert updates == []
    asyncio.run(check())


@pytest.mark.parametrize("model,name,serial,boards", [
    ("Mi Electric Scooter 1S", "MIScooter1234", b"25700/12345678", {0x20: {0xB0: bytes(32)}}),
    ("Ninebot F40", "NBScooter1234", b"N5GEC2110C1234", {0x22: {0x32: words(80)}}),
])
def test_saved_session_handles_fragmented_encrypted_gatt_without_new_pairing(runtime, model, name, serial, boards):
    async def check():
        scooter, updates = runtime(model)
        scooter.device_name = name
        simulated = SimulatedScooter(name, serial, boards, host_id=scooter._host_id, read_reply_command=1)
        client = SimulatedGattClient(simulated)

        async def establish(device):
            return client

        scooter._async_establish_client = establish
        info = SimpleNamespace(address=scooter.address, name=name, connectable=True,
                               device=SimpleNamespace(name=name), source="test", rssi=-45)
        assert scooter.async_on_live_advertisement(info)
        await scooter._async_ensure_session()
        assert scooter._session_ready
        assert scooter._authentication_mode == "verified_read_after_5b"
        assert simulated.commands() == [0x5B, 1]
        assert scooter._initial_telemetry.target == scooter._host_id
        assert scooter._app_key == bytes.fromhex("ab" * 16)
        assert updates == []
        await scooter.async_shutdown()
        assert not client.is_connected

    asyncio.run(check())
