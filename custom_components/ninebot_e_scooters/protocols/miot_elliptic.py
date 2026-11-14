"""Xiaomi's "P4" scooter pairing: ECDH key exchange and AES-CCM confirmation.

Named and fully described, independently of any scooter this integration has
seen, by a peer-reviewed security paper: Casagrande, Cestaro, Losiouk, Conti
and Antonioli, "E-Spoofer: Attacking and Defending Xiaomi Electric Scooter
Ecosystem", WiSec '23 (DOI 10.1145/3558482.3590176). The paper names four
Xiaomi application-layer protocols found across all Xiaomi e-scooters from
2016 to 2021; P4, "ECDH and AES-CCM", is the one implemented here. Its Table 4
gives the exact command bytes of every step, reproduced below.

Pairing: the scooter advertises a pairable window for seventeen seconds after
its headlight button is held down (the paper's "unintentional pairing mode",
V2) — the same kind of physical confirmation this integration's own Ninebot
and Xiaomi 1S pairing already uses, not a cloud step. The scooter sends a
sixteen-byte challenge; an ECDH exchange on the NIST P-256 curve follows (both
sides' raw public points, fragmented over several GATT writes); then pk (a
pairing key) and otk (a one-time key) are derived from the shared secret, and
the app alone proves it derived the right otk — pairing authenticates the app
to the scooter, not the other way around (the paper's root cause V1,
"Unauthenticated Pairing": nothing here proves the pairer is the real Mi Home
app). Pairing has its own characteristic pair, 0x0019 for its unencrypted
commands and 0x0010 for its confirmation and the Session handshake after it —
independently corroborated, on hardware that is not a scooter, by three
unrelated public projects for other Xiaomi devices:
  https://github.com/haohaozi328-arch/miot-ble-sdk (the same two handles)
  https://github.com/clairefiorettiythzr6802-eng/xiaomi-diffuser-ble (the
    ECDH+HKDF shape and a 4-byte AES-CCM tag)
  https://github.com/kbpk/xiaomi-s400-homeassistant (names the P-256 curve
    explicitly; the same two 4-byte responses, 0x11000000/0x21000000)

What follows the named command bytes (exact fragment boundaries beyond the
documented "the fragment header adds 0x0010 each time" rule, which half of
the challenge each named fragment carries, and the AES-CCM nonce for the
app's one-shot proof) is this module's own best-effort reconstruction, not
confirmed by the paper; `runtime/flow_pairing.py`, the only caller, treats
any unexpected reply as a failure rather than guessing further. There is no
register map or entity for the property traffic Session would carry once
established (see `protocols/research.py`); a scooter paired this way is
recorded as paired, with a repair issue explaining that live data is not
supported yet, never with invented telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

MIOT_ELLIPTIC_PAIRING_CHARACTERISTIC = "00000019-0000-1000-8000-00805f9b34fb"
MIOT_ELLIPTIC_SESSION_CHARACTERISTIC = "00000010-0000-1000-8000-00805f9b34fb"
MIOT_ELLIPTIC_HANDLES: tuple[int, ...] = (0x0010, 0x0019, 0x001A)
MIOT_ELLIPTIC_CURVE = ec.SECP256R1()
# AES-CCM tag length every corroborating source agrees on.
MIOT_ELLIPTIC_TAG_LENGTH = 4
# The literal frame sync bytes of the encrypted channel Session opens.
MIOT_ELLIPTIC_FRAME_SYNC = b"\x55\xAB"
# The two HKDF info strings the paper names; Pairing and Session each use
# their own, so a key derived for one can never be replayed as the other.
MIOT_ELLIPTIC_PAIRING_INFO = b"mible-setup-info"
MIOT_ELLIPTIC_SESSION_INFO = b"mible-login-info"

# Every command byte the paper's Table 4 gives, under its own names. A
# fragmented write (PairPubKey, PairSol, SessSol) repeats with 0x0010 added
# each time ("00X0" in the paper); the fragment's own payload follows.
MIOT_PAIR_REQ = b"\xA2\x00\x00\x00"  # App -> Esc: start Pairing.
MIOT_PAIR_REQ_OK = b"\x00\x00\x00\x00\x02\x00"  # Esc -> App.
MIOT_PAIR_CHAL_1 = b"\x00\x10"  # Esc -> App, first half of chal; payload follows.
MIOT_PAIR_CHAL_2 = b"\x00\x20"  # Esc -> App, second half; payload follows.
MIOT_PAIR_EC_START = b"\x00\x00\x00\x03\x04\x00"  # App <-> Esc: begin the EC exchange.
MIOT_PAIR_PUB_KEY_FIRST_FRAGMENT = b"\x00\x00"  # App <-> Esc, a public-key fragment; payload follows.
MIOT_PAIR_EC_END = b"\x00\x00\x00\x00\x02\x00"  # App -> Esc: the EC exchange is complete.
MIOT_PAIR_SOL_FIRST_FRAGMENT = b"\x00\x00"  # App -> Esc, resp (the pairing solution) fragment; payload follows.
MIOT_PAIR_SOL_ACK = b"\x00\x00\x01\x00"  # Esc -> App.
MIOT_PAIR_OK = b"\x13\x00\x00\x00"  # App -> Esc: Pairing is confirmed.
MIOT_PAIR_OK_ACK = b"\x11\x00\x00\x00"  # Esc -> App.
MIOT_SESS_REQ_1 = b"\x24\x00\x00\x00"  # App -> Esc: start Session.
MIOT_SESS_REQ_2 = b"\x00\x00\x00\x0B\x01\x00"  # App -> Esc.
MIOT_SESS_RAND_HEADER = b"\x01\x00"  # App <-> Esc, carries a directional random; payload follows.
MIOT_SESS_ASK_RAND = b"\x00\x00\x00\x0C\x02\x00"  # Esc -> App.
MIOT_SESS_SOL_FIRST_FRAGMENT = b"\x00\x00"  # App <-> Esc, an HMAC (AuthSol) fragment; payload follows.
MIOT_SESS_OK = b"\x21\x00\x00\x00"  # App -> Esc: Session is confirmed.

# The byte length each fragmented value is split into on the wire, and the
# step the fragment header advances by between fragments (both from the
# paper's own "0x0010 added each time" description). Used to fragment this
# host's writes and to reassemble the scooter's own fragmented replies.
MIOT_ELLIPTIC_FRAGMENT_SIZE = 16
MIOT_ELLIPTIC_FRAGMENT_STEP = 0x0010


def miot_elliptic_generate_keypair() -> ec.EllipticCurvePrivateKey:
    """A fresh P-256 key pair for one ECDH exchange; never reused."""
    return ec.generate_private_key(MIOT_ELLIPTIC_CURVE)


def miot_elliptic_public_point(private_key: ec.EllipticCurvePrivateKey) -> bytes:
    """The 64-byte raw X||Y coordinate pair sent to the other side.

    Over the wire the leading 0x04 "uncompressed point" marker is dropped (it
    is implied, since this scheme only ever sends uncompressed points) and
    reconstructed on the receiving end; see miot_elliptic_load_peer_point.
    """
    encoded = private_key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return encoded[1:]


def miot_elliptic_load_peer_point(point: bytes) -> ec.EllipticCurvePublicKey:
    """Parse a 64-byte raw X||Y point as received over the wire."""
    return ec.EllipticCurvePublicKey.from_encoded_point(MIOT_ELLIPTIC_CURVE, b"\x04" + point)


def miot_elliptic_shared_secret(
    private_key: ec.EllipticCurvePrivateKey, peer_public_key: ec.EllipticCurvePublicKey
) -> bytes:
    """The raw ECDH secret; still needs HKDF before it is a session key."""
    return private_key.exchange(ec.ECDH(), peer_public_key)


def miot_elliptic_derive_pairing_keys(shared_secret: bytes) -> bytes:
    """HKDF-SHA256(ikm=shared secret, salt=b"", info="mible-setup-info"),
    32 bytes: the paper's pk (a pairing key, [0:16]) and otk (a one-time
    key, [16:32]), in that concatenation order ("pk||otk"); it does not
    state their exact byte length, 16 bytes each is this module's
    assumption, matching every AES-CCM-128 key elsewhere in the scheme.
    """
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=b"", info=MIOT_ELLIPTIC_PAIRING_INFO,
    ).derive(shared_secret)


def miot_elliptic_pairing_response(one_time_key: bytes, nonce: bytes, challenge: bytes) -> bytes:
    """resp=AES-CCM(key=otk, input=chal): the app's unilateral proof that it
    derived the same otk as the scooter, sent once during Pairing. Pairing
    authenticates the app to the scooter only, not the other way around —
    this is the paper's root cause V1, "Unauthenticated Pairing". The
    nonce is not named in the paper; this takes it as a parameter rather
    than guessing one.
    """
    return miot_elliptic_encrypt(one_time_key, nonce, challenge)


def miot_elliptic_derive_login_keys(pairing_key: bytes, host_nonce: bytes, device_nonce: bytes) -> bytes:
    """sk_esc||sk_app||n_esc||n_app=HKDF(key=pk, salt=rand_app||rand_esc,
    info="mible-login-info"): pairing_key is pk, the first half of
    miot_elliptic_derive_pairing_keys' output, not the raw ECDH secret —
    Session happens after Pairing has already produced pk. 40 bytes: a
    16-byte key to verify what the device sends, a 16-byte key for what
    this host sends, then two 4-byte values that each become half of a
    per-direction AES-CCM nonce. Split with miot_elliptic_session_keys
    below rather than by hand.
    """
    return HKDF(
        algorithm=hashes.SHA256(), length=40, salt=host_nonce + device_nonce, info=MIOT_ELLIPTIC_SESSION_INFO,
    ).derive(pairing_key)


@dataclass(frozen=True, slots=True)
class MiotEllipticSession:
    """One direction's key and nonce seed, named from this host's view."""

    receive_key: bytes  # Verifies and decrypts what the device sends.
    receive_nonce_seed: bytes
    send_key: bytes  # Encrypts what this host sends.
    send_nonce_seed: bytes


def miot_elliptic_session_keys(login_keys: bytes) -> MiotEllipticSession:
    """Split the 40-byte HKDF output into the four values a session needs."""
    return MiotEllipticSession(
        receive_key=login_keys[0:16], send_key=login_keys[16:32],
        receive_nonce_seed=login_keys[32:36], send_nonce_seed=login_keys[36:40],
    )


def miot_elliptic_confirmation_tag(key: bytes, device_nonce: bytes, host_nonce: bytes) -> bytes:
    """HMAC-SHA256(key, device_nonce+host_nonce): both sides compute this
    once with each of the two derived keys and compare, proving each side
    reached the same shared secret before any property traffic is trusted.
    """
    h = hmac.HMAC(key, hashes.SHA256())
    h.update(device_nonce + host_nonce)
    return h.finalize()


def miot_elliptic_checksum(data: bytes) -> bytes:
    """One's-complement 16-bit sum, little-endian: the same family of
    checksum nootnooot documents for the plain Ninebot frames this
    integration's other adapters already use, not something specific to
    this scheme."""
    return (~sum(data) & 0xFFFF).to_bytes(2, "little")


def miot_elliptic_data_nonce(nonce_seed: bytes, sequence: int) -> bytes:
    """The 12-byte AES-CCM nonce for one encrypted data-channel frame: the
    4-byte per-direction seed from miot_elliptic_session_keys, four zero
    bytes, then the frame's own 2-byte little-endian sequence number and two
    more zero bytes. sequence wraps at 16 bits, matching the frame field.
    """
    if not 0 <= sequence <= 0xFFFF:
        raise ValueError("sequence must fit the frame's 16-bit field")
    return nonce_seed + b"\x00\x00\x00\x00" + sequence.to_bytes(2, "little") + b"\x00\x00"


def miot_elliptic_encrypt(key: bytes, nonce: bytes, plaintext: bytes) -> bytes:
    """AES-CCM, the 4-byte tag every corroborating source agrees on."""
    return AESCCM(key, tag_length=MIOT_ELLIPTIC_TAG_LENGTH).encrypt(nonce, plaintext, None)


def miot_elliptic_decrypt(key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    """The matching decrypt; raises InvalidTag on a wrong key or a tampered frame."""
    return AESCCM(key, tag_length=MIOT_ELLIPTIC_TAG_LENGTH).decrypt(nonce, ciphertext, None)


def miot_elliptic_build_data_frame(session: MiotEllipticSession, sequence: int, header: bytes, payload: bytes) -> bytes:
    """One complete encrypted data-channel frame: sync, length, sequence,
    AES-CCM(header+payload) with this direction's key and nonce, checksum.
    header is the 3-byte sub-header the plaintext carries ahead of payload;
    its meaning (target, command, ...) is not confirmed and not guessed at
    here. No caller builds this yet: there is no register map for the
    property traffic it would carry.
    """
    plaintext = header + payload
    body = sequence.to_bytes(2, "little") + miot_elliptic_encrypt(
        session.send_key, miot_elliptic_data_nonce(session.send_nonce_seed, sequence), plaintext,
    )
    frame = MIOT_ELLIPTIC_FRAME_SYNC + bytes((len(plaintext) - 1,)) + body
    return frame + miot_elliptic_checksum(frame[2:])


def miot_elliptic_parse_data_frame(session: MiotEllipticSession, frame: bytes) -> bytes:
    """The inverse of miot_elliptic_build_data_frame: verifies the checksum,
    decrypts with this direction's receive key and nonce, and returns the
    plaintext (header+payload together, undivided). Raises ValueError on a
    bad sync or checksum, InvalidTag on a wrong key or a tampered frame.
    """
    if frame[:2] != MIOT_ELLIPTIC_FRAME_SYNC:
        raise ValueError("not a MIoT elliptic data frame")
    if miot_elliptic_checksum(frame[2:-2]) != frame[-2:]:
        raise ValueError("checksum mismatch")
    sequence = int.from_bytes(frame[3:5], "little")
    nonce = miot_elliptic_data_nonce(session.receive_nonce_seed, sequence)
    return miot_elliptic_decrypt(session.receive_key, nonce, frame[5:-2])


def miot_elliptic_fragment(payload: bytes) -> tuple[bytes, ...]:
    """Split a value into the 16-byte-chunk, 0x0010-stepped fragments this
    scheme writes a long value as (a public point, the pairing response):
    each fragment is a big-endian 16-bit offset followed by up to 16 bytes
    of payload, the last fragment shorter if the length is not a multiple
    of 16. The exact header width is confirmed by the paper only for the
    first fragment (MIOT_PAIR_PUB_KEY_FIRST_FRAGMENT, 2 bytes); this module
    assumes every later one keeps the same width and simply counts up by
    MIOT_ELLIPTIC_FRAGMENT_STEP, per the paper's own "0x0010 added each
    time" description.
    """
    return tuple(
        offset.to_bytes(2, "big") + payload[offset:offset + MIOT_ELLIPTIC_FRAGMENT_SIZE]
        for offset in range(0, len(payload), MIOT_ELLIPTIC_FRAGMENT_SIZE)
    )
