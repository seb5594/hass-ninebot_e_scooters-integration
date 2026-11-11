"""A scooter on the other end of the link, for tests without hardware.

The simulator keeps a register file per board, the way the documented
dashboards do: every register is one 16-bit word, and a read of n bytes
returns the words that follow the requested index. Xiaomi block reads and
Ninebot word reads are two views of the same memory.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from types import SimpleNamespace

from custom_components.ninebot_e_scooters.protocols.gatt import NORDIC_UART, UartService
from custom_components.ninebot_e_scooters.protocols.ninebot.crypto import NinebotCrypto
from custom_components.ninebot_e_scooters.protocols.ninebot.packet import (
    CMD_INIT,
    CMD_PAIR,
    CMD_PING,
    CMD_READ,
    CMD_READ_ACK,
    ENCRYPTED_FRAME_OVERHEAD,
    DeviceId,
    FrameOffset,
    NinebotPacket,
    PairingStatus,
)

WORD = 2
ATT_PAYLOAD = 20


class DashboardCrypto(NinebotCrypto):
    """The scooter's half of a session: same frames, key changes mirrored."""

    def _frame_sent(self, logical: bytes, *, before_challenge: bool) -> None:
        if before_challenge and self._is_challenge(logical):
            self._adopt_challenge(logical)
        elif not before_challenge and self._is_password_confirmation(logical):
            self._use_session_key()

    def _frame_received(self, logical: bytes, *, before_challenge: bool) -> None:
        if not before_challenge and self._is_password_offer(logical):
            self._remember_password(logical)


def words(*values: int) -> bytes:
    """Little-endian register words, as they sit in the register file."""
    return b"".join((value & 0xFFFF).to_bytes(WORD, "little") for value in values)


