"""BLE129 crypto tests against the current NinebotCrypto interface."""

import importlib.util
from pathlib import Path
import sys
import types

import pytest

PACKAGE_PATH = Path(__file__).resolve().parents[2] / "custom_components" / "ninebot_e_scooters"

# Load pure crypto modules without starting the full Home Assistant runtime.
package = types.ModuleType("custom_components.ninebot_e_scooters")
package.__path__ = [str(PACKAGE_PATH)]
sys.modules["custom_components.ninebot_e_scooters"] = package


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, PACKAGE_PATH / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


crypto_module = _load_module("custom_components.ninebot_e_scooters.ninebot_crypto", "ninebot_crypto.py")
packet_module = _load_module("custom_components.ninebot_e_scooters.ninebot_packet", "protocols/ninebot/packet.py")
NinebotCrypto = crypto_module.NinebotCrypto


def test_packet_roundtrip():
    packet = packet_module.make_init().pack()
    assert packet == bytes.fromhex("5AA5003E215B00")
    assert packet_module.NinebotPacket.unpack(packet) is not None


def test_crypto_encrypt_is_session_stable():
    crypto = NinebotCrypto("MIScooter5977")
    packet = packet_module.make_init().pack()
    encrypted = crypto.encrypt(packet)

    # BLE129 crypto adds six trailer bytes to the logical packet.
    assert encrypted[:3] == b"\x5A\xA5\x00"
    assert len(encrypted) == len(packet) + 6
    assert crypto.message_counter == 1
    again = NinebotCrypto("MIScooter5977").encrypt(packet)
    assert encrypted == again


def test_crypto_key_derivation_changes_after_ble_data():
    crypto = NinebotCrypto("MIScooter5977")
    original = crypto._sha1_key
    crypto._random_ble_data = bytes(reversed(range(16)))
    crypto._sha1_key = crypto._calc_sha1_key(crypto._name, crypto._random_ble_data)
    assert crypto._sha1_key != original


def test_ping_frame_length():
    ping = packet_module.make_ping(bytes(range(16))).pack()
    assert len(ping) == 23
    assert ping[:7] == bytes.fromhex("5AA5103E215C00")
    encrypted = NinebotCrypto("MIScooter5977").encrypt(ping)
    assert len(encrypted) == 29  # This must be written in multiple ATT chunks.



def _make_5b_pair():
    """Generate encrypted legacy 0x5B reply with a deterministic BLE key."""
    tx = NinebotCrypto("MIScooter5977")
    rx = NinebotCrypto("MIScooter5977")
    key = bytes(range(16))
    serial = b"12345678901234"
    reply = packet_module.NinebotPacket(
        source=0x21, target=0x3E, command=0x5B, index=0,
        data=key + serial,
    ).pack()
    encrypted = tx.encrypt(reply)
    assert rx.decrypt(encrypted) == reply
    tx._random_ble_data = key
    tx._sha1_key = tx._calc_sha1_key(tx._name, key)
    return tx, rx


def test_first_reply_bad_crc_does_not_set_ble_key():
    tx = NinebotCrypto("MIScooter5977")
    rx = NinebotCrypto("MIScooter5977")
    reply = packet_module.NinebotPacket(
        source=0x21, target=0x3E, command=0x5B, index=0,
        data=bytes(range(16)) + b"12345678901234",
    ).pack()
    bad = bytearray(tx.encrypt(reply))
    bad[-3] ^= 0x40
    before = (rx.message_counter, rx._random_ble_data, rx._sha1_key)
    assert rx.decrypt(bytes(bad)) is None
    assert (rx.message_counter, rx._random_ble_data, rx._sha1_key) == before


def test_high_counter_must_pass_integrity_not_arbitrary_limit():
    tx, rx = _make_5b_pair()
    message = packet_module.NinebotPacket(
        source=0x21, target=0x3E, command=0x5C, index=0,
    ).pack()
    tx._msg_it = 39159
    packet = tx.encrypt(message)  # valid high counter 39160
    assert rx.decrypt(packet) == message
    assert rx.message_counter == 39160
    assert rx.decrypt(packet) is None  # no counter reuse


def test_corrupt_high_counter_cannot_poison_future_session():
    tx, rx = _make_5b_pair()
    message = packet_module.NinebotPacket(
        source=0x21, target=0x3E, command=0x5C, index=0,
    ).pack()
    good = tx.encrypt(message)
    bad = bytearray(good)
    bad[-2:] = (39160).to_bytes(2, "big")  # fake high counter, old MAC
    assert rx.decrypt(bytes(bad)) is None
    assert rx.message_counter == 0
    assert rx.decrypt(good) == message
    assert rx.message_counter == 2


def test_bad_encrypted_mac_cannot_switch_key():
    tx, rx = _make_5b_pair()
    packet = packet_module.NinebotPacket(
        source=0x21, target=0x3E, command=0x5C, index=1,
    ).pack()
    old_key = rx._sha1_key
    bad = bytearray(tx.encrypt(packet))
    bad[-6] ^= 0x01
    assert rx.decrypt(bytes(bad)) is None
    assert rx._sha1_key == old_key
    assert rx.message_counter == 0
