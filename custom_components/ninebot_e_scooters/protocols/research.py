"""Inert research catalog for possible scooter adapters.

Nothing in this module is imported by discovery, pairing, polling, entities or
controls. Each record is a candidate for a future, separately tested adapter;
it does not establish compatibility with an existing one. Families that have
an adapter are described in models/transports.py instead.

Sources: https://github.com/ownbee/ninebot-ble/tree/main/ninebot_ble
         https://github.com/dnandha/miauth (and the miauth 0.9.7 release)
         https://github.com/scooterhacking/NinebotCrypto
         https://wiki.scooterhacking.org/doku.php?id=nbdocs
         https://nootnooot.codeberg.page/segway-ninebot-ble/ (device tables)
         ScooterHacking Utility (https://utility.cfw.sh/), for the MIoT BLE
         Spec v2 section below; its wire format is independently
         corroborated by unrelated public projects for other Xiaomi
         ecosystem devices, none of them scooters
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


@dataclass(frozen=True, slots=True)
class ProtocolCandidate:
    """Describe a protocol to investigate, without enabling an adapter."""

    family: str
    frame_prefix: str
    authentication: str
    known_ble_versions: tuple[str, ...]
    gatt_transport: str
    adapter_implemented: bool = False


# BLE versions indicate reported examples, not a complete compatibility list.
# 5A AB and 55 AB are different packet prefixes; neither is Ninebot 5A A5.
PROTOCOL_CANDIDATES: tuple[ProtocolCandidate, ...] = (
    ProtocolCandidate("xiaomi_ble132_nb", "5A A5", "ninebot_chained", ("BLE132",), "nordic_uart"),
    ProtocolCandidate("xiaomi_ble132_5aab", "5A AB", "to_be_verified", ("BLE132",), "to_be_verified"),
    # The handshake itself is a sequence of small, unencrypted GATT writes;
    # "55 AB" is the sync of the encrypted frame that carries property
    # traffic once it succeeds. See the MIoT BLE Spec v2 section below.
    ProtocolCandidate("xiaomi_mi_ec", "55 AB", "ecdh_hkdf_aes_ccm", (), "to_be_verified"),
    # F2, F2 Plus, F2 Pro, E2, E2 Plus and E2 Pro: the vendor device table
    # lists them with XOR-obfuscated frames instead of the chained crypto.
    ProtocolCandidate("ninebot_f2_e2", "5A A5", "xor_obfuscation", (), "to_be_verified"),
    # GT1, GT2, P65 and P100S: same chained crypto, but two motors and an
    # unknown register layout.
    ProtocolCandidate("segway_gt_p", "5A A5", "ninebot_chained", (), "ninebot_uart"),
    # ZT3 Pro and GT3 number their boards like the F3, but their registers
    # have not been compared with it.
    ProtocolCandidate("segway_zt3_gt3", "5A A5", "ninebot_chained", (), "nordic_uart"),
    # Described in the public documentation without naming a scooter: the
    # first key starts from a zero block instead of the firmware constant.
    ProtocolCandidate("segway_zero_seed", "5A A5", "ninebot_chained_zero_seed", (), "to_be_verified"),
)


@dataclass(frozen=True, slots=True)
class RegisterCandidate:
    """Record a potential future read without performing any I/O."""

    target: int
    index: int
    label: str
    words: int = 1
    kind: str = "dynamic"
    note: str = ""


# From ownbee/ninebot-ble register.py. Target 0x20 is the controller and 0x22
# the BMS; most reads request two bytes per word. Shapes and scale factors
# must be verified per scooter before adding entities. Never expose 0x17
# (Bluetooth password) as an entity or through diagnostics.
NINEBOT_READ_CANDIDATES: tuple[RegisterCandidate, ...] = (
    RegisterCandidate(0x20, 0x10, "controller_serial", 7, "static", "Read seven adjacent 2-byte words."),
    RegisterCandidate(0x20, 0x1A, "controller_firmware", kind="static"),
    RegisterCandidate(0x20, 0x1B, "controller_error_code"),
    RegisterCandidate(0x20, 0x1C, "controller_alarm_code"),
    RegisterCandidate(0x20, 0x1D, "controller_status_bits", note="Bit 1 is a lock hint; validate per model."),
    RegisterCandidate(0x20, 0x29, "total_distance", 2, "slow", "Two words; source scales by 1/1000 km."),
    RegisterCandidate(0x20, 0x32, "total_operation_time", 2, "slow"),
    RegisterCandidate(0x20, 0x34, "total_riding_time", 2, "slow"),
    RegisterCandidate(0x20, 0x3E, "controller_temperature", note="Signedness must be validated."),
    RegisterCandidate(0x20, 0x47, "controller_voltage"),
    RegisterCandidate(0x20, 0x68, "ble_firmware", kind="static"),
    RegisterCandidate(0x20, 0x75, "operation_mode", note="Do not reuse Xiaomi 1S mode values."),
    RegisterCandidate(0x20, 0x7B, "kers_level"),
    RegisterCandidate(0x20, 0x7C, "cruise_state"),
    RegisterCandidate(0x20, 0x7D, "rear_light_state"),
    RegisterCandidate(0x22, 0x10, "bms_serial", 7, "static"),
    RegisterCandidate(0x22, 0x17, "bms_firmware", kind="static"),
    RegisterCandidate(
        0x22, 0x20, "battery_manufacture_date", kind="static",
        note="M365 BMS stores a packed battery date; verify the epoch per model before decoding.",
    ),
    RegisterCandidate(0x22, 0x31, "remaining_battery_capacity"),
    RegisterCandidate(0x22, 0x32, "battery_charge_percent"),
    RegisterCandidate(0x22, 0x33, "battery_current", note="Signed 16-bit; source scales by 1/100 A."),
    RegisterCandidate(0x22, 0x34, "battery_voltage", note="Source scales by 1/100 V."),
    RegisterCandidate(0x22, 0x35, "battery_temperatures", note="Two temperatures share one 16-bit word."),
    RegisterCandidate(0x22, 0x3B, "battery_health"),
)


# --- xiaomi_mi_ec: MIoT BLE Spec v2 primitives, for study only ---------------
#
# A GATT-connected scheme Xiaomi uses across its IoT line (sensors, a body
# scale, buttons, lights): an ECDH key exchange on the NIST P-256 curve,
# session keys from HKDF-SHA256 over the shared secret, and AES-CCM for the
# encrypted channel. No scooter is confirmed to speak it.
#
# ScooterHacking Utility (https://utility.cfw.sh/, v2.7 of its Android build)
# implements this scheme for the newer Xiaomi generations it supports, on the
# shared MiBeacon service (0000fe95-...) the rest of this file also uses, over
# two characteristics: 00000019-... carries the ECDH register exchange and
# the paired-key confirmation, 00000010-... carries the login and the
# property traffic that follows. Three independent, unrelated public
# projects for non-scooter Xiaomi hardware corroborate the shape:
#   https://github.com/haohaozi328-arch/miot-ble-sdk (ten-plus sensors, a
#     button and a body scale; the same two handles; "REGISTER COMPLETE
#     (result 0x11 on 0x0010)" and "STD LOGIN COMPLETE (0x21 on 0x0010)")
#   https://github.com/clairefiorettiythzr6802-eng/xiaomi-diffuser-ble (the
#     ECDH+HKDF shape and a 4-byte AES-CCM tag, on a Mijia smart diffuser)
#   https://github.com/kbpk/xiaomi-s400-homeassistant (names the P-256 curve
#     explicitly; the same two 4-byte responses, 0x11000000/0x21000000)
# Home Assistant's own https://www.home-assistant.io/integrations/xiaomi_ble/
# documents the paired key these devices need as a "bindkey" or "beaconkey":
# 12 bytes for the older MiBeacon v2/v3 devices, 16 bytes for v4/v5, normally
# read from a signed-in Xiaomi account. None of the sources above say how a
# scooter would obtain one.
#
# The encrypted channel rides over the same Nordic UART characteristics the
# plain, unencrypted scheme already on this service uses; only the register
# and login exchange has its own pair. The one credential bundle a device
# needs, once obtained, is kept locally keyed by the scooter's Bluetooth MAC
# address, not by anything that would identify its model.
#
# This integration has no Xiaomi account sign-in and no way to obtain that
# key, so none of this is reachable from a live session: a correct ECDH
# exchange with no key to finish authenticating would just as surely stay
# empty as a model nobody has looked at. These are the primitives and the
# frame shape the scheme is built from, written once so a future,
# hardware-tested adapter does not have to look them up again.

MIOT_ELLIPTIC_AUTH_CHARACTERISTIC = "00000019-0000-1000-8000-00805f9b34fb"
MIOT_ELLIPTIC_CONTROL_CHARACTERISTIC = "00000010-0000-1000-8000-00805f9b34fb"
MIOT_ELLIPTIC_HANDLES: tuple[int, ...] = (0x0010, 0x0019, 0x001A)
MIOT_ELLIPTIC_REGISTER_OK = b"\x11\x00\x00\x00"
MIOT_ELLIPTIC_LOGIN_OK = b"\x21\x00\x00\x00"
MIOT_ELLIPTIC_CURVE = ec.SECP256R1()
# AES-CCM tag length every corroborating source agrees on.
MIOT_ELLIPTIC_TAG_LENGTH = 4
# The literal frame sync bytes of the encrypted channel that follows login.
MIOT_ELLIPTIC_FRAME_SYNC = b"\x55\xAB"


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


def miot_elliptic_derive_login_keys(shared_secret: bytes, host_nonce: bytes, device_nonce: bytes) -> bytes:
    """HKDF-SHA256(ikm=shared secret, salt=device_nonce+host_nonce,
    info="mible-login-info") over the ECDH secret, 40 bytes: a 16-byte key to
    verify what the device sends, a 16-byte key for what this host sends,
    then two 4-byte values that each become half of a per-direction AES-CCM
    nonce. Split with miot_elliptic_session_keys below rather than by hand.
    """
    return HKDF(
        algorithm=hashes.SHA256(), length=40, salt=device_nonce + host_nonce, info=b"mible-login-info",
    ).derive(shared_secret)


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
    checksum nootnooot documents for the plain Ninebot frames this file's
    other candidates already use, not something specific to this scheme."""
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
    here.
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
