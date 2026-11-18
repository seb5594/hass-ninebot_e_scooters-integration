"""Verify the config-flow pairing: the classic BLE129 handshake orchestration.

bleak and bleak_retry_connector are not installed in this test environment
(they are a runtime-only dependency, satisfied by Home Assistant itself), so
runtime/flow_pairing.py is exercised the same way the rest of this test suite
exercises coordinator code that needs a BLE library: the relevant functions
are extracted from the real source file with ast and executed against a
small, explicit set of fakes, rather than imported as a module.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from protocol_scope import add_protocol_symbols
from source_helpers import parse_source

SRC = Path(__file__).resolve().parents[2] / "custom_components/ninebot_e_scooters/runtime/flow_pairing.py"
TREE = parse_source(SRC.read_text())
NAMES = ("PairingOutcome", "_async_show_pairing_notice", "async_attempt_pairing")
NODES = {
    node.name: node for node in TREE.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in NAMES
}
assert set(NODES) == set(NAMES)
MOD = ast.Module(
    body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *NODES.values()],
    type_ignores=[],
)


class ScooterConnectionError(Exception):
    pass


class BleakError(Exception):
    pass


class Notifications:
    def __init__(self):
        self.created = []
        self.dismissed = []

    def async_create(self, hass, message, title, notification_id):
        self.created.append((title, notification_id))

    def async_dismiss(self, hass, notification_id):
        self.dismissed.append(notification_id)


def _namespace(**overrides):
    ns = {
        "asyncio": asyncio,
        "secrets": __import__("secrets"),
        "dataclass": __import__("dataclasses").dataclass,
        "_LOGGER": __import__("logging").getLogger("flow-pairing-test"),
        "ScooterConnectionError": ScooterConnectionError,
        "BleakError": BleakError,
        "persistent_notification": Notifications(),
        "Any": object,
    }
    add_protocol_symbols(ns)
    exec(compile(ast.fix_missing_locations(MOD), str(SRC), "exec"), ns)
    # Applied after exec: these replace the real, just-defined functions
    # rather than being clobbered by them, since `async_attempt_pairing`
    # resolves these names from this same dict at call time.
    ns.update(overrides)
    return ns


class FakeHandshakeClient:
    def __init__(self):
        self.is_connected = True
        self.disconnected = False

    async def disconnect(self):
        self.disconnected = True
        self.is_connected = False


def _orchestration_namespace(*, connect_ok=True, classic_ok=False):
    connect_calls, classic_calls = [], []
    client = FakeHandshakeClient()

    async def fake_connect(ble_device, device_name):
        connect_calls.append((ble_device, device_name))
        if not connect_ok:
            raise BleakError("no route to the scooter")
        return client

    async def fake_classic(client_, device_name, app_key, hass, notification_id):
        classic_calls.append((device_name, app_key))
        if not classic_ok:
            raise ScooterConnectionError("classic handshake unanswered")

    ns = _namespace(
        _async_connect=fake_connect,
        _async_attempt_classic_pairing=fake_classic,
    )
    return ns, client, connect_calls, classic_calls


def test_attempt_pairing_reports_ble129_and_dismisses_the_notice_on_success():
    ns, client, _connect, classic_calls = _orchestration_namespace(classic_ok=True)
    outcome = asyncio.run(ns["async_attempt_pairing"](object(), object(), "Scooter", "flow-1"))
    assert outcome.protocol == "ble129"
    assert outcome.app_key is not None and outcome.error is None
    assert len(classic_calls) == 1
    assert client.disconnected is True
    assert ns["persistent_notification"].dismissed == ["ninebot_e_scooters_pair_flow-1"]


def test_attempt_pairing_reports_no_protocol_when_the_classic_handshake_fails():
    ns, client, _connect, classic_calls = _orchestration_namespace(classic_ok=False)
    outcome = asyncio.run(ns["async_attempt_pairing"](object(), object(), "Scooter", "flow-2"))
    assert outcome.protocol is None and outcome.app_key is None
    assert "classic handshake" in outcome.error
    assert len(classic_calls) == 1
    assert client.disconnected is True


def test_attempt_pairing_never_tries_a_handshake_when_it_cannot_connect():
    ns, client, connect_calls, classic_calls = _orchestration_namespace(connect_ok=False)
    outcome = asyncio.run(ns["async_attempt_pairing"](object(), object(), "Scooter", "flow-3"))
    assert outcome.protocol is None
    assert len(connect_calls) == 1
    assert classic_calls == []


def test_attempt_pairing_skips_connecting_entirely_without_a_ble_device():
    """A discovered service_info can carry no BLEDevice at all (not
    connectable, or its advertisement already expired); real Home Assistant
    test fixtures model this with device=None."""
    ns, client, connect_calls, classic_calls = _orchestration_namespace(connect_ok=True)
    outcome = asyncio.run(ns["async_attempt_pairing"](object(), None, "Scooter", "flow-4"))
    assert outcome.protocol is None and outcome.app_key is None
    assert connect_calls == [] and classic_calls == []
