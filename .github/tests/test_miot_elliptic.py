"""Verify the P4 (ECDH and AES-CCM) pairing primitives used by the config-flow fallback."""

import pytest

from test_protocol import load_module


catalog = load_module("protocols.miot_elliptic")


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


def test_miot_elliptic_handles_and_responses_match_the_paper():
    assert catalog.MIOT_ELLIPTIC_HANDLES == (0x0010, 0x0019, 0x001A)
    assert catalog.MIOT_ELLIPTIC_PAIRING_CHARACTERISTIC == "00000019-0000-1000-8000-00805f9b34fb"
    assert catalog.MIOT_ELLIPTIC_SESSION_CHARACTERISTIC == "00000010-0000-1000-8000-00805f9b34fb"
    assert catalog.MIOT_PAIR_OK_ACK == b"\x11\x00\x00\x00"
    assert catalog.MIOT_SESS_OK == b"\x21\x00\x00\x00"
    assert catalog.MIOT_PAIR_REQ == b"\xA2\x00\x00\x00"
    assert catalog.MIOT_PAIR_OK == b"\x13\x00\x00\x00"
    assert catalog.MIOT_SESS_REQ_1 == b"\x24\x00\x00\x00"


def test_miot_elliptic_pairing_keys_are_deterministic_and_split_as_pk_then_otk():
    secret = b"\x07" * 32
    derived = catalog.miot_elliptic_derive_pairing_keys(secret)
    assert len(derived) == 32
    assert derived == catalog.miot_elliptic_derive_pairing_keys(secret)
    pairing_key, one_time_key = derived[:16], derived[16:]
    assert pairing_key != one_time_key


def test_miot_elliptic_pairing_response_is_the_app_s_unilateral_proof():
    """Pairing only has the app prove it reached the same otk as the
    scooter (the paper's V1, Unauthenticated Pairing); there is no
    matching scooter-side response to verify in return."""
    one_time_key, nonce, challenge = b"\x08" * 16, b"\x09" * 12, b"\x0A" * 16
    response = catalog.miot_elliptic_pairing_response(one_time_key, nonce, challenge)
    assert catalog.miot_elliptic_decrypt(one_time_key, nonce, response) == challenge


def test_miot_elliptic_full_pairing_and_session_between_two_sides():
    """End to end: an ECDH exchange, Pairing's HKDF, the app's unilateral
    proof, then Session's HKDF reaching the same four keys on both sides —
    the complete shape Pairing and Session go through, per the cited paper."""
    app = catalog.miot_elliptic_generate_keypair()
    esc = catalog.miot_elliptic_generate_keypair()
    app_point = catalog.miot_elliptic_public_point(app)
    esc_point = catalog.miot_elliptic_public_point(esc)
    app_secret = catalog.miot_elliptic_shared_secret(app, catalog.miot_elliptic_load_peer_point(esc_point))
    esc_secret = catalog.miot_elliptic_shared_secret(esc, catalog.miot_elliptic_load_peer_point(app_point))
    assert app_secret == esc_secret

    app_pairing = catalog.miot_elliptic_derive_pairing_keys(app_secret)
    esc_pairing = catalog.miot_elliptic_derive_pairing_keys(esc_secret)
    assert app_pairing == esc_pairing
    pairing_key, one_time_key = app_pairing[:16], app_pairing[16:]

    challenge, nonce = b"\x0B" * 16, b"\x0C" * 12
    response = catalog.miot_elliptic_pairing_response(one_time_key, nonce, challenge)
    assert catalog.miot_elliptic_decrypt(one_time_key, nonce, response) == challenge

    rand_app, rand_esc = b"\x0D" * 16, b"\x0E" * 16
    app_session = catalog.miot_elliptic_derive_login_keys(pairing_key, rand_app, rand_esc)
    esc_session = catalog.miot_elliptic_derive_login_keys(pairing_key, rand_app, rand_esc)
    assert app_session == esc_session


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


def test_miot_elliptic_fragment_splits_into_16_byte_chunks_with_a_big_endian_offset_header():
    fragments = catalog.miot_elliptic_fragment(bytes(range(20)))
    assert fragments == (
        b"\x00\x00" + bytes(range(0, 16)),
        b"\x00\x10" + bytes(range(16, 20)),
    )
    assert catalog.miot_elliptic_fragment(b"") == ()


def test_miot_elliptic_fragment_of_a_64_byte_point_uses_the_four_documented_offsets():
    point = bytes(range(64))
    fragments = catalog.miot_elliptic_fragment(point)
    assert [fragment[:2] for fragment in fragments] == [
        b"\x00\x00", b"\x00\x10", b"\x00\x20", b"\x00\x30",
    ]
    assert b"".join(fragment[2:] for fragment in fragments) == point
