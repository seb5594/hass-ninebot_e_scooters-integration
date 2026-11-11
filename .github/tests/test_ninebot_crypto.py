"""BLE129 crypto tests against the current NinebotCrypto interface."""

import importlib
from pathlib import Path
import sys
import types

import pytest

PACKAGE_PATH = Path(__file__).resolve().parents[2] / "custom_components" / "ninebot_e_scooters"

# Load pure crypto modules without starting the full Home Assistant runtime.
package = types.ModuleType("custom_components.ninebot_e_scooters")
package.__path__ = [str(PACKAGE_PATH)]
sys.modules["custom_components.ninebot_e_scooters"] = package


crypto_module = importlib.import_module("custom_components.ninebot_e_scooters.protocols.ninebot.crypto")
packet_module = importlib.import_module("custom_components.ninebot_e_scooters.protocols.ninebot.packet")
NinebotCrypto = crypto_module.NinebotCrypto

from scooter_simulator import DashboardCrypto  # noqa: E402


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


def test_challenge_of_the_scooter_changes_the_session_key():
    read = packet_module.make_read(0x22, 0x32, 2).pack()
    frames = []
    for challenge in (bytes(16), bytes(range(16))):
        dashboard, host = _session_after_challenge(challenge)
        frames.append(host.encrypt(read))
        assert dashboard.decrypt(frames[-1]) == read
    assert frames[0] != frames[1]


def test_ping_frame_length():
    ping = packet_module.make_ping(bytes(range(16))).pack()
    assert len(ping) == 23
    assert ping[:7] == bytes.fromhex("5AA5103E215C00")
    encrypted = NinebotCrypto("MIScooter5977").encrypt(ping)
    assert len(encrypted) == 29  # This must be written in multiple ATT chunks.



NAME = "MIScooter5977"
SERIAL = b"12345678901234"


def _challenge_reply(challenge: bytes) -> bytes:
    return packet_module.NinebotPacket(
        source=0x21, target=0x3E, command=0x5B, index=0, data=challenge + SERIAL,
    ).pack()


def _session_after_challenge(challenge: bytes = bytes(range(16))):
    """Dashboard and host after 0x5B: both hold the key derived from the challenge."""
    dashboard, host = DashboardCrypto(NAME), NinebotCrypto(NAME)
    init = packet_module.make_init().pack()
    assert dashboard.decrypt(host.encrypt(init)) == init
    reply = _challenge_reply(challenge)
    assert host.decrypt(dashboard.encrypt(reply)) == reply
    return dashboard, host


def _flip(frame: bytes, position: int, mask: int) -> bytes:
    damaged = bytearray(frame)
    damaged[position] ^= mask
    return bytes(damaged)


def test_first_reply_bad_crc_does_not_set_ble_key():
    dashboard, host = DashboardCrypto(NAME), NinebotCrypto(NAME)
    dashboard.decrypt(host.encrypt(packet_module.make_init().pack()))
    reply = _challenge_reply(bytes(range(16)))
    wire = dashboard.encrypt(reply)
    assert host.decrypt(_flip(wire, -3, 0x40)) is None
    assert host.last_rejection_reason == "first_frame_crc_or_name"
    assert host.message_counter == 1
    # Still on the name key: the undamaged reply opens and the session goes on.
    assert host.decrypt(wire) == reply
    read = packet_module.make_read(0x20, 0xB0, 0x20).pack()
    assert dashboard.decrypt(host.encrypt(read)) == read


def test_high_counter_must_pass_integrity_not_arbitrary_limit():
    dashboard, host = _session_after_challenge()
    message = packet_module.NinebotPacket(
        source=0x21, target=0x3E, command=0x5C, index=0,
    ).pack()
    dashboard._counter = 39159
    packet = dashboard.encrypt(message)  # valid high counter 39160
    assert host.decrypt(packet) == message
    assert host.message_counter == 39160
    assert host.decrypt(packet) is None  # no counter reuse
    assert host.last_rejection_reason == "old_or_replayed_counter"


def test_counter_keeps_counting_beyond_the_16_bits_on_the_wire():
    dashboard, host = _session_after_challenge()
    read = packet_module.make_read(0x22, 0x32, 2).pack()
    reply = packet_module.NinebotPacket(source=0x22, target=0x3E, command=4, index=0x32, data=b"\x50\x00").pack()
    dashboard._counter = host._counter = 0xFFFC
    for _ in range(4):
        assert dashboard.decrypt(host.encrypt(read)) == read
        assert host.decrypt(dashboard.encrypt(reply)) == reply
    assert host.message_counter == dashboard.message_counter == 0x10004


def test_corrupt_high_counter_cannot_poison_future_session():
    dashboard, host = _session_after_challenge()
    message = packet_module.NinebotPacket(
        source=0x21, target=0x3E, command=0x5C, index=0,
    ).pack()
    good = dashboard.encrypt(message)
    bad = good[:-2] + (39160).to_bytes(2, "big")  # fake high counter, old MAC
    assert host.decrypt(bad) is None
    assert host.last_rejection_reason == "chained_frame_integrity"
    assert host.message_counter == 1
    assert host.decrypt(good) == message
    assert host.message_counter == 2


def test_bad_encrypted_mac_cannot_switch_key():
    dashboard, host = _session_after_challenge()
    offer = packet_module.make_ping(bytes(reversed(range(16)))).pack()
    assert dashboard.decrypt(host.encrypt(offer)) == offer
    confirmation = packet_module.NinebotPacket(
        source=0x21, target=0x3E, command=0x5C, index=1,
    ).pack()
    wire = dashboard.encrypt(confirmation)
    counter_before = host.message_counter
    assert host.decrypt(_flip(wire, -6, 0x01)) is None
    assert host.message_counter == counter_before
    # The confirmation was sealed with the challenge key. It only opens if
    # the damaged copy has not moved the host to the password key.
    assert host.decrypt(wire) == confirmation
    read = packet_module.make_read(0x20, 0xB0, 0x20).pack()
    assert dashboard.decrypt(host.encrypt(read)) == read
