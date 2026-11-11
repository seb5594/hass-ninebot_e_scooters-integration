"""Ninebot word-register polling on the shared authenticated GATT session."""

from __future__ import annotations

import asyncio

from ..protocols.ninebot.packet import (
    CMD_READ,
    CMD_READ_ACK,
    NinebotPacket,
    make_read,
)
from ..protocols.ninebot.registers import (
    BYTES_PER_WORD,
    CLASSIC_REGISTERS,
    RegisterMap,
    RegisterSpec,
)

OPTIONAL_READ_INTERVAL = 60
UNANSWERED_READ_INTERVAL = 300


class NinebotMixin:
    """Poll confirmed read-only tables without reusing Xiaomi block offsets."""

    @property
    def _register_map(self) -> RegisterMap:
        """The register layout of the selected family; classic unless it says otherwise."""
        transport = getattr(self, "transport_profile", None)
        return getattr(transport, "registers", None) or CLASSIC_REGISTERS

    async def _async_read_ninebot_block(self, spec: RegisterSpec) -> NinebotPacket | None:
        """Read adjacent words; discard an incomplete block atomically."""
        if self._register_map.reads_whole_blocks:
            requests = ((spec.index, spec.words * BYTES_PER_WORD),)
        else:
            requests = tuple((spec.index + offset, BYTES_PER_WORD) for offset in range(spec.words))
        parts = []
        for index, length in requests:
            reply = await self._async_crypto_request(
                make_read(spec.target, index, length),
                expected_commands={CMD_READ, CMD_READ_ACK},
                timeout=1.2, accept_timeout=True, quiet_timeout=True,
            )
            if reply is None or len(reply.data) != length:
                return None
            parts.append(reply.data)
        return NinebotPacket(spec.target, self._host_id, CMD_READ_ACK, spec.index, b"".join(parts))

    async def _async_read_ninebot_registers(self) -> list[NinebotPacket]:
        """Read core values and at most one optional block per cycle."""
        registers = self._register_map
        self._last_protocol = registers.protocol_label
        replies = []
        if self._initial_telemetry is not None:
            replies.append(self._initial_telemetry)
            self._initial_telemetry = None
        initial_addresses = {(packet.source, packet.index) for packet in replies}
        for spec in registers.core:
            if (spec.target, spec.index) in initial_addresses:
                continue
            response = await self._async_read_ninebot_block(spec)
            if response is not None:
                replies.append(response)
        if not replies:
            return replies
        now = asyncio.get_running_loop().time()
        for _ in registers.optional:
            spec = registers.optional[self._ninebot_optional_index % len(registers.optional)]
            self._ninebot_optional_index += 1
            if spec.static and self.data is not None and getattr(self.data, spec.fields[0]) is not None:
                continue
            key = f"ninebot_{int(spec.target):02x}_{spec.index:02x}"
            if now < self._next_setting_read_at.get(key, 0):
                continue
            self._next_setting_read_at[key] = now + OPTIONAL_READ_INTERVAL
            response = await self._async_read_ninebot_block(spec)
            if response is not None:
                replies.append(response)
            else:
                self._next_setting_read_at[key] = now + UNANSWERED_READ_INTERVAL
            break
        return replies
