"""Wire vectors preserve the supplied Xiaomi 1S implementation's output."""

import json
from pathlib import Path

from custom_components.ninebot_e_scooters.protocols.data import ScooterData
from custom_components.ninebot_e_scooters.protocols.ninebot.crypto import NinebotCrypto
from custom_components.ninebot_e_scooters.protocols.ninebot.packet import NinebotPacket
from custom_components.ninebot_e_scooters.protocols.xiaomi import ScooterMessage, apply_message


def test_0913_encrypted_wire_vectors_remain_identical():
    fixture = json.loads((Path(__file__).parent / "fixtures/xiaomi_1s_vectors.json").read_text())
    crypto = NinebotCrypto(fixture["name"])
    for vector in fixture["vectors"]:
        packet = bytes.fromhex(vector["logical"])
        assert NinebotPacket.unpack(packet) is not None
        assert crypto.encrypt(packet).hex() == vector["encrypted"]


def test_xiaomi_controller_and_bms_offsets_cannot_be_mixed():
    data = ScooterData(battery_percent=50, is_tail_light_on=False)
    assert not apply_message(data, ScooterMessage(0x22, 1, 0x7D, b"\x02\x00", b""))
    assert not apply_message(data, ScooterMessage(0x20, 1, 0x31, bytes(10), b""))
    assert not apply_message(data, ScooterMessage(0x20, 5, 0x7D, b"\x02\x00", b""))
    assert data.battery_percent == 50
    assert data.is_tail_light_on is False
