from source_helpers import parse_source
"""Regressions for real BLE notification fragmentation and reconnect handling."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from custom_components.ninebot_e_scooters.ninebot_crypto import NinebotCrypto
from custom_components.ninebot_e_scooters.ninebot_packet import NinebotPacket
from protocol_scope import add_protocol_symbols

SRC = Path(__file__).resolve().parents[1] / 'custom_components/ninebot_e_scooters/coordinator.py'
TREE = parse_source(SRC.read_text())
CLASS = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'ScooterCoordinator')
METHODS = {n.name:n for n in CLASS.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def method(name, namespace):
    node = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), METHODS[name]], type_ignores=[])
    add_protocol_symbols(namespace)
    exec(compile(ast.fix_missing_locations(node),str(SRC),'exec'),namespace)
    return namespace[name]


def environment():
    # Import only the receive handler, not the HA runtime.
    ns={'NinebotPacket':NinebotPacket,'_LOGGER':Mock(), 'MAX_BLE129_BUFFER':512,
        'MAX_BLE129_PAYLOAD':128, 'CMD_PING':0x5C, 'CMD_PAIR':0x5D}
    handler=method('_handle_notification',ns)
    scooter=SimpleNamespace(
       _last_notification=None,_raw_notification_count=0,
       _rx_buffer=bytearray(),_rejected_crypto_frames=0,_last_frame_issue=None,
       _crypto=NinebotCrypto('MIScooter5977'),
       _packet_queue=asyncio.Queue(),_last_reply_command=None,
    )
    response=NinebotPacket(source=0x21,target=0x3E,command=0x5B,index=1,
                          data=bytes(range(16))+b'12345678901234')
    encrypted=NinebotCrypto('MIScooter5977').encrypt(response.pack())
    return handler,scooter,response,encrypted


def test_first_5b_survives_split_header_across_ble_notifications():
    handler,o,p,frame=environment()
    handler(o,frame[:1]); assert bytes(o._rx_buffer)==b'\x5a'
    handler(o,frame[1:20]); handler(o,frame[20:])
    assert o._packet_queue.get_nowait()==p
    assert o._last_frame_issue is None
    assert o._raw_notification_count==3


def test_trailing_start_marker_survives_noise_and_next_chunk():
    handler,o,p,frame=environment()
    handler(o,b'\x11\x22\x5a')
    handler(o,frame[1:])
    assert o._packet_queue.get_nowait()==p


def test_invalid_large_length_does_not_block_valid_5b():
    handler,o,p,frame=environment()
    handler(o,b'\x5a\xa5\xf0\x11\x22'+frame)
    assert o._packet_queue.get_nowait()==p


def test_corrupt_candidate_cannot_swallow_following_valid_5b():
    handler,o,p,frame=environment()
    # False header claims 6 bytes of payload; it consumes the first 13
    # bytes of real encrypted reply. Recover its nested 5AA5 header and retry.
    handler(o,b'\x5a\xa5\x06abc'+frame)
    assert o._packet_queue.get_nowait()==p
    assert o._rejected_crypto_frames==1


def test_disconnected_callback_rearms_and_does_not_invalidate_old_client():
    source=ast.unparse(METHODS['_async_establish_client'])
    assert 'disconnected_callback=_disconnected' in source
    assert 'client is not self._client' in source
    assert 'self._retry_not_before' in source
    assert 'self._rearm_advertisements()' in source


