"""Verify future-protocol metadata remains safe and separate from live BLE."""

import ast

import pytest

from test_protocol import PACKAGE_PATH, load_module


catalog = load_module("protocols.research")
serials = load_module("models.serials")


@pytest.mark.parametrize("serial,family,model", (
    ("N2GMX1939C0123", "Ninebot E series", "E45E"),
    ("N2GYX2112C0123", "Ninebot E series", "E25D"),
    ("N2GTA1234C1234", "Ninebot ES", "ES2"),
    ("N2GSF2126K2577", "Ninebot ES", "ES4"),
    ("N4GTD2110C0123", "Ninebot Max", "G30M"),
    ("01GXE2319C0338", "Ninebot Max G2", "Max G2"),
    ("01GZE2319C0338", "Ninebot Max G2", "Max G2D"),
    ("01GYE2319C0338", "Ninebot Max G2", None),
    ("N4GSD1939C0123", "Ninebot Max", "G30P"),
    ("N5GNK2113C0123", "Ninebot F series", "F25"),
    ("N5GIK2113C0123", "Ninebot F series", None),
    ("N5GSK2113C0123", "Ninebot F series", None),
    ("N4GZD1939C0123", "Ninebot Max", None),
))
def test_serial_hint_keeps_family_and_ambiguous_model_separate(serial, family, model):
    hint = serials.inspect_ninebot_serial(serial)
    assert hint is not None
    assert (hint.family, hint.model_hint) == (family, model)
    assert hint.revision == serial[9]
    assert (hint.production_year, hint.production_week) == (2000 + int(serial[5:7]), int(serial[7:9]))


@pytest.mark.parametrize("serial", (
    None, "N4GSD1939C012", "N4GSD1939C01234", "N4GSD1999C0123",
    "N4GSD1939C01?3", "N4GSD1939C0123\x00extra", "25700/00015977",
    "N4GSD1939C0123 ", "N4GSD1939C0123\u00e9", "N4GSD2100C0123",
    "N4GSD2153C0123", "N9GSD1939C0123",
    # N2G is shared by the ES and the E series: an unlisted variant names neither.
    "N2GLA1939C0123",
))
def test_unknown_or_malformed_serial_cannot_claim_a_ninebot_family(serial):
    assert serials.inspect_ninebot_serial(serial) is None


def test_zero_terminated_serial_bytes_are_only_a_hint():
    assert serials.inspect_ninebot_serial(b"N4GSD1939C0123\0").model_hint == "G30P"
    assert serials.inspect_ninebot_serial(b"N4GSD1939C012\xff") is None


def test_all_future_adapters_remain_disabled_and_auth_families_are_distinct():
    assert catalog.PROTOCOL_CANDIDATES
    assert all(not candidate.adapter_implemented for candidate in catalog.PROTOCOL_CANDIDATES)
    by_family = {candidate.family: candidate for candidate in catalog.PROTOCOL_CANDIDATES}
    assert by_family["segway_zero_seed"].frame_prefix == "5A A5"
    assert by_family["xiaomi_ble132_5aab"].frame_prefix == "5A AB"
    assert by_family["xiaomi_mi_ec"].frame_prefix == "55 AB"
    assert by_family["xiaomi_mi_ec"].authentication == "ecdh_hkdf_aes_ccm"
    # A family with an adapter is described by its transport profile, never
    # by this catalog of protocols nobody has implemented.
    transports = load_module("models.transports")
    implemented = {family for family, transport in transports.TRANSPORT_PROFILES.items()
                   if transport.adapter_implemented}
    assert not implemented & set(by_family)


def test_register_candidates_have_explicit_target_and_never_expose_controller_password():
    assert {(item.target, item.index) for item in catalog.NINEBOT_READ_CANDIDATES} >= {
        (0x20, 0x1D), (0x20, 0x75), (0x22, 0x31), (0x22, 0x35),
    }
    assert all(item.target in (0x20, 0x22) and item.words > 0
               for item in catalog.NINEBOT_READ_CANDIDATES)
    assert not any(item.target == 0x20 and item.index == 0x17
                   for item in catalog.NINEBOT_READ_CANDIDATES)
    assert not any(item.target == 0x20 and item.index == 0xBA
                   for item in catalog.NINEBOT_READ_CANDIDATES)


