"""Pin 1S wire frames across the protocol-constant refactor.

Vectors were generated with the packaged v0.9.7 packet and crypto modules.
They cover raw BLE129 bytes; the Ninebot ES PDF has a separate serial checksum.
"""

import pytest

from test_protocol import const, protocol
from test_ninebot_crypto import NinebotCrypto, packet_module as packet


@pytest.mark.parametrize("name,frame,logical,encrypted", (
    (
        "init", packet.make_init(),
        "5AA5003E215B00", "5AA50005CFEDE7000045FF0000",
    ),
    (
        "fast telemetry", packet.make_read(packet.DeviceId.ESC, packet.Xiaomi1sEscRegister.FAST_TELEMETRY,
                                            packet.RegisterReadSize.FAST_TELEMETRY),
        "5AA5013E2001B020", "5AA50105CEB757D10000D0FE0000",
    ),
    (
        "battery", packet.make_read(packet.DeviceId.BMS, packet.Xiaomi1sBmsRegister.BATTERY_INFO,
                                     packet.RegisterReadSize.TRIP_AND_BATTERY),
        "5AA5013E2201310A", "5AA50105CCB7D6FB000063FF0000",
    ),
    (
        "ping", packet.make_ping(bytes(range(packet.BLE129_APP_KEY_LENGTH))),
        "5AA5103E215C00000102030405060708090A0B0C0D0E0F",
        "5AA51005CFEAE7F1F2C212C2DB377CFBCE486037E3B8E80000CCFE0000",
    ),
    (
        "pair", packet.make_pair(b"12345678901234"),
        "5AA50E3E215D003132333435363738393031323334",
        "5AA50E05CFEBE7C0C1F325F3E80643CAF7735908DA00006CFC0000",
    ),
))
def test_ble129_first_frame_is_identical_to_v097(name, frame, logical, encrypted):
    raw = bytes.fromhex(logical)
    assert frame.pack() == raw, name
    assert packet.NinebotPacket.unpack(raw) == frame, name
    assert NinebotCrypto("MIScooter5977").encrypt(raw) == bytes.fromhex(encrypted), name


def test_es_and_xiaomi_1s_same_address_has_different_meaning():
    assert packet.NinebotEsRegister.QUICK_ERROR == packet.Xiaomi1sEscRegister.FAST_TELEMETRY == 0xB0
    assert packet.Xiaomi1sEscRegister.SUPPLEMENTARY_KERS == 0x7B
    assert 0x7B not in packet.NinebotEsRegister
    assert const.MOTOR_TO_MASTER == packet.LegacyM365Reply.ESC
    assert packet.DeviceId.EXTERNAL_BMS == packet.LegacyM365Reply.ESC
    assert const.WRITE == packet.PacketOpcode.WRITE_NO_REPLY


def test_legacy_read_frames_keep_their_original_bytes():
    reads = dict(protocol.standard_read_commands())
    assert reads["motor_info"] == protocol.make_read(
        const.MASTER_TO_MOTOR, 0xB0, 0x20,
    )
    assert reads["supplementary"] == protocol.make_read(
        const.MASTER_TO_BATTERY, 0x7B, 0x06,
    )
