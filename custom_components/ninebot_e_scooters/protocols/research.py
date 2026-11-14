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
         MIoT BLE Spec v2, documented independently by unrelated public
         projects for other Xiaomi ecosystem devices, none of them scooters
         (see the MiotElliptic section below for the exact sources)
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
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
    # Not a fixed byte-prefixed stream: a sequence of 4-byte little-endian
    # opcodes written to a GATT handle. See MiotElliptic below.
    ProtocolCandidate("xiaomi_mi_ec", "", "ecdh_hkdf_aes_ccm", (), "to_be_verified"),
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
# encrypted channel. It does not need the fixed "55 AB" byte prefix the
# family name above was first filed under; that was a mix-up with the older,
# plain Xiaomi serial stream. No scooter is confirmed to speak it.
#
# Three independent, unrelated public projects document it on hardware that
# is not a scooter, and agree on the parts recorded here:
#   https://github.com/haohaozi328-arch/miot-ble-sdk
#     (commit 90dd918fb82f565329c37c0ccd51b2fefd58e2e0) binds and logs in to
#     ten-plus Xiaomi sensors, buttons and a body scale over GATT handles
#     0x0010, 0x0019 and 0x001A, and logs "REGISTER COMPLETE (result 0x11 on
#     0x0010)" and "STD LOGIN COMPLETE (0x21 on 0x0010)".
#   https://github.com/clairefiorettiythzr6802-eng/xiaomi-diffuser-ble
#     (commit 96268a53e3c8ba4443dd322ecaede606ec7c89c6) names the ECDH+HKDF
#     shape, a 4-byte AES-CCM tag, and a login request of 0x50 0x00 0x00 0x00
#     (replacing an older 0x20) on the Mijia smart diffuser.
#   https://github.com/kbpk/xiaomi-s400-homeassistant
#     (commit 60569f5826658c9bab617a0d9f2c86988ca48fa2) names the P-256 curve
#     explicitly for its body scale and reads the same two responses as
#     4-byte frames: 0x11000000 for a successful register, 0x21000000 for a
#     successful login.
# Home Assistant's own https://www.home-assistant.io/integrations/xiaomi_ble/
# documents the paired key these devices need as a "bindkey" or "beaconkey":
# 12 bytes (24 hex characters) for the older MiBeacon v2/v3 devices, 16 bytes
# (32 hex characters) for v4/v5. None of the three projects above say how a
# scooter would obtain one; likely the same way, through a Xiaomi account.
#
# This integration has no Xiaomi account sign-in and no way to obtain that
# key, so none of this is reachable from a live session: a correct ECDH
# exchange with no key to finish authenticating would just as surely stay
# empty as a model nobody has looked at. These are the standard primitives
# the scheme is built from (curve, KDF, cipher), written once so a future,
# hardware-tested adapter does not have to look them up again.

MIOT_ELLIPTIC_HANDLES: tuple[int, ...] = (0x0010, 0x0019, 0x001A)
MIOT_ELLIPTIC_REGISTER_OK = b"\x11\x00\x00\x00"
MIOT_ELLIPTIC_LOGIN_OK = b"\x21\x00\x00\x00"
MIOT_ELLIPTIC_CURVE = ec.SECP256R1()


def miot_elliptic_generate_keypair() -> ec.EllipticCurvePrivateKey:
    """A fresh P-256 key pair for one ECDH exchange; never reused."""
    return ec.generate_private_key(MIOT_ELLIPTIC_CURVE)


def miot_elliptic_public_bytes(private_key: ec.EllipticCurvePrivateKey) -> bytes:
    """The uncompressed point (0x04 || X || Y) sent to the other side."""
    return private_key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)


def miot_elliptic_load_peer_public_key(point: bytes) -> ec.EllipticCurvePublicKey:
    """Parse the peer's uncompressed point; raises on a malformed one."""
    return ec.EllipticCurvePublicKey.from_encoded_point(MIOT_ELLIPTIC_CURVE, point)


def miot_elliptic_shared_secret(
    private_key: ec.EllipticCurvePrivateKey, peer_public_key: ec.EllipticCurvePublicKey
) -> bytes:
    """The raw ECDH secret; still needs HKDF before it is a session key."""
    return private_key.exchange(ec.ECDH(), peer_public_key)


def miot_elliptic_derive_key(
    shared_secret: bytes, salt: bytes, info: bytes, length: int
) -> bytes:
    """HKDF-SHA256 over the shared secret; the published salt and info
    strings are specific to the diffuser's login and not claimed here for
    any scooter."""
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(shared_secret)


def miot_elliptic_encrypt(key: bytes, nonce: bytes, data: bytes, associated_data: bytes = b"") -> bytes:
    """AES-CCM with the 4-byte tag the diffuser project reports."""
    return AESCCM(key, tag_length=4).encrypt(nonce, data, associated_data)


def miot_elliptic_decrypt(key: bytes, nonce: bytes, data: bytes, associated_data: bytes = b"") -> bytes:
    """The matching decrypt; raises InvalidTag on a wrong key or a tampered frame."""
    return AESCCM(key, tag_length=4).decrypt(nonce, data, associated_data)
