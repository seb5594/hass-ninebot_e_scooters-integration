"""Import and exercise the assembled coordinator with Home Assistant doubles.

The doubles provide HA's boundaries; production mixins and codecs are imported
normally. These checks do not require an adapter, BlueZ or a physical scooter.
"""

import asyncio
import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest


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
    module("homeassistant.const", Platform=SimpleNamespace(
        SENSOR="sensor", BINARY_SENSOR="binary_sensor", SWITCH="switch", LOCK="lock", SELECT="select"))
    notification = module("homeassistant.components.persistent_notification",
                          async_create=lambda *args, **kwargs: None,
                          async_dismiss=lambda *args, **kwargs: None)
    bluetooth = module("homeassistant.components.bluetooth")
    module("homeassistant.components", bluetooth=bluetooth, persistent_notification=notification)
    module("homeassistant.config_entries", ConfigEntry=object)
    state = SimpleNamespace(running="running")
    module("homeassistant.core", CoreState=state, HomeAssistant=object)
    module("homeassistant.exceptions", HomeAssistantError=HAError)
    registry = module("homeassistant.helpers.device_registry",
                      async_get=lambda hass: SimpleNamespace(async_get_device=lambda **kwargs: None))
    module("homeassistant.helpers", device_registry=registry)
    module("homeassistant.helpers.storage", Store=Store)
    module("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=Coordinator, UpdateFailed=HAError)
    # Reload only the HA-facing modules so every dependency uses these doubles.
    names = ["custom_components.ninebot_e_scooters.runtime." + name
             for name in ("errors", "device", "connection", "session", "requests", "telemetry", "controls")]
    names.append("custom_components.ninebot_e_scooters.coordinator")
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


@pytest.mark.parametrize("model,name,serial", [
    ("Mi Electric Scooter 1S", "MIScooter1234", b"25700/12345678"),
    ("Ninebot F40", "NBScooter1234", b"N5GEC2110C1234"),
])
def test_saved_session_handles_fragmented_encrypted_gatt_without_new_pairing(runtime, model, name, serial):
    from custom_components.ninebot_e_scooters.protocols.ninebot.crypto import NinebotCrypto
    from custom_components.ninebot_e_scooters.protocols.ninebot.packet import NinebotPacket

    async def check():
        scooter, updates = runtime(model)
        scooter.device_name = name
        server = NinebotCrypto(name, host_id=scooter._host_id)
        ble_key = bytes(range(16))
        commands = []

        class Client:
            is_connected = True
            callback = None

            def __init__(self):
                self.buffer = bytearray()
                characteristic = SimpleNamespace(uuid="uart", handle=1,
                                                 properties=("write-without-response", "notify"))
                self.services = SimpleNamespace(get_characteristic=lambda uuid: characteristic)
                self.services = type("Services", (), {
                    "__iter__": lambda self: iter(()),
                    "get_characteristic": lambda self, uuid: characteristic,
                })()

            async def start_notify(self, characteristic, callback, **kwargs):
                self.callback = callback

            async def stop_notify(self, characteristic):
                self.callback = None

            async def disconnect(self):
                self.is_connected = False

            async def write_gatt_char(self, characteristic, fragment, **kwargs):
                self.buffer.extend(fragment)
                if len(self.buffer) < 3 or len(self.buffer) < self.buffer[2] + 13:
                    return
                request = NinebotPacket.unpack(server.decrypt(bytes(self.buffer)))
                self.buffer.clear()
                commands.append(request.command)
                if request.command == 0x5B:
                    response = NinebotPacket(0x21, scooter._host_id, 0x5B, 0, ble_key + serial)
                    encrypted = server.encrypt(response.pack())
                    server._random_ble_data = ble_key
                    server._sha1_key = server._calc_sha1_key(server._name, ble_key)
                else:
                    assert request.command == 1
                    payload = b"\x50\x00" if request.target == 0x22 else bytes(32)
                    response = NinebotPacket(request.target, scooter._host_id, 1, request.index, payload)
                    encrypted = server.encrypt(response.pack())
                # Include a split preamble and arbitrary ATT fragmentation.
                for offset in (0, 1, 8, 20):
                    end = {0: 1, 1: 8, 8: 20, 20: len(encrypted)}[offset]
                    if offset < len(encrypted):
                        self.callback(characteristic, bytearray(encrypted[offset:end]))

        client = Client()

        async def establish(device):
            return client

        scooter._async_establish_client = establish
        info = SimpleNamespace(address=scooter.address, name=name, connectable=True,
                               device=SimpleNamespace(name=name), source="test", rssi=-45)
        assert scooter.async_on_live_advertisement(info)
        await scooter._async_ensure_session()
        assert scooter._session_ready
        assert scooter._authentication_mode == "verified_read_after_5b"
        assert commands == [0x5B, 1]
        assert scooter._initial_telemetry.target == scooter._host_id
        assert scooter._app_key == bytes.fromhex("ab" * 16)
        assert updates == []
        await scooter.async_shutdown()
        assert not client.is_connected

    asyncio.run(check())