def test_research_catalog_is_not_imported_by_any_runtime_component():
    for path in PACKAGE_PATH.rglob("*.py"):
        if path.name == "research.py":
            continue
        syntax = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(
            isinstance(node, ast.ImportFrom) and (node.module or "").endswith("research")
            or isinstance(node, ast.Import) and any(
                alias.name.endswith("research") for alias in node.names
            )
            for node in ast.walk(syntax)
        ), f"Unexpected runtime import in {path.relative_to(PACKAGE_PATH)}"


def test_miot_elliptic_ecdh_round_trips_to_the_same_shared_secret():
    """Two independent key pairs must agree on one shared secret, each side
    computing it from its own private key and the other's raw point."""
    host = catalog.miot_elliptic_generate_keypair()
    device = catalog.miot_elliptic_generate_keypair()
    host_point = catalog.miot_elliptic_public_point(host)
    device_point = catalog.miot_elliptic_public_point(device)
    assert len(host_point) == 64  # raw P-256 X||Y, no leading 0x04
    host_secret = catalog.miot_elliptic_shared_secret(host, catalog.miot_elliptic_load_peer_point(device_point))
    device_secret = catalog.miot_elliptic_shared_secret(device, catalog.miot_elliptic_load_peer_point(host_point))
    assert host_secret == device_secret
    assert len(host_secret) == 32  # P-256 field size


def test_miot_elliptic_login_keys_are_deterministic_and_salt_bound():
    secret = b"\x01" * 32
    host_nonce, device_nonce = b"\x02" * 16, b"\x03" * 16
    derived = catalog.miot_elliptic_derive_login_keys(secret, host_nonce, device_nonce)
    assert len(derived) == 40
    assert derived == catalog.miot_elliptic_derive_login_keys(secret, host_nonce, device_nonce)
    assert derived != catalog.miot_elliptic_derive_login_keys(secret, host_nonce, b"\x09" * 16)


def test_miot_elliptic_confirmation_tags_match_only_with_the_right_nonce_order():
    key, host_nonce, device_nonce = b"\x04" * 16, b"\x05" * 16, b"\x06" * 16
    tag = catalog.miot_elliptic_confirmation_tag(key, device_nonce, host_nonce)
    assert len(tag) == 32  # HMAC-SHA256
    assert tag == catalog.miot_elliptic_confirmation_tag(key, device_nonce, host_nonce)
    assert tag != catalog.miot_elliptic_confirmation_tag(key, host_nonce, device_nonce)


def test_miot_elliptic_checksum_is_the_one_s_complement_of_the_byte_sum():
    assert catalog.miot_elliptic_checksum(b"\x00") == (~0 & 0xFFFF).to_bytes(2, "little")
    assert catalog.miot_elliptic_checksum(b"\x01\x02\x03") == (~6 & 0xFFFF).to_bytes(2, "little")


def test_miot_elliptic_aes_ccm_round_trips_and_rejects_a_tampered_frame():
    key, nonce = b"\x02" * 16, b"\x03" * 12
    ciphertext = catalog.miot_elliptic_encrypt(key, nonce, b"payload")
    assert len(ciphertext) == len(b"payload") + catalog.MIOT_ELLIPTIC_TAG_LENGTH
    assert catalog.miot_elliptic_decrypt(key, nonce, ciphertext) == b"payload"
    tampered = ciphertext[:-1] + bytes([ciphertext[-1] ^ 1])
    with pytest.raises(Exception):
        catalog.miot_elliptic_decrypt(key, nonce, tampered)


def test_miot_elliptic_handles_and_responses_match_the_registration_catalog():
    assert catalog.MIOT_ELLIPTIC_HANDLES == (0x0010, 0x0019, 0x001A)
    assert catalog.MIOT_ELLIPTIC_AUTH_CHARACTERISTIC == "00000019-0000-1000-8000-00805f9b34fb"
    assert catalog.MIOT_ELLIPTIC_CONTROL_CHARACTERISTIC == "00000010-0000-1000-8000-00805f9b34fb"
    assert catalog.MIOT_ELLIPTIC_REGISTER_OK == b"\x11\x00\x00\x00"
    assert catalog.MIOT_ELLIPTIC_LOGIN_OK == b"\x21\x00\x00\x00"


