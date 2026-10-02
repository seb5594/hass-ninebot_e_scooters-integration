from source_helpers import parse_source
"""Regression checks for a late BLE129 0x5C01 response.

Extract coordinator method with AST so these logic tests run without a full
Home Assistant/BlueZ installation. Real scooter integration needs HA.
"""
import ast
import asyncio
import importlib.util
import logging
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ninebot_e_scooters"
SPEC = importlib.util.spec_from_file_location("ninebot_packet_034", ROOT / "protocols/ninebot/packet.py")
PKT = importlib.util.module_from_spec(SPEC)
import sys
from protocol_scope import add_protocol_symbols
sys.modules[SPEC.name] = PKT
SPEC.loader.exec_module(PKT)

SRC = parse_source((ROOT / "coordinator.py").read_text())
COORD = next(x for x in SRC.body if isinstance(x, ast.ClassDef) and x.name == "ScooterCoordinator")
METHOD = next(x for x in COORD.body if isinstance(x, ast.AsyncFunctionDef) and x.name == "_async_crypto_request")
MOD = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                       ast.ClassDef(name="Harness", bases=[], keywords=[], body=[METHOD], decorator_list=[])], type_ignores=[])
class ScooterConnectionError(Exception):
    pass

NS = {"asyncio": asyncio, "NinebotPacket": PKT.NinebotPacket,
      "CMD_INIT": PKT.CMD_INIT,
      "CMD_READ": PKT.CMD_READ, "CMD_PING": PKT.CMD_PING, "CMD_PAIR": PKT.CMD_PAIR,
      "_LOGGER": logging.getLogger("test_pairing_queue"),
      "ScooterConnectionError": ScooterConnectionError}
add_protocol_symbols(NS, PKT)
exec(compile(ast.fix_missing_locations(MOD), "<coordinator_pairing_queue_test>", "exec"), NS)


def harness():
    test = NS["Harness"]()
    test._crypto = SimpleNamespace(encrypt=lambda raw: b"ENCRYPTED", message_counter=2)
    test._client = SimpleNamespace(is_connected=True)
    test._tx_char = object()
    test._packet_queue = asyncio.Queue()
    test._last_reply_command = "0x5B/0x01"
    test._raw_notification_count = 1
    test._last_notification = "some previous message"
    test._stage = "ble129_pairing_5c_5d"
    test.writes = []

    async def write(payload):
        test.writes.append(payload)
    test._async_write_packet = write
    return test


def test_late_5c01_is_not_discarded_and_does_not_resend_5c():
    async def check():
        test = harness()
        test._packet_queue.put_nowait(PKT.NinebotPacket(0x21, 0x3E, 0x5B, 1, b""))
        expected = PKT.NinebotPacket(0x21, 0x3E, 0x5C, 1, b"")
        test._packet_queue.put_nowait(expected)
        result = await test._async_crypto_request(
            PKT.make_ping(bytes(16)), expected_commands={0x5C}, timeout=0.03,
        )
        assert result is expected
        assert test.writes == [], "must not send another 0x5C after 0x5C01"
    asyncio.run(check())


def test_late_other_register_does_not_satisfy_read_request():
    async def check():
        test = harness()
        stale = PKT.NinebotPacket(0x23, 0x3E, 0x04, 0x3A, b"\x00")
        wanted = PKT.NinebotPacket(0x23, 0x3E, 0x04, 0xB0, b"\x01")
        test._packet_queue.put_nowait(stale)
        test._packet_queue.put_nowait(wanted)
        result = await test._async_crypto_request(
            PKT.make_read(0x20, 0xB0, 0x20), expected_commands={0x04}, timeout=0.03,
        )
        assert result is wanted
        assert test.writes == [b"ENCRYPTED"]
    asyncio.run(check())

# Regression for Xiaomi 1S BLE129: the decrypted 5A A5 envelope contains a
# 0x01 read reply, not the 0x04 read ACK used by Ninebot models.
def test_xiaomi_1s_read_reply_01_is_accepted_with_native_controller_source():
    async def check():
        test = harness()
        request = PKT.make_read(0x20, 0xB0, 0x20)
        expected = PKT.NinebotPacket(0x20, 0x3E, 0x01, 0xB0, bytes(32))
        test._packet_queue.put_nowait(expected)
        got = await test._async_crypto_request(
            request, expected_commands={PKT.CMD_READ, PKT.CMD_READ_ACK}, timeout=0.03,
        )
        assert got is expected
        assert test.writes == [b"ENCRYPTED"]
    asyncio.run(check())


def test_xiaomi_1s_bms_read_reply_01_is_accepted_with_native_bms_source():
    async def check():
        test = harness()
        request = PKT.make_read(0x22, 0x31, 0x0A)
        expected = PKT.NinebotPacket(0x22, 0x3E, 0x01, 0x31, bytes(10))
        test._packet_queue.put_nowait(expected)
        got = await test._async_crypto_request(
            request, expected_commands={0x01, 0x04}, timeout=0.03,
        )
        assert got is expected
    asyncio.run(check())


def test_read_does_not_consume_unrelated_register_source_or_destination():
    async def check():
        test = harness()
        request = PKT.make_read(0x20, 0xB0, 0x20)
        invalid = (
            PKT.NinebotPacket(0x20, 0x3E, 0x01, 0x3A, bytes(10)),  # other register
            PKT.NinebotPacket(0x22, 0x3E, 0x01, 0xB0, bytes(32)),  # battery, not ESC
            PKT.NinebotPacket(0x20, 0x3D, 0x01, 0xB0, bytes(32)),  # not addressed to phone
        )
        for packet in invalid:
            test._packet_queue.put_nowait(packet)
        expected = PKT.NinebotPacket(0x20, 0x3E, 0x01, 0xB0, bytes(32))
        test._packet_queue.put_nowait(expected)
        got = await test._async_crypto_request(
            request, expected_commands={0x01, 0x04}, timeout=0.03,
        )
        assert got is expected
    asyncio.run(check())


def test_ninebot_style_read_ack_04_still_supported():
    async def check():
        test = harness()
        expected = PKT.NinebotPacket(0x20, 0x3E, 0x04, 0x25, b"\x4a\x01")
        test._packet_queue.put_nowait(expected)
        got = await test._async_crypto_request(
            PKT.make_read(0x20, 0x25, 2),
            expected_commands={0x01, 0x04}, timeout=0.03,
        )
        assert got is expected
    asyncio.run(check())


