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
