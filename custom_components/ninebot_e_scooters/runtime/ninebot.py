"""Ninebot word-register polling on the shared authenticated GATT session."""

from __future__ import annotations

import asyncio

from ..protocols.ninebot.packet import (
    CMD_READ,
    CMD_READ_ACK,
    NinebotPacket,
    make_read,
)
from ..protocols.ninebot.registers import CORE_REGISTERS, OPTIONAL_REGISTERS, RegisterSpec


class NinebotMixin:
    """Poll confirmed read-only tables without reusing Xiaomi block offsets."""

    async def _async_read_ninebot_block(self, spec: RegisterSpec) -> NinebotPacket | None:
        """Read adjacent words; discard an incomplete block atomically."""
        words = []
        for offset in range(spec.words):
            reply = await self._async_crypto_request(
                make_read(spec.target, spec.index + offset, 2),
                expected_commands={CMD_READ, CMD_READ_ACK},
                timeout=1.2, accept_timeout=True, quiet_timeout=True,
            )
            if reply is None or len(reply.data) != 2:
                return None
            words.append(reply.data)
        return NinebotPacket(spec.target, self._host_id, CMD_READ_ACK, spec.index, b"".join(words))

    async def _async_read_ninebot_registers(self) -> list[NinebotPacket]:
        """Read core values and at most one optional block per cycle."""
        self._last_protocol = "Ninebot chained crypto / word registers (read-only)"
        replies = []
        if self._initial_telemetry is not None:
            replies.append(self._initial_telemetry)
            self._initial_telemetry = None
        initial_addresses = {(packet.source, packet.index) for packet in replies}
        for spec in CORE_REGISTERS:
            if (spec.target, spec.index) in initial_addresses:
                continue
            response = await self._async_read_ninebot_block(spec)
            if response is not None:
                replies.append(response)
        if not replies:
            return replies
        now = asyncio.get_running_loop().time()
        for _ in OPTIONAL_REGISTERS:
            spec = OPTIONAL_REGISTERS[self._ninebot_optional_index % len(OPTIONAL_REGISTERS)]
            self._ninebot_optional_index += 1
            if spec.static and self.data is not None and getattr(self.data, spec.fields[0]) is not None:
                continue
            key = f"ninebot_{int(spec.target):02x}_{spec.index:02x}"
            if now < self._next_setting_read_at.get(key, 0):
                continue
            self._next_setting_read_at[key] = now + 60
            response = await self._async_read_ninebot_block(spec)
            if response is not None:
                replies.append(response)
            else:
                self._next_setting_read_at[key] = now + 300
            break
        return replies
