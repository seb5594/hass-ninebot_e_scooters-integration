"""Session encryption of the 5A A5 protocol on Xiaomi and Segway-Ninebot dashboards.

Every frame keeps its three header bytes in the clear. The rest is XORed with
an AES-128 keystream and followed by six trailer bytes. Until the scooter has
sent its challenge, frames carry counter zero, share one keystream block and
end in a plain checksum. Afterwards each frame has its own counter, a
counter-mode keystream and a four-byte CBC-MAC tag, close to AES-CCM.

The key changes twice during the handshake:
  0x5B  key = SHA1(device name | firmware seed); the reply holds the challenge
  0x5C  key = SHA1(device name | challenge); the host sends a session password
  0x5D  key = SHA1(session password | challenge), kept for the rest of the link

Written from the published description of the scheme and checked against
frames of the release that runs on the reference scooter:
  https://nootnooot.codeberg.page/segway-ninebot-ble/encryption/
  https://nootnooot.codeberg.page/segway-ninebot-ble/authentication/
"""

from __future__ import annotations

from collections.abc import Iterator
import hashlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .packet import (
    BLE129_APP_KEY_LENGTH,
    BLE129_INIT_REPLY_LENGTH,
    DeviceId,
    ENCRYPTED_TRAILER_LENGTH,
    FrameOffset,
    HEADER,
    PacketOpcode,
    PairingStatus,
)

BLOCK_LENGTH = 16
CLEAR_HEADER_LENGTH = len(HEADER) + 1  # 5A A5 and the payload length
TAG_LENGTH = 4
WIRE_COUNTER_LENGTH = 2
WIRE_COUNTER_MASK = 0xFFFF
WIRE_COUNTER_TOP_BIT = 0x8000
CHALLENGE_BYTES_IN_NONCE = 8

# Leading byte of the two kinds of AES input block.
KEYSTREAM_BLOCK = 0x01
MAC_START_BLOCK = 0x59

# Constant of the dashboard firmware: second key half and keystream input
# for the frames exchanged before the scooter has issued its challenge.
FIRMWARE_SEED = bytes.fromhex("97CFB802844143DE56002B3B34780A5D")

SHORTEST_FRAME_LENGTH = CLEAR_HEADER_LENGTH + ENCRYPTED_TRAILER_LENGTH

# Why decrypt() refused a frame; shown in diagnostics.
REJECTED_MALFORMED = "invalid_header_or_short_frame"
REJECTED_FIRST_CHECKSUM = "first_frame_crc_or_name"
REJECTED_REPLAY = "old_or_replayed_counter"
REJECTED_TAG = "chained_frame_integrity"


def _aes(key: bytes, block: bytes) -> bytes:
    """Encrypt a single block with AES-128."""
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return encryptor.update(block) + encryptor.finalize()


def _pad(data: bytes) -> bytes:
    """Cut or zero-fill to exactly one AES block."""
    return data[:BLOCK_LENGTH].ljust(BLOCK_LENGTH, b"\x00")


def _xor(data: bytes, mask: bytes) -> bytes:
    """XOR data with the start of a mask at least as long."""
    return bytes(byte ^ mask_byte for byte, mask_byte in zip(data, mask))


def _blocks(data: bytes) -> Iterator[bytes]:
    """Split into AES blocks; the last one may be shorter."""
    for start in range(0, len(data), BLOCK_LENGTH):
        yield data[start:start + BLOCK_LENGTH]


def derive_key(first: bytes, second: bytes) -> bytes:
    """Hash two padded key halves into the AES key of one handshake phase."""
    return hashlib.sha1(_pad(first) + _pad(second)).digest()[:BLOCK_LENGTH]


def first_frame_checksum(payload: bytes) -> bytes:
    """Inverted 16-bit byte sum that protects frames sent with counter zero."""
    return (~sum(payload) & 0xFFFF).to_bytes(2, "little")


