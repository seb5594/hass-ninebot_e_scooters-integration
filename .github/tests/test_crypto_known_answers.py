"""Replay recorded sessions of the last release against the current crypto.

The session crypto was rewritten from the public description of the scheme.
These vectors keep it byte-identical to the implementation that is known to
work with a real scooter: every output, counter and rejection must match.
"""

import json
from pathlib import Path

import pytest

from custom_components.ninebot_e_scooters.protocols.ninebot.crypto import NinebotCrypto
from custom_components.ninebot_e_scooters.protocols.ninebot.packet import DeviceId

FIXTURE = json.loads((Path(__file__).parent / "fixtures/released_crypto_sessions.json").read_text())


@pytest.mark.parametrize("session", FIXTURE["sessions"], ids=lambda session: session["name"])
def test_recorded_session_is_reproduced_byte_for_byte(session):
    crypto = NinebotCrypto(session["name"], host_id=DeviceId(session["host"]))
    for number, step in enumerate(session["steps"]):
        result = getattr(crypto, step["operation"])(bytes.fromhex(step["input"]))
        assert (None if result is None else result.hex()) == step["output"], number
        assert crypto.message_counter == step["counter"], number
        assert crypto.last_rejection_reason == step["rejection"], number


def test_recorded_sessions_cover_every_branch_of_the_crypto():
    steps = [step for session in FIXTURE["sessions"] for step in session["steps"]]
    assert {step["rejection"] for step in steps if step["operation"] == "decrypt"} == {
        None, "invalid_header_or_short_frame", "first_frame_crc_or_name",
        "old_or_replayed_counter", "chained_frame_integrity",
    }
    # At least one session runs past the 16 counter bits that travel on the wire.
    assert max(step["counter"] for step in steps) > 0xFFFF
