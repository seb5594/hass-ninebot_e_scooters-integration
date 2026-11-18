from source_helpers import parse_source
"""Regression: setup never touches BLE; connect uses actual live BLEDevice."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

from compat_scope import add_compat_symbols

FILE = Path(__file__).resolve().parents[2] / "custom_components" / "ninebot_e_scooters" / "__init__.py"
source = parse_source(FILE.read_text(encoding="utf-8"))
method = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_setup_entry")
module = ast.Module(
    body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), method],
    type_ignores=[],
)


class CoreState:
    starting = "starting"
    running = "running"


class Bluetooth:
    class BluetoothScanningMode:
        ACTIVE = "active"

    class BluetoothCallbackReplay:
        DISABLED = "disabled"
        NEWEST_FIRST = "newest-first"

    def __init__(self):
        self.callback = None
        self.raw_callback = None
        self.register_kwargs = None
        self.clear_calls = []

    def async_register_callback(self, hass, cb, filters, mode, **kwargs):
        # Mirror HA/habluetooth 2026 scanner interval validation.
        if kwargs.get("scan_interval", 300) < 60.0:
            raise ValueError("scan_interval must be a finite number >= 60s")
        self.callback = cb
        self.register_kwargs = kwargs
        return lambda: None

    def async_register_advertisement_callback(self, hass, cb, address):
        self.raw_callback = cb
        self.raw_address = address
        return lambda: None

    def async_last_service_info(self, hass, address, connectable=True):
        return None

    def async_clear_advertisement_history(self, hass, address):
        self.clear_calls.append(address)


class Coordinator:
    def __init__(self, hass, entry, address, name, poll_interval):
        self.address = address
        self.devices = []
        self._session_ready = False
        self._client = None
        self._stage = "waiting"

    def async_on_live_advertisement(self, info):
        self.devices.append(info.device)
        return True

    def async_note_scanner_advertisement(self, info):
        self.last_scanner = getattr(info, "source", None)

    async def async_restore_saved_data(self):
        self.restored = True

    async def async_request_refresh(self):
        raise AssertionError('live advertisements must not use 10s debounce')

    async def async_refresh(self):
        pass


class Entry:
    def __init__(self):
        self.data = {"address": "AA:BB:CC:DD:EE:FF", "bluetooth_name": "MIScooter5977"}
        self.options = {}
        self.title = "MIScooter5977"
        self.entry_id = "entry1"
        self.tasks = []
        self.unload_callbacks = []

    def async_on_unload(self, cb):
        self.unload_callbacks.append(cb)

    def async_create_background_task(self, hass, coro, name, eager_start):
        coro.close()
        self.tasks.append((name, eager_start))
        return SimpleNamespace(done=lambda: False)


class Bus:
    def __init__(self):
        self.started_callback = None

    def async_listen(self, event_name, cb):
        self.started_callback = cb
        self.registered = True
        self.remove_calls = 0

        def unsubscribe():
            if not self.registered:
                raise ValueError("list.remove(x): x not in list")
            self.registered = False
            self.remove_calls += 1
            self.started_callback = None
        return unsubscribe


async def _test():
    bt = Bluetooth()
    ns = {
        "ScooterCoordinator": Coordinator,
        "CONF_POLL_INTERVAL": "poll_interval",
        "DEFAULT_POLL_INTERVAL": 10,
        "PLATFORMS": ["sensor", "binary_sensor", "switch"],
        "CoreState": CoreState,
        "bluetooth": bt,
        "EVENT_HOMEASSISTANT_STARTED": "homeassistant_started",
        "callback": lambda fn: fn,
        "asyncio": asyncio,
        "_LOGGER": SimpleNamespace(info=lambda *a, **kw: None),
        "async_track_time_interval": lambda hass, cb, interval: lambda: None,
        "ADVERTISEMENT_CHECK_INTERVAL": object(),
        "_recent_connectable_info": lambda info: (
            info is not None and bool(getattr(info, "connectable", False))
            and getattr(info, "device", None) is not None
        ),
    }
    add_compat_symbols(ns)
    exec(compile(ast.fix_missing_locations(module), str(FILE), "exec"), ns)
    entry = Entry()
    hass = SimpleNamespace(
        state=CoreState.starting,
        bus=Bus(),
        config_entries=SimpleNamespace(async_forward_entry_setups=lambda entry, platforms: asyncio.sleep(0)),
    )
    assert await ns["async_setup_entry"](hass, entry) is True
    assert entry.tasks == []
    assert bt.clear_calls == []
    assert bt.callback is None  # No callback or scan registration during boot.
    assert hass.bus.started_callback is not None
    dev = object()
    info = SimpleNamespace(address=entry.data["address"], connectable=True, device=dev)
    # There is no Bluetooth callback available while HA is starting.
    assert bt.callback is None
    assert entry.tasks == []

    hass.state = CoreState.running
    hass.bus.started_callback(None)
    assert hass.bus.registered is False
    assert hass.bus.remove_calls == 1
    for unload in entry.unload_callbacks:
        unload()
        unload()   # teardown is idempotent even if HA consumed the event
    assert hass.bus.remove_calls == 1
    assert entry.tasks == [("ninebot_e_scooters_immediate_scan_entry1", False)]
    assert bt.clear_calls == [entry.data["address"]]
    assert bt.callback is not None
    assert bt.raw_callback is None
    bt.callback(info, None)
    assert len(entry.tasks) == 2
    assert entry.runtime_data.devices == [dev]
    assert entry.tasks[1][1] is False
    assert bt.register_kwargs["scan_interval"] == 60.0
    assert bt.register_kwargs["scan_duration"] == 10.0


def test_no_bluetooth_during_boot_and_passes_live_device():
    asyncio.run(_test())
