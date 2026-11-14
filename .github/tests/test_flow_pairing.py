"""Verify the config-flow pairing fallback: its handshake order and its
MIoT elliptic GATT choreography.

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

from cryptography.exceptions import InvalidTag

from protocol_scope import add_protocol_symbols
from source_helpers import parse_source
from test_protocol import load_module

miot = load_module("protocols.miot_elliptic")

SRC = Path(__file__).resolve().parents[2] / "custom_components/ninebot_e_scooters/runtime/flow_pairing.py"
TREE = parse_source(SRC.read_text())
NAMES = ("PairingOutcome", "_async_show_pairing_notice", "_async_attempt_miot_elliptic_pairing", "async_attempt_pairing")
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
        "InvalidTag": InvalidTag,
        "persistent_notification": Notifications(),
        "MIOT_ELLIPTIC_PAIRING_CHARACTERISTIC": miot.MIOT_ELLIPTIC_PAIRING_CHARACTERISTIC,
        "MIOT_PAIR_REQ": miot.MIOT_PAIR_REQ,
        "MIOT_PAIR_REQ_OK": miot.MIOT_PAIR_REQ_OK,
        "MIOT_PAIR_CHAL_1": miot.MIOT_PAIR_CHAL_1,
        "MIOT_PAIR_CHAL_2": miot.MIOT_PAIR_CHAL_2,
        "MIOT_PAIR_EC_START": miot.MIOT_PAIR_EC_START,
        "MIOT_PAIR_EC_END": miot.MIOT_PAIR_EC_END,
        "MIOT_PAIR_SOL_ACK": miot.MIOT_PAIR_SOL_ACK,
        "MIOT_PAIR_OK": miot.MIOT_PAIR_OK,
        "MIOT_PAIR_OK_ACK": miot.MIOT_PAIR_OK_ACK,
        "miot_elliptic_fragment": miot.miot_elliptic_fragment,
        "miot_elliptic_generate_keypair": miot.miot_elliptic_generate_keypair,
        "miot_elliptic_load_peer_point": miot.miot_elliptic_load_peer_point,
        "miot_elliptic_public_point": miot.miot_elliptic_public_point,
        "miot_elliptic_pairing_response": miot.miot_elliptic_pairing_response,
        "miot_elliptic_derive_pairing_keys": miot.miot_elliptic_derive_pairing_keys,
        "miot_elliptic_shared_secret": miot.miot_elliptic_shared_secret,
        "MIOT_ELLIPTIC_PAIRING_WINDOW": 0.2,
        "MIOT_ELLIPTIC_STEP_TIMEOUT": 0.2,
        "Any": object,
    }
    add_protocol_symbols(ns)
    exec(compile(ast.fix_missing_locations(MOD), str(SRC), "exec"), ns)
    # Applied after exec: these replace the real, just-defined functions
    # rather than being clobbered by them, since `async_attempt_pairing`
    # resolves these names from this same dict at call time.
    ns.update(overrides)
    return ns


class FakeCharacteristic:
    def __init__(self, uuid):
        self.uuid = uuid


class FakeServices:
    def __init__(self, characteristic):
        self._characteristic = characteristic

    def get_characteristic(self, uuid):
        return self._characteristic if uuid == self._characteristic.uuid else None


class FakeMiotClient:
    """A scooter that answers the MIoT elliptic pairing characteristic.

    `script` maps a sent frame's exact bytes to the reply frame(s) it
    triggers; the device's own public key is generated once per instance so
    the exchange is cryptographically real on the device side too.
    """

    def __init__(self, scripted_replies):
        self.is_connected = True
        self.services = FakeServices(FakeCharacteristic(miot.MIOT_ELLIPTIC_PAIRING_CHARACTERISTIC))
        self._handler = None
        self._scripted_replies = scripted_replies
        self.writes: list[bytes] = []

    async def start_notify(self, _characteristic, handler):
        self._handler = handler

    async def stop_notify(self, _characteristic):
        self._handler = None

    async def write_gatt_char(self, _characteristic, data, response=False):
        self.writes.append(bytes(data))
        for reply in self._scripted_replies(bytes(data)):
            self._handler(None, bytearray(reply))


def _device_public_key_fragments():
    device_key = miot.miot_elliptic_generate_keypair()
    point = miot.miot_elliptic_public_point(device_key)
    return device_key, miot.miot_elliptic_fragment(point)


def _full_script(device_key, device_fragments):
    """A complete, well-behaved scripted exchange for one pairing attempt.

    Mirrors the real order _async_attempt_miot_elliptic_pairing expects: the
    challenge answers REQ (before EC_START is ever written), and the
    device's own public-key fragments answer EC_END (the app's own fragments
    carry no individual reply).
    """
    challenge = b"\x0A" * 16

    def script(sent: bytes):
        if sent == miot.MIOT_PAIR_REQ:
            return [miot.MIOT_PAIR_REQ_OK, miot.MIOT_PAIR_CHAL_1 + challenge[:8], miot.MIOT_PAIR_CHAL_2 + challenge[8:]]
        if sent == miot.MIOT_PAIR_EC_END:
            return list(device_fragments)
        if len(sent) == 2 + 4 and sent[:2] == b"\x00\x10":
            # The second, shorter fragment of the app's pairing response.
            return [miot.MIOT_PAIR_SOL_ACK]
        if sent == miot.MIOT_PAIR_OK:
            return [miot.MIOT_PAIR_OK_ACK]
        return []

    return script


def test_miot_elliptic_pairing_succeeds_with_a_fully_scripted_exchange():
    ns = _namespace()
    device_key, device_fragments = _device_public_key_fragments()
    client = FakeMiotClient(_full_script(device_key, device_fragments))

    asyncio.run(ns["_async_attempt_miot_elliptic_pairing"](client, object(), "notice-1"))

    assert client.writes[0] == miot.MIOT_PAIR_REQ
    assert client.writes[-1] == miot.MIOT_PAIR_OK
    assert miot.MIOT_PAIR_EC_START in client.writes


def test_miot_elliptic_pairing_times_out_cleanly_when_nothing_answers():
    ns = _namespace()
    client = FakeMiotClient(lambda sent: [])

    async def run():
        await ns["_async_attempt_miot_elliptic_pairing"](client, object(), "notice-1")

    try:
        asyncio.run(run())
    except ns["ScooterConnectionError"]:
        pass
    else:
        assert False, "expected the unanswered REQ to fail, not succeed"
    assert client.writes == [miot.MIOT_PAIR_REQ]


def test_miot_elliptic_pairing_has_no_characteristic_fails_immediately():
    ns = _namespace()
    client = FakeMiotClient(lambda sent: [])
    client.services = FakeServices(FakeCharacteristic("not-the-right-uuid"))

    async def run():
        await ns["_async_attempt_miot_elliptic_pairing"](client, object(), "notice-1")

    try:
        asyncio.run(run())
    except ns["ScooterConnectionError"] as err:
        assert "characteristic" in str(err)
    else:
        assert False, "expected a missing characteristic to fail fast"
    assert client.writes == []


class FakeHandshakeClient:
    def __init__(self):
        self.is_connected = True
        self.disconnected = False

    async def disconnect(self):
        self.disconnected = True
        self.is_connected = False


def _orchestration_namespace(*, connect_ok=True, classic_ok=False, elliptic_ok=False):
    connect_calls, classic_calls, elliptic_calls = [], [], []
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

    async def fake_elliptic(client_, hass, notification_id):
        elliptic_calls.append(notification_id)
        if not elliptic_ok:
            raise ScooterConnectionError("miot elliptic handshake unanswered")

    ns = _namespace(
        _async_connect=fake_connect,
        _async_attempt_classic_pairing=fake_classic,
        _async_attempt_miot_elliptic_pairing=fake_elliptic,
    )
    return ns, client, connect_calls, classic_calls, elliptic_calls


def test_attempt_pairing_prefers_the_classic_handshake_and_skips_the_fallback():
    ns, client, _connect, classic_calls, elliptic_calls = _orchestration_namespace(classic_ok=True)
    outcome = asyncio.run(ns["async_attempt_pairing"](object(), object(), "Scooter", "flow-1"))
    assert outcome.protocol == "ble129"
    assert outcome.app_key is not None and outcome.error is None
    assert len(classic_calls) == 1
    assert elliptic_calls == []
    assert client.disconnected is True
    assert ns["persistent_notification"].dismissed == ["ninebot_e_scooters_pair_flow-1"]


def test_attempt_pairing_falls_back_to_miot_elliptic_once_classic_fails():
    ns, client, _connect, classic_calls, elliptic_calls = _orchestration_namespace(
        classic_ok=False, elliptic_ok=True,
    )
    outcome = asyncio.run(ns["async_attempt_pairing"](object(), object(), "Scooter", "flow-2"))
    assert outcome.protocol == "xiaomi_mi_ec"
    assert outcome.app_key is not None and outcome.error is None
    assert len(classic_calls) == 1 and len(elliptic_calls) == 1
    assert client.disconnected is True


def test_attempt_pairing_reports_both_failures_when_neither_handshake_answers():
    ns, client, _connect, classic_calls, elliptic_calls = _orchestration_namespace(
        classic_ok=False, elliptic_ok=False,
    )
    outcome = asyncio.run(ns["async_attempt_pairing"](object(), object(), "Scooter", "flow-3"))
    assert outcome.protocol is None and outcome.app_key is None
    assert "classic handshake" in outcome.error and "miot elliptic" in outcome.error
    assert len(classic_calls) == 1 and len(elliptic_calls) == 1
    assert client.disconnected is True


def test_attempt_pairing_never_tries_a_handshake_when_it_cannot_connect():
    ns, client, connect_calls, classic_calls, elliptic_calls = _orchestration_namespace(connect_ok=False)
    outcome = asyncio.run(ns["async_attempt_pairing"](object(), object(), "Scooter", "flow-4"))
    assert outcome.protocol is None
    assert len(connect_calls) == 1
    assert classic_calls == [] and elliptic_calls == []


def test_attempt_pairing_skips_connecting_entirely_without_a_ble_device():
    """A discovered service_info can carry no BLEDevice at all (not
    connectable, or its advertisement already expired); real Home Assistant
    test fixtures model this with device=None."""
    ns, client, connect_calls, classic_calls, elliptic_calls = _orchestration_namespace(connect_ok=True)
    outcome = asyncio.run(ns["async_attempt_pairing"](object(), None, "Scooter", "flow-5"))
    assert outcome.protocol is None and outcome.app_key is None
    assert connect_calls == [] and classic_calls == [] and elliptic_calls == []
