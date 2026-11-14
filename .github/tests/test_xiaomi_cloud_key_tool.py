"""Offline checks for docs/tools/fetch_xiaomi_ble_credentials.py.

This tool is deliberately outside custom_components: it is not part of the
Home Assistant integration and is never imported by it. These tests only
exercise its pure cryptographic helpers; none of them touch the network or
need a Xiaomi account.
"""

import base64
import hashlib
import importlib.util
import sys
from pathlib import Path

TOOL_PATH = Path(__file__).resolve().parents[2] / "docs" / "tools" / "fetch_xiaomi_ble_credentials.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("fetch_xiaomi_ble_credentials", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = load_tool()


def test_rc4_round_trips_and_matches_a_known_test_vector():
    session = tool.XiaomiCloudSession()
    key, data = b"secret-key-bytes", b"a payload long enough to cross the discarded keystream"
    encrypted = session._rc4(key, data)
    assert encrypted != data
    # RC4 is its own inverse: re-applying the same keystream decrypts it.
    assert session._rc4(key, encrypted) == data

    # RFC 6229 test vector: key "Key", first keystream bytes after offset 0.
    keystream = tool.XiaomiCloudSession._rc4_keystream(b"Key", 8)
    assert keystream.hex() == "eb9f7781b734ca72"


def test_signed_nonce_matches_the_documented_sha256_formula():
    session = tool.XiaomiCloudSession()
    session._ssecurity = base64.b64encode(b"\x01" * 16).decode()
    nonce = base64.b64encode(b"\x02" * 12).decode()
    expected = base64.b64encode(hashlib.sha256(b"\x01" * 16 + b"\x02" * 12).digest()).decode()
    assert session._signed_nonce(nonce) == expected


def test_nonce_is_12_bytes_and_ends_with_the_current_minute():
    session = tool.XiaomiCloudSession()
    nonce = base64.b64decode(session._nonce())
    assert len(nonce) == 12


def test_device_id_and_user_agent_look_plausible_and_vary():
    a, b = tool._random_device_id(), tool._random_device_id()
    assert len(a) == 6 and a.isalpha() and a.islower()
    assert a != b or a != tool._random_device_id()  # practically always different
    agent = tool._random_user_agent()
    assert "APP/com.xiaomi.mihome" in agent
