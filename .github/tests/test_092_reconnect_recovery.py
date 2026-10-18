from source_helpers import parse_source
"""Recover GATT after unsolicited disconnect without reloading the entry."""

import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

from compat_scope import add_compat_symbols
from protocol_scope import add_utility_symbols
from test_pairing_queue import ScooterConnectionError


COORD = Path(__file__).resolve().parents[2] / "custom_components/ninebot_e_scooters/coordinator.py"
tree = parse_source(COORD.read_text())
coordinator = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ScooterCoordinator")
selected = [node for node in coordinator.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in ("_async_establish_client", "_async_cleanup_disconnected_client",
                              "_async_disconnect", "async_on_live_advertisement",
                              "async_note_scanner_advertisement",
                              "_async_rearm_after_cooldown")]


class FakeClient:
    def __init__(self):
        self.is_connected = True
        self.callback = None
        self.disconnects = 0

    async def disconnect(self):
        self.disconnects += 1
        self.is_connected = False


def test_disconnect_cleanup_precedes_new_client_without_config_entry_reload():
    """The old client must release BlueZ even after is_connected becomes false."""
    clients = []

    async def establish(_type, _device, _name, **kwargs):
        assert kwargs["max_attempts"] == 2
        client = FakeClient()
        client.callback = kwargs["disconnected_callback"]
        clients.append(client)
        return client

    namespace = dict(asyncio=asyncio, establish_connection=establish,
                     BleakClientWithServiceCache=FakeClient,
                     BleakOutOfConnectionSlotsError=type("NoSlots", (Exception,), {}),
                     BleakError=RuntimeError, ScooterConnectionError=ScooterConnectionError,
                     DIRECT_GATT_TIMEOUT=18, GATT_RETRY_COOLDOWN=0.01,
                     GATT_CLEANUP_COOLDOWN=25,
                     SCANNER_RECENT_SECONDS=20, SCANNER_ALTERNATIVE_MIN_RSSI=-85,
                     SCANNER_SOURCE_COOLDOWN=90, SHORT_SESSION_SECONDS=120,
                     _LOGGER=logging.getLogger("scooter_reconnect_test"))
    add_utility_symbols(namespace)
    add_compat_symbols(namespace)
    unit = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                            ast.ClassDef(name="Harness", bases=[], keywords=[], body=selected, decorator_list=[])],
                      type_ignores=[])
    exec(compile(ast.fix_missing_locations(unit), str(COORD), "exec"), namespace)

    async def check():
        obj = namespace["Harness"]()
        obj.address = "D8:9B:B1:50:DD:25"
        obj.hass = object()
        obj.device_name = "MIScooter5977"
        obj._pairing_completed = True
        obj._command_lock = asyncio.Lock()
        obj._shutting_down = False
        obj._pending_seen_at = asyncio.get_running_loop().time()
        obj._pending_ble_device = None
        obj._pending_ble_name = None
        obj._retry_not_before = 0
        obj._stage = "idle"
        obj._gatt_attempts = obj._gatt_successes = obj._disconnect_count = 0
        obj._gatt_retry_cooldown = 0.01
        obj._last_seen_rssi = -55
        obj._last_seen_scanner_source = "test-proxy"
        obj._scanner_last_seen = {}
        obj._scanner_avoid_until = {}
        obj._scanner_short_disconnects = {}
        obj._packet_queue = asyncio.Queue()
        obj._rx_buffer = bytearray(b"junk")
        obj._client = None
        obj._rearm_calls = 0
        obj._rearm_advertisements = lambda: setattr(obj, "_rearm_calls", obj._rearm_calls + 1)
        scheduled = []
        obj.entry = SimpleNamespace(entry_id="scooter", async_create_background_task=lambda _hass, work, _name, **_kw:
                                    scheduled.append(asyncio.create_task(work)))

        first = await obj._async_establish_client(SimpleNamespace(details={}))
        obj._client = first
        obj._session_ready = True
        obj._rx_char = object()
        obj._tx_char = object()
        obj._crypto = object()
        obj._initial_telemetry = None
        obj._authentication_mode = "first_pairing"
        obj._gatt_attempt_active = True
        old_queue = obj._packet_queue

        first.is_connected = False
        first.callback(first)
        assert old_queue.get_nowait() is None
        assert len(scheduled) == 1
        await scheduled.pop()
        assert first.disconnects == 1
        assert obj._client is None and obj._crypto is None
        assert obj._connected_scanner_source == "test-proxy"
        assert obj._last_unexpected_session_duration_s >= 0
        assert obj._rearm_calls >= 2

        await asyncio.sleep(0.015)
        new_device = SimpleNamespace(details={})
        info = SimpleNamespace(address=obj.address, connectable=True, device=new_device,
                               name="MIScooter5977", rssi=-50, source="test-proxy")
        assert obj.async_on_live_advertisement(info)
        assert obj._pending_ble_device is new_device
        second = await obj._async_establish_client(obj._pending_ble_device)
        obj._client = second
        first.callback(first)
        assert obj._client is second and second.is_connected
        assert len(clients) == 2 and obj._gatt_successes == 2
        second.is_connected = False
        second.callback(second)
        assert obj._scanner_short_disconnects == {}
        assert obj._scanner_avoid_until == {}
        await scheduled.pop()

    asyncio.run(check())


def test_recovery_scan_rechecks_deadline_extended_during_scan():
    """A failed connect during the first scan must not strand rearming."""
    scans = []
    history = []
    state = None

    async def scan(_hass, *, duration):
        scans.append(duration)
        if len(scans) == 1:
            state._retry_not_before = asyncio.get_running_loop().time() + 0.01

    namespace = dict(asyncio=asyncio,
                     bluetooth=SimpleNamespace(async_clear_advertisement_history=lambda _h, addr: history.append(addr),
                                               async_request_active_scan=scan),
                     _LOGGER=logging.getLogger("scooter_rearm_test"))
    add_utility_symbols(namespace)
    add_compat_symbols(namespace)
    unit = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                            next(node for node in selected if node.name == "_async_rearm_after_cooldown")], type_ignores=[])
    exec(compile(ast.fix_missing_locations(unit), str(COORD), "exec"), namespace)

    async def check():
        nonlocal state
        state = SimpleNamespace(address="D8:9B:B1:50:DD:25", hass=object(),
                                _shutting_down=False, _rearm_task=object(),
                                _retry_not_before=0, _gatt_last_failure={"kind": "TimeoutError"})
        await namespace["_async_rearm_after_cooldown"](state)
        assert scans == [4.0, 4.0]
        assert history == [state.address, state.address]
        assert state._rearm_task is None

    asyncio.run(check())