class NinebotCrypto:
    """Host side of one encrypted session; a new GATT link needs a new instance."""

    def __init__(
        self,
        name: str,
        *,
        host_id: DeviceId = DeviceId.PHONE,
        handshake_board: DeviceId = DeviceId.DASHBOARD,
    ) -> None:
        """Start with the key every host can derive from the advertised name.

        `handshake_board` is the Bluetooth module that answers 0x5B to 0x5D:
        the dashboard on classic scooters, board 0x04 on the VCU generation.
        """
        if host_id not in (DeviceId.PHONE, DeviceId.PC):
            raise ValueError("A crypto session requires a phone or PC host address")
        self._host_id = host_id
        self._handshake_board = handshake_board
        self._device_name = _pad(name.encode("utf-8", errors="ignore"))
        self._challenge = bytes(BLOCK_LENGTH)
        self._session_password = bytes(BLOCK_LENGTH)
        self._key = derive_key(self._device_name, FIRMWARE_SEED)
        self._counter = 0
        self.last_rejection_reason: str | None = None

    @property
    def message_counter(self) -> int:
        """Counter of the newest frame this session sent or accepted."""
        return self._counter

    def encrypt(self, frame: bytes) -> bytes:
        """Wrap a logical 5A A5 frame for transmission."""
        if len(frame) < CLEAR_HEADER_LENGTH or frame[:len(HEADER)] != HEADER:
            raise ValueError("Ninebot packet must start with 5A A5")
        header, payload = frame[:CLEAR_HEADER_LENGTH], frame[CLEAR_HEADER_LENGTH:]

        if self._counter == 0:
            self._counter = 1
            encrypted = (
                header + self._first_keystream_xor(payload)
                + b"\x00\x00" + first_frame_checksum(payload) + b"\x00\x00"
            )
            self._frame_sent(frame, before_challenge=True)
            return encrypted

        self._counter += 1
        tag = self._tag(header, payload, self._counter)
        wire_counter = (self._counter & WIRE_COUNTER_MASK).to_bytes(WIRE_COUNTER_LENGTH, "big")
        encrypted = header + self._keystream_xor(payload, self._counter) + tag + wire_counter
        self._frame_sent(frame, before_challenge=False)
        return encrypted

    def decrypt(self, frame: bytes) -> bytes | None:
        """Return the logical frame, or None with last_rejection_reason set."""
        self.last_rejection_reason = None
        if len(frame) < SHORTEST_FRAME_LENGTH or frame[:len(HEADER)] != HEADER:
            self.last_rejection_reason = REJECTED_MALFORMED
            return None
        header = frame[:CLEAR_HEADER_LENGTH]
        ciphertext = frame[CLEAR_HEADER_LENGTH:-ENCRYPTED_TRAILER_LENGTH]
        trailer = frame[-ENCRYPTED_TRAILER_LENGTH:]
        counter = self._full_counter(int.from_bytes(trailer[-WIRE_COUNTER_LENGTH:], "big"))

        if counter == 0:
            return self._decrypt_first(header, ciphertext, trailer)
        if counter <= self._counter:
            self.last_rejection_reason = REJECTED_REPLAY
            return None

        payload = self._keystream_xor(ciphertext, counter)
        # The tag is checked with the candidate counter before anything is
        # stored: a damaged frame must change neither the counter nor the key.
        if self._tag(header, payload, counter) != trailer[:TAG_LENGTH]:
            self.last_rejection_reason = REJECTED_TAG
            return None
        logical = header + payload
        self._frame_received(logical, before_challenge=False)
        self._counter = counter
        return logical

    def _frame_sent(self, logical: bytes, *, before_challenge: bool) -> None:
        """Remember the session password this host offers with 0x5C."""
        if not before_challenge and self._is_password_offer(logical):
            self._remember_password(logical)

    def _frame_received(self, logical: bytes, *, before_challenge: bool) -> None:
        """Move to the next key once the dashboard answers 0x5B or accepts 0x5C."""
        if before_challenge:
            if self._is_challenge(logical):
                self._adopt_challenge(logical)
        elif self._is_password_confirmation(logical):
            self._use_session_key()

    def _adopt_challenge(self, challenge_frame: bytes) -> None:
        """Second key: the device name combined with the challenge of the scooter."""
        self._challenge = challenge_frame[FrameOffset.DATA:FrameOffset.DATA + BLOCK_LENGTH]
        self._key = derive_key(self._device_name, self._challenge)

    def _remember_password(self, offer_frame: bytes) -> None:
        """Keep the offered password until the scooter confirms it."""
        self._session_password = offer_frame[FrameOffset.DATA:FrameOffset.DATA + BLE129_APP_KEY_LENGTH]

    def _use_session_key(self) -> None:
        """Third key: the confirmed session password combined with the challenge."""
        self._key = derive_key(self._session_password, self._challenge)

    def resume_with_password(self, password: bytes) -> None:
        """Skip 0x5C: use a password the scooter already stores for this session."""
        self._session_password = _pad(password)
        self._use_session_key()

    def forget_password(self) -> None:
        """Return to the challenge key after the scooter refused a stored password."""
        self._key = derive_key(self._device_name, self._challenge)

    def _decrypt_first(self, header: bytes, ciphertext: bytes, trailer: bytes) -> bytes | None:
        """Open a frame that was sent with counter zero."""
        payload = self._first_keystream_xor(ciphertext)
        # A fragment of another frame would otherwise pass as a 0x5B reply
        # and replace the key of this session for good.
        if first_frame_checksum(payload) != trailer[2:4]:
            self.last_rejection_reason = REJECTED_FIRST_CHECKSUM
            return None
        logical = header + payload
        self._frame_received(logical, before_challenge=True)
        return logical

    def _full_counter(self, wire_counter: int) -> int:
        """Extend the 16 transmitted counter bits by the rollovers seen so far."""
        rollovers = self._counter & ~WIRE_COUNTER_MASK
        if self._counter & WIRE_COUNTER_TOP_BIT and not wire_counter & WIRE_COUNTER_TOP_BIT:
            rollovers += WIRE_COUNTER_MASK + 1
        return rollovers | wire_counter

    def _first_keystream_xor(self, data: bytes) -> bytes:
        """Counter-zero frames reuse a single keystream block for every data block."""
        keystream = _aes(self._key, FIRMWARE_SEED)
        return b"".join(_xor(block, keystream) for block in _blocks(data))

    def _aes_input(self, kind: int, counter: int, last_byte: int) -> bytes:
        """Block made of kind, frame counter, challenge prefix and a final byte."""
        nonce = counter.to_bytes(4, "big") + self._challenge[:CHALLENGE_BYTES_IN_NONCE]
        return bytes((kind,)) + nonce + bytes((0, 0, last_byte))

    def _keystream_xor(self, data: bytes, counter: int) -> bytes:
        """Counter mode: data block n is XORed with the encrypted block number n."""
        return b"".join(
            _xor(block, _aes(self._key, self._aes_input(KEYSTREAM_BLOCK, counter, number)))
            for number, block in enumerate(_blocks(data), start=1)
        )

    def _tag(self, header: bytes, payload: bytes, counter: int) -> bytes:
        """CBC-MAC over header and plain payload, masked with keystream block zero."""
        mac = _aes(self._key, self._aes_input(MAC_START_BLOCK, counter, len(payload)))
        for block in (header, *_blocks(payload)):
            mac = _aes(self._key, _xor(_pad(block), mac))
        mask = _aes(self._key, self._aes_input(KEYSTREAM_BLOCK, counter, 0))
        return _xor(mac[:TAG_LENGTH], mask)

    def _is_challenge(self, logical: bytes) -> bool:
        """0x5B reply of the Bluetooth module: 16 challenge bytes, then the serial."""
        return (
            logical[FrameOffset.LENGTH] >= BLE129_INIT_REPLY_LENGTH
            and logical[FrameOffset.SOURCE:FrameOffset.INDEX]
            == bytes((self._handshake_board, self._host_id, PacketOpcode.INIT))
        )

    def _is_password_offer(self, logical: bytes) -> bool:
        """0x5C request of this host that carries the session password."""
        return logical[CLEAR_HEADER_LENGTH - 1:FrameOffset.DATA] == bytes((
            BLE129_APP_KEY_LENGTH, self._host_id, self._handshake_board,
            PacketOpcode.PING, PairingStatus.PENDING,
        ))

    def _is_password_confirmation(self, logical: bytes) -> bool:
        """Empty 0x5C reply of the dashboard that accepts the session password."""
        return logical[CLEAR_HEADER_LENGTH - 1:FrameOffset.DATA] == bytes((
            0, self._handshake_board, self._host_id,
            PacketOpcode.PING, PairingStatus.CONFIRMED,
        ))
