"""The legacy link must serialize callers without losing fragmented replies."""

import asyncio

from custom_components.ninebot_e_scooters.protocols.legacy import LegacyM365Link
from custom_components.ninebot_e_scooters.protocols.ninebot.packet import DeviceId, LegacyM365Reply
from custom_components.ninebot_e_scooters.protocols.xiaomi import ScooterCommand, parse_message


def test_concurrent_reads_match_their_own_registers():
    async def check():
        active = 0
        maximum_active = 0

        async def write(frame):
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            request = parse_message(frame)
            await asyncio.sleep(0.001)
            reply = ScooterCommand(LegacyM365Reply.ESC, 1, request.attribute, bytes((request.attribute, 0))).build()
            link.on_notification(reply[:4])
            link.on_notification(reply[4:])
            active -= 1

        link = LegacyM365Link(write)
        replies = await asyncio.gather(link.read(DeviceId.ESC, 0x1B, 2),
                                       link.read(DeviceId.ESC, 0x1C, 2))
        assert maximum_active == 1
        assert [reply.attribute for reply in replies] == [0x1B, 0x1C]
    asyncio.run(check())


def test_empty_matching_reply_does_not_complete_a_read():
    async def check():
        async def write(frame):
            request = parse_message(frame)
            for payload in (b"", b"\x01", b"\x02\x00"):
                link.on_notification(ScooterCommand(LegacyM365Reply.ESC, 1, request.attribute, payload).build())

        link = LegacyM365Link(write)
        reply = await link.read(DeviceId.ESC, 0x1B, 2)
        assert reply.payload == b"\x02\x00"
    asyncio.run(check())