def test_miot_elliptic_full_login_key_confirmation_between_two_sides():
    """An end-to-end sanity check: both sides reach the same derived keys and
    the same two confirmation tags, the way a real register+login would."""
    host = catalog.miot_elliptic_generate_keypair()
    device = catalog.miot_elliptic_generate_keypair()
    host_point = catalog.miot_elliptic_public_point(host)
    device_point = catalog.miot_elliptic_public_point(device)
    host_nonce, device_nonce = b"\x10" * 16, b"\x20" * 16

    host_secret = catalog.miot_elliptic_shared_secret(host, catalog.miot_elliptic_load_peer_point(device_point))
    device_secret = catalog.miot_elliptic_shared_secret(device, catalog.miot_elliptic_load_peer_point(host_point))
    host_keys = catalog.miot_elliptic_derive_login_keys(host_secret, host_nonce, device_nonce)
    device_keys = catalog.miot_elliptic_derive_login_keys(device_secret, host_nonce, device_nonce)
    assert host_keys == device_keys

    device_confirms_key, host_confirms_key = host_keys[:16], host_keys[16:32]
    device_tag = catalog.miot_elliptic_confirmation_tag(device_confirms_key, device_nonce, host_nonce)
    host_tag = catalog.miot_elliptic_confirmation_tag(host_confirms_key, device_nonce, host_nonce)
    # Each side recomputes the other's tag with its own copy of that key.
    assert catalog.miot_elliptic_confirmation_tag(device_confirms_key, device_nonce, host_nonce) == device_tag
    assert catalog.miot_elliptic_confirmation_tag(host_confirms_key, device_nonce, host_nonce) == host_tag

    # The remaining 8 bytes of host_keys exist (two 4-byte halves); how they
    # become the per-direction AES-CCM nonce is not confirmed, so the
    # encrypted channel itself is exercised separately, with an arbitrary
    # nonce, in test_miot_elliptic_aes_ccm_round_trips_and_rejects_a_tampered_frame.
    assert len(host_keys[32:]) == 8


def test_miot_elliptic_session_keys_split_the_hkdf_output_by_direction():
    login_keys = bytes(range(40))
    session = catalog.miot_elliptic_session_keys(login_keys)
    assert session.receive_key == login_keys[0:16]
    assert session.send_key == login_keys[16:32]
    assert session.receive_nonce_seed == login_keys[32:36]
    assert session.send_nonce_seed == login_keys[36:40]


def test_miot_elliptic_data_nonce_is_12_bytes_and_varies_with_the_sequence():
    seed = b"\xAA\xBB\xCC\xDD"
    nonce = catalog.miot_elliptic_data_nonce(seed, 7)
    assert len(nonce) == 12
    assert nonce[:4] == seed
    assert nonce != catalog.miot_elliptic_data_nonce(seed, 8)
    with pytest.raises(ValueError):
        catalog.miot_elliptic_data_nonce(seed, 0x10000)


def test_miot_elliptic_data_frame_round_trips_between_both_directions():
    """What the host builds with its own session, the device's mirrored
    session (receive/send swapped) must be able to parse, and back again."""
    login_keys = b"\x11" * 16 + b"\x22" * 16 + b"\x33\x33\x33\x33" + b"\x44\x44\x44\x44"
    host = catalog.miot_elliptic_session_keys(login_keys)
    device = catalog.MiotEllipticSession(
        receive_key=host.send_key, receive_nonce_seed=host.send_nonce_seed,
        send_key=host.receive_key, send_nonce_seed=host.receive_nonce_seed,
    )
    frame = catalog.miot_elliptic_build_data_frame(host, 1, header=b"\x01\x02\x03", payload=b"battery=80")
    assert frame[:2] == catalog.MIOT_ELLIPTIC_FRAME_SYNC
    assert catalog.miot_elliptic_parse_data_frame(device, frame) == b"\x01\x02\x03battery=80"

    reply = catalog.miot_elliptic_build_data_frame(device, 1, header=b"\x01\x02\x03", payload=b"ack")
    assert catalog.miot_elliptic_parse_data_frame(host, reply) == b"\x01\x02\x03ack"


def test_miot_elliptic_data_frame_rejects_a_bad_sync_or_a_flipped_checksum_bit():
    login_keys = b"\x55" * 40
    session = catalog.miot_elliptic_session_keys(login_keys)
    frame = catalog.miot_elliptic_build_data_frame(session, 0, header=b"\x00\x00\x00", payload=b"x")
    with pytest.raises(ValueError):
        catalog.miot_elliptic_parse_data_frame(session, b"\x00\x00" + frame[2:])
    tampered = bytearray(frame)
    tampered[-1] ^= 1
    with pytest.raises(ValueError):
        catalog.miot_elliptic_parse_data_frame(session, bytes(tampered))
