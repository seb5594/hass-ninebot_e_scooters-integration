"""Ninebot/Xiaomi legacy BLE crypto used by BLE129/BLE132."""

from __future__ import annotations

import hashlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from ...protocols.ninebot.packet import (
    BLE129_APP_KEY_LENGTH,
    BLE129_INIT_REPLY_LENGTH,
    DeviceId,
    ENCRYPTED_TRAILER_LENGTH,
    HEADER as NINEBOT_HEADER,
    PacketOpcode,
    PairingStatus,
)

FW_DATA = bytes.fromhex("97 CF B8 02 84 41 43 DE 56 00 2B 3B 34 78 0A 5D")
HEADER = NINEBOT_HEADER
CRYPTO_ENVELOPE_BYTES = len(HEADER) + 1 + ENCRYPTED_TRAILER_LENGTH
# These are decrypted logical-frame prefixes. The lengths are payload bytes,
# not the encrypted frame lengths or the legacy serial checksum bytes.
BLE129_INIT_REPLY_PREFIX = HEADER + bytes((
    BLE129_INIT_REPLY_LENGTH, DeviceId.DASHBOARD, DeviceId.PHONE, PacketOpcode.INIT,
))
BLE129_PING_CONFIRMED_PREFIX = HEADER + bytes((
    0, DeviceId.DASHBOARD, DeviceId.PHONE, PacketOpcode.PING, PairingStatus.CONFIRMED,
))
BLE129_PING_REQUEST_PREFIX = HEADER + bytes((
    BLE129_APP_KEY_LENGTH, DeviceId.PHONE, DeviceId.DASHBOARD, PacketOpcode.PING, PairingStatus.PENDING,
))


def _aes_ecb(data: bytes, key: bytes) -> bytes:
    """Encrypt one 16-byte block using AES-128 ECB."""
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(data) + encryptor.finalize()


def _xor16(left: bytes, right: bytes) -> bytes:
    """XOR two 16-byte blocks."""
    return bytes(a ^ b for a, b in zip(left, right, strict=True))


