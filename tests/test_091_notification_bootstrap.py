from source_helpers import parse_source
"""Exercise BLE129 notifications through the real coordinator callback."""

import ast
import asyncio
from datetime import UTC, datetime
import logging
from pathlib import Path
from types import SimpleNamespace

from test_ninebot_crypto import NinebotCrypto
from test_pairing_queue import PKT, ScooterConnectionError
from protocol_scope import add_protocol_symbols


COORD = Path(__file__).resolve().parents[1] / "custom_components/ninebot_e_scooters/coordinator.py"
tree = parse_source(COORD.read_text())
cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ScooterCoordinator")
methods = [node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in (
    "_async_ensure_session", "_async_crypto_request", "_handle_notification"
)]
module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
    ast.ClassDef(name="Harness", bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])
namespace = dict(asyncio=asyncio, datetime=datetime, UTC=UTC, NinebotCrypto=NinebotCrypto,
    NinebotPacket=PKT.NinebotPacket, make_init=PKT.make_init, make_read=PKT.make_read,
    make_ping=PKT.make_ping, CMD_INIT=0x5B, CMD_READ=1, CMD_READ_ACK=4,
    CMD_PING=0x5C, CMD_PAIR=0x5D, TARGET_ESC=0x20,
    NUS_WRITE_UUID="write", NUS_NOTIFY_UUID="notify", MAX_ADVERTISEMENT_AGE=5,
    MAX_BLE129_BUFFER=512, MAX_BLE129_PAYLOAD=128,
    BleakError=RuntimeError, ScooterConnectionError=ScooterConnectionError,
    effective_profile=lambda *_args: None, M365_LEGACY="xiaomi_m365_legacy",
    _LOGGER=logging.getLogger("test_091_notification_bootstrap"))
add_protocol_symbols(namespace)
exec(compile(ast.fix_missing_locations(module), str(COORD), "exec"), namespace)


def test_real_fragmented_5b_reply_reaches_pairing_on_current_client():
    """The 0.9.0 callback referenced an undefined client and lost every reply."""

    class Services:
        def __iter__(self):
            return iter((SimpleNamespace(uuid="uart"),))

        def get_characteristic(self, uuid):
            return SimpleNamespace(uuid=uuid, handle=1, properties=("notify",))

    class FakeClient:
        is_connected = True
        services = Services()
        callback = None

        async def start_notify(self, _characteristic, callback, **_kwargs):
            self.callback = callback

    async def check(deliver_on_write: int):
        obj = namespace["Harness"]()
        obj._identify_serial = lambda _serial: None
        client = FakeClient()
        obj._client = None
        obj._session_ready = False
        obj._pending_ble_device = SimpleNamespace(name="MIScooter9999")
        obj._pending_ble_name = "MIScooter9999"
        obj._pending_seen_at = asyncio.get_running_loop().time()
        obj.address = "AA:BB:CC:DD:EE:FF"
        obj.device_name = "old configuration name"
        obj.model = "Mi Electric Scooter 1S"
        obj._model_identification = None
        obj._rx_buffer = bytearray()
        obj._packet_queue = asyncio.Queue()
        obj._next_setting_read_at = {}
        obj._pairing_completed = False
        obj._app_key = bytes(16)
        obj._async_establish_client = lambda _device: asyncio.sleep(0, result=client)
        paired = []

        async def pair_current():
            paired.append(True)

        obj._async_pair_current_session = pair_current

        writes = []

        async def write(_encrypted):
            writes.append(_encrypted)
            if len(writes) != deliver_on_write:
                return
            response = PKT.NinebotPacket(0x21, 0x3E, 0x5B, 0, bytes(30))
            encrypted = NinebotCrypto("MIScooter9999").encrypt(response.pack())
            client.callback(None, bytearray(encrypted[:20]))
            client.callback(None, bytearray(encrypted[20:40]))
            client.callback(None, bytearray(encrypted[40:]))

        obj._async_write_packet = write
        await obj._async_ensure_session()
        assert obj._session_ready
        assert paired == [True]
        assert obj._raw_notification_count == 3
        assert obj._last_reply_command == "0x5B/0x00"
        assert obj._crypto_name_source == "live_advertisement"
        assert len(writes) == deliver_on_write
        assert len(set(writes)) == 1
        assert obj._crypto.message_counter == 1

        # Late notifications on an old connection must not alter a new one.
        obj._client = FakeClient()
        client.callback(None, bytearray(b"\x5a\xa5\x00"))
        assert obj._raw_notification_count == 3

        # Callback faults must wake the waiter and appear in diagnostics.
        obj._client = client
        obj._handle_notification = lambda _payload: (_ for _ in ()).throw(RuntimeError("test callback fault"))
        client.callback(None, bytearray(b"\x5a"))
        assert obj._notification_callback_errors == 1
        assert obj._last_frame_issue == "notification_callback_exception"
        assert obj._packet_queue.get_nowait() is None

    asyncio.run(check(1))
    asyncio.run(check(3))


def test_missing_notifications_rearm_subscription_before_abandoning_gatt():
    class Services:
        def __iter__(self):
            return iter((SimpleNamespace(uuid="uart"),))

        def get_characteristic(self, uuid):
            return SimpleNamespace(uuid=uuid, handle=1, properties=("notify",))

    class Client:
        is_connected = True
        services = Services()

        def __init__(self):
            self.subscriptions = 0
            self.unsubscriptions = 0
            self.callback = None

        async def start_notify(self, _characteristic, callback, **_kw):
            self.subscriptions += 1
            self.callback = callback

        async def stop_notify(self, _characteristic):
            self.unsubscriptions += 1

    async def check():
        obj = namespace["Harness"]()
        client = Client()
        obj.address = "AA:BB:CC:DD:EE:FF"
        obj.device_name = "MIScooter5977"
        obj.model = "Mi Electric Scooter 1S"
        obj._model_identification = None
        obj._pending_ble_device = SimpleNamespace(name="MIScooter5977")
        obj._pending_ble_name = "MIScooter5977"
        obj._pending_seen_at = asyncio.get_running_loop().time()
        obj._client = None
        obj._session_ready = False
        obj._rx_buffer = bytearray()
        obj._packet_queue = asyncio.Queue()
        obj._next_setting_read_at = {}
        obj._pairing_completed = False
        obj._app_key = bytes(16)
        obj._identify_serial = lambda _serial: None
        obj._async_establish_client = lambda _device: asyncio.sleep(0, result=client)
        paired = []

        async def pair_current():
            paired.append(True)

        obj._async_pair_current_session = pair_current
        writes = []

        async def write(frame):
            writes.append(frame)
            if client.subscriptions == 2:
                response = PKT.NinebotPacket(0x21, 0x3E, 0x5B, 0, bytes(30))
                encrypted = NinebotCrypto("MIScooter5977").encrypt(response.pack())
                client.callback(None, bytearray(encrypted))

        obj._async_write_packet = write
        await obj._async_ensure_session()
        assert client.subscriptions == 2 and client.unsubscriptions == 1
        assert len(writes) == 4 and len(set(writes)) == 1
        assert obj._crypto.message_counter == 1
        assert paired == [True] and obj._session_ready

    asyncio.run(check())
