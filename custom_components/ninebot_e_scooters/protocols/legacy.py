"""Unencrypted 55 AA transport for the original four-dot Xiaomi M365.

The M365 Pro with BLE110/122 uses the separate chained Ninebot crypto path.
Only complete checksum-validated packets from the requested source/register
may satisfy a read. This adapter never writes scooter settings.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from ..protocols.ninebot.packet import DeviceId, LegacyM365Reply, PacketOpcode
from ..protocols.xiaomi import PacketParser, ScooterCommand, ScooterMessage
from ..utilities import TIMEOUT_ERRORS, timeout as async_timeout


class LegacyM365Link:
    """Hold a live M365 receive parser and serialize reads on one GATT link."""

    def __init__(self, write: Callable[[bytes], Awaitable[None]]) -> None:
        self._write = write
        self._parser = PacketParser()
        self._received: asyncio.Queue[ScooterMessage] = asyncio.Queue()
        self._read_lock = asyncio.Lock()

    def on_notification(self, data: bytes) -> None:
        """Accept arbitrary BLE fragments, never incomplete or invalid frames."""
        for message in self._parser.feed(data):
            self._received.put_nowait(message)

    async def read(
        self, target: DeviceId, register: int, length: int, *, timeout: float = 1.8
    ) -> ScooterMessage | None:
        """Serialize reads so callers cannot discard each other's responses."""
        async with self._read_lock:
            return await self._read_register(target, register, length, timeout=timeout)

    async def _read_register(
        self, target: DeviceId, register: int, length: int, *, timeout: float
    ) -> ScooterMessage | None:
        """A missed optional ACK leaves the session available for the next read."""
        if target not in (DeviceId.ESC, DeviceId.BMS):
            raise ValueError("Only M365 controller and BMS registers can be read")
        if not 0 < length <= 0xFF:
            raise ValueError("Invalid M365 register length")
        while not self._received.empty():
            self._received.get_nowait()
        expected_sources = (
            {LegacyM365Reply.ESC, DeviceId.ESC} if target == DeviceId.ESC
            else {LegacyM365Reply.BMS, DeviceId.BMS}
        )
        frame = ScooterCommand(target, PacketOpcode.READ, register, bytes((length,))).build()
        await self._write(frame)
        try:
            async with async_timeout(timeout):
                while True:
                    message = await self._received.get()
                    if (message.direction in expected_sources
                            and message.attribute == register
                            and message.read_write in (PacketOpcode.READ, PacketOpcode.READ_ACK)
                            and len(message.payload) >= min(length, 2)):
                        return message
        except TIMEOUT_ERRORS:
            return None