class NinebotCrypto:
    """Stateful NinebotCrypto implementation."""

    def __init__(self, name: str, *, host_id: DeviceId = DeviceId.PHONE) -> None:
        """Initialize the crypto state."""
        self._name = name.encode("utf-8", errors="ignore")[:16].ljust(16, b"\x00")
        self._random_ble_data = bytes(16)
        self._random_app_data = bytes(16)
        self._sha1_key = self._calc_sha1_key(self._name, FW_DATA)
        self._msg_it = 0
        if host_id not in (DeviceId.PHONE, DeviceId.PC):
            raise ValueError("A crypto session requires a phone or PC host address")
        self._host_id = host_id
        self.last_rejection_reason: str | None = None

    @staticmethod
    def _calc_sha1_key(data1: bytes, data2: bytes) -> bytes:
        """Calculate the first 16 bytes of SHA1(data1 + data2)."""
        return hashlib.sha1(data1[:16] + data2[:16]).digest()[:16]

    @property
    def message_counter(self) -> int:
        """Return the current crypto message counter."""
        return self._msg_it

    def _crypto_first(self, data: bytes) -> bytes:
        """Apply the first-session crypto operation."""
        result = bytearray(len(data))
        for offset in range(0, len(data), 16):
            chunk = data[offset:offset + 16]
            stream = _aes_ecb(FW_DATA, self._sha1_key)
            result[offset:offset + len(chunk)] = _xor16(
                chunk.ljust(16, b"\x00"), stream
            )[:len(chunk)]
        return bytes(result)

    def _crypto_next(self, data: bytes, msg_it: int) -> bytes:
        """Apply the chained crypto operation."""
        result = bytearray(len(data))
        aes_enc_data = bytearray(16)
        aes_enc_data[0] = 1
        aes_enc_data[1:5] = msg_it.to_bytes(4, "big")
        aes_enc_data[5:13] = self._random_ble_data[:8]
        for block_number, offset in enumerate(range(0, len(data), 16), start=1):
            aes_enc_data[15] = block_number
            chunk = data[offset:offset + 16]
            stream = _aes_ecb(bytes(aes_enc_data), self._sha1_key)
            result[offset:offset + len(chunk)] = _xor16(
                chunk.ljust(16, b"\x00"), stream
            )[:len(chunk)]
        return bytes(result)

    @staticmethod
    def _crc_first(data: bytes) -> bytes:
        """Calculate the first-message CRC."""
        return ((~sum(data)) & 0xFFFF).to_bytes(2, "little")

    def _crc_next(self, data: bytes, msg_it: int) -> bytes:
        """Calculate the chained-message CRC."""
        payload_len = len(data) - 3
        byte_idx = 3
        aes_enc_data = bytearray(16)
        aes_enc_data[0] = 0x59
        aes_enc_data[1:5] = msg_it.to_bytes(4, "big")
        aes_enc_data[5:13] = self._random_ble_data[:8]
        aes_enc_data[15] = payload_len

        xor_data_2 = _aes_ecb(bytes(aes_enc_data), self._sha1_key)
        xor_data_1 = data[:3].ljust(16, b"\x00")
        xor_data_2 = _aes_ecb(_xor16(xor_data_1, xor_data_2), self._sha1_key)

        remaining = payload_len
        while remaining > 0:
            chunk_len = min(remaining, 16)
            chunk = data[byte_idx:byte_idx + chunk_len]
            xor_data_2 = _aes_ecb(
                _xor16(chunk.ljust(16, b"\x00"), xor_data_2),
                self._sha1_key,
            )
            remaining -= chunk_len
            byte_idx += chunk_len

        aes_enc_data[0] = 1
        aes_enc_data[15] = 0
        xor_data_1 = _aes_ecb(bytes(aes_enc_data), self._sha1_key)
        return _xor16(xor_data_1, xor_data_2)[:4]

    def decrypt(self, data: bytes) -> bytes | None:
        """Decrypt a complete Ninebot encrypted frame."""
        self.last_rejection_reason = None
        if len(data) < CRYPTO_ENVELOPE_BYTES or data[:len(HEADER)] != HEADER:
            self.last_rejection_reason = "invalid_header_or_short_frame"
            return None

        decrypted = bytearray(len(data) - ENCRYPTED_TRAILER_LENGTH)
        decrypted[:3] = data[:3]
        new_msg_it = self._msg_it
        if (new_msg_it & 0x00008000) and (data[-2] >> 7) == 0:
            new_msg_it += 0x00010000
        new_msg_it = (new_msg_it & 0xFFFF0000) + (data[-2] << 8) + data[-1]

        payload_len = len(data) - CRYPTO_ENVELOPE_BYTES
        payload = data[3:3 + payload_len]

        if new_msg_it == 0:
            payload = self._crypto_first(payload)
            decrypted[3:3 + payload_len] = payload
            # NinebotCrypto's upstream decrypt does not authenticate incoming
            # frames. An incomplete/misaligned notification can otherwise be
            # mistaken for a high counter and permanently poison this session.
            # First packets use a 16-bit inverted sum in trailer bytes -4:-2.
            if self._crc_first(payload) != data[-4:-2]:
                self.last_rejection_reason = "first_frame_crc_or_name"
                return None
            if (decrypted[2] == BLE129_INIT_REPLY_LENGTH
                    and decrypted[3:6] == bytes((DeviceId.DASHBOARD, self._host_id, PacketOpcode.INIT))):
                self._random_ble_data = bytes(decrypted[7:23])
                self._sha1_key = self._calc_sha1_key(self._name, self._random_ble_data)
            return bytes(decrypted)

        if new_msg_it <= self._msg_it:
            self.last_rejection_reason = "old_or_replayed_counter"
            return None

        payload = self._crypto_next(payload, new_msg_it)
        decrypted[3:3 + payload_len] = payload
        # Verify the AES-derived 4-byte integrity tag with the candidate
        # counter BEFORE switching the pairing key or committing that counter.
        # Do not impose an arbitrary max counter: a valid high counter or an
        # actual 16-bit rollover must still work.
        if self._crc_next(bytes(decrypted), new_msg_it) != data[-6:-2]:
            self.last_rejection_reason = "chained_frame_integrity"
            return None
        if decrypted[:7] == HEADER + bytes((0, DeviceId.DASHBOARD, self._host_id, PacketOpcode.PING, PairingStatus.CONFIRMED)):
            self._sha1_key = self._calc_sha1_key(
                self._random_app_data, self._random_ble_data
            )
        self._msg_it = new_msg_it
        return bytes(decrypted)

    def encrypt(self, data: bytes) -> bytes:
        """Encrypt a complete logical Ninebot packet."""
        if len(data) < 3 or data[:2] != HEADER:
            raise ValueError("Ninebot packet must start with 5A A5")

        encrypted = bytearray(len(data) + ENCRYPTED_TRAILER_LENGTH)
        encrypted[:3] = data[:3]
        payload = data[3:]

        if self._msg_it == 0:
            crc = self._crc_first(payload)
            payload = self._crypto_first(payload)
            encrypted[3:3 + len(payload)] = payload
            encrypted[len(data):len(data) + 2] = b"\x00\x00"
            encrypted[len(data) + 2:len(data) + 4] = crc
            encrypted[len(data) + 4:len(data) + 6] = b"\x00\x00"
            self._msg_it += 1
            return bytes(encrypted)

        self._msg_it += 1
        crc = self._crc_next(data, self._msg_it)
        payload = self._crypto_next(payload, self._msg_it)
        encrypted[3:3 + len(payload)] = payload
        encrypted[len(data):len(data) + 4] = crc
        encrypted[len(data) + 4:len(data) + 6] = (self._msg_it & 0xFFFF).to_bytes(2, "big")

        if data[:7] == HEADER + bytes((BLE129_APP_KEY_LENGTH, self._host_id, DeviceId.DASHBOARD, PacketOpcode.PING, PairingStatus.PENDING)):
            self._random_app_data = data[7:23]

        return bytes(encrypted)