class RegisterFile:
    """Word-addressed memory of one board."""

    def __init__(self, blocks: dict[int, bytes]) -> None:
        self._words: dict[int, bytes] = {}
        for index, block in blocks.items():
            self.store(index, block)

    def store(self, index: int, block: bytes) -> None:
        """Place a block of whole words at a register index."""
        assert len(block) % WORD == 0, "Registers hold whole words"
        for offset in range(0, len(block), WORD):
            self._words[index + offset // WORD] = block[offset:offset + WORD]

    def read(self, index: int, length: int) -> bytes | None:
        """Return length bytes from index on; None if any register is unknown."""
        needed = range(index, index + (length + 1) // WORD)
        if any(register not in self._words for register in needed):
            return None
        return b"".join(self._words[register] for register in needed)[:length]


class SimulatedScooter:
    """Answer the handshake and register reads of the encrypted 5A A5 protocol."""

    def __init__(
        self,
        name: str,
        serial: bytes,
        boards: dict[int, dict[int, bytes]],
        *,
        host_id: DeviceId = DeviceId.PHONE,
        handshake_board: DeviceId = DeviceId.DASHBOARD,
        read_reply_command: int = CMD_READ_ACK,
        challenge: bytes = bytes(range(16)),
        pings_until_button_press: int = 0,
        stored_password: bytes | None = None,
    ) -> None:
        self.serial = serial
        self.requests: list[NinebotPacket] = []
        # The one session password the scooter keeps, as set by its last pairing.
        self.stored_password = stored_password
        self._crypto = DashboardCrypto(name, host_id=host_id, handshake_board=handshake_board)
        self._host_id = host_id
        self._handshake_board = handshake_board
        self._boards = {board: RegisterFile(blocks) for board, blocks in boards.items()}
        self._read_reply_command = read_reply_command
        self._challenge = challenge
        self._pings_until_button_press = pings_until_button_press
        self._paired = False
        self._logged_in = False

    def commands(self) -> list[int]:
        """Opcodes of every request received so far."""
        return [request.command for request in self.requests]

    def receive(self, wire: bytes) -> bytes | None:
        """Take one encrypted request; return the encrypted reply, if any.

        A frame the scooter cannot open, or one for a board it does not
        have, gets no reply at all.
        """
        logical = self._open(wire)
        request = None if logical is None else NinebotPacket.unpack(logical)
        if request is None or request.source != self._host_id:
            return None
        self.requests.append(request)
        reply = self._answer(request)
        return None if reply is None else self._crypto.encrypt(reply.pack())

    def _open(self, wire: bytes) -> bytes | None:
        """Decrypt with the current key or, for a 0x5D login, the stored password."""
        logical = self._crypto.decrypt(wire)
        if logical is not None or self.stored_password is None or self._logged_in:
            return logical
        self._crypto.resume_with_password(self.stored_password)
        logical = self._crypto.decrypt(wire)
        if logical is None:
            self._crypto.forget_password()
        else:
            self._logged_in = True
        return logical

    def _answer(self, request: NinebotPacket) -> NinebotPacket | None:
        if request.command in (CMD_INIT, CMD_PING, CMD_PAIR) and request.target != self._handshake_board:
            return None
        if request.command == CMD_INIT:
            has_password = PairingStatus.PENDING if self.stored_password is None else PairingStatus.CONFIRMED
            return self._dashboard_reply(CMD_INIT, has_password, self._challenge + self.serial)
        if request.command == CMD_PING:
            if self._pings_until_button_press > 0:
                self._pings_until_button_press -= 1
                return self._dashboard_reply(CMD_PING, PairingStatus.PENDING)
            self.stored_password = request.data
            self._logged_in = True
            return self._dashboard_reply(CMD_PING, PairingStatus.CONFIRMED)
        if request.command == CMD_PAIR:
            self._paired = request.data == self.serial
            status = PairingStatus.CONFIRMED if self._paired else PairingStatus.PENDING
            return self._dashboard_reply(CMD_PAIR, status)
        if request.command == CMD_READ:
            board = self._boards.get(request.target)
            data = board.read(request.index, request.data[0]) if board is not None else None
            if data is None:
                return None  # A real scooter stays silent on registers it lacks.
            return NinebotPacket(request.target, self._host_id, self._read_reply_command,
                                 request.index, data)
        return None

    def _dashboard_reply(self, command: int, status: int, data: bytes = b"") -> NinebotPacket:
        return NinebotPacket(self._handshake_board, self._host_id, command, status, data)


class SimulatedGattClient:
    """Bleak client double that carries fragmented frames to a simulated scooter."""

    is_connected = True

    def __init__(self, scooter: SimulatedScooter, uart: UartService = NORDIC_UART) -> None:
        self._scooter = scooter
        self._write_buffer = bytearray()
        self._notify: Callable[[object, bytearray], None] | None = None
        self.services = _Services(uart)

    async def start_notify(self, _characteristic, callback, **_kwargs) -> None:
        self._notify = callback

    async def stop_notify(self, _characteristic) -> None:
        self._notify = None

    async def disconnect(self) -> None:
        self.is_connected = False

    async def write_gatt_char(self, characteristic, fragment, **_kwargs) -> None:
        self._write_buffer.extend(fragment)
        if (len(self._write_buffer) <= FrameOffset.LENGTH
                or len(self._write_buffer) < self._write_buffer[FrameOffset.LENGTH] + ENCRYPTED_FRAME_OVERHEAD):
            return
        reply = self._scooter.receive(bytes(self._write_buffer))
        self._write_buffer.clear()
        if reply is not None and self._notify is not None:
            for fragment_of_reply in _att_fragments(reply):
                self._notify(characteristic, bytearray(fragment_of_reply))


async def bring_into_range(coordinator, client: SimulatedGattClient, name: str) -> None:
    """Let the coordinator see an advertisement and hand it this GATT client."""

    async def establish(_device):
        return client

    coordinator._async_establish_client = establish
    advertisement = SimpleNamespace(address=coordinator.address, name=name, connectable=True,
                                    device=SimpleNamespace(name=name), source="test", rssi=-45)
    assert coordinator.async_on_live_advertisement(advertisement)


def answer_quickly(coordinator, reply_timeout: float = 0.05) -> None:
    """Cap reply timeouts: the simulator answers at once or not at all."""
    request = coordinator._async_crypto_request

    async def impatient(packet, **options):
        options["timeout"] = min(options["timeout"], reply_timeout)
        return await request(packet, **options)

    coordinator._async_crypto_request = impatient


async def poll(coordinator, times: int = 1):
    """Run refreshes the way the update coordinator does and keep their result."""
    for _ in range(times):
        coordinator.data = await coordinator._async_update_data()
    return coordinator.data


def _att_fragments(frame: bytes) -> Iterable[bytes]:
    """Split like a dashboard does, with the sync bytes arriving separately."""
    yield frame[:1]
    for start in range(1, len(frame), ATT_PAYLOAD):
        yield frame[start:start + ATT_PAYLOAD]


class _Characteristic:
    handle = 1

    def __init__(self, uuid: str, properties: tuple[str, ...]) -> None:
        self.uuid = uuid
        self.properties = properties


class _Service:
    def __init__(self, uart: UartService) -> None:
        self.uuid = uart.service_uuid
        self.characteristics = (
            _Characteristic(uart.write_uuid, ("write-without-response", "write")),
            _Characteristic(uart.notify_uuid, ("notify",)),
        )


class _Services:
    """Service collection of a device that offers exactly one serial service."""

    def __init__(self, uart: UartService) -> None:
        self._service = _Service(uart)

    def __iter__(self):
        return iter((self._service,))

    def get_characteristic(self, uuid: str):
        return next((characteristic for characteristic in self._service.characteristics
                     if characteristic.uuid == uuid), None)
