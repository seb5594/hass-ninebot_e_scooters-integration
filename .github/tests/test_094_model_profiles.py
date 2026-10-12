from source_helpers import parse_source
"""Check serial evidence and fail-closed model-specific actions."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_090_reconnect_mode import method
from test_protocol import PACKAGE_PATH, const, load_module


profiles = load_module(
    "custom_components.ninebot_e_scooters.model_profiles",
    PACKAGE_PATH / "model_profiles.py",
)


@pytest.mark.parametrize("prefix,expected", [
    ("25700", "Mi Electric Scooter 1S"),
    ("25699", "Mi Electric Scooter 1S"),
    ("25701", "Mi Electric Scooter Pro 2"),
    ("26354", "Mi Electric Scooter Pro 2"),
    ("25702", "Mi Electric Scooter Essential"),
    ("46442", "Mi Electric Scooter 4"),
])
def test_documented_serial_prefixes_identify_model_without_pretending_transport_support(prefix, expected):
    finding = profiles.identify_model(f"{prefix}/00015977".encode(), "MIScooter5977")
    assert finding.model == expected
    assert finding.evidence == "serial_prefix"
    if prefix == "46442":
        assert profiles.effective_profile(profiles.AUTO_MODEL, finding).protocol == profiles.UNVERIFIED
        assert not profiles.supports_write(profiles.AUTO_MODEL, finding, "work_mode")


@pytest.mark.parametrize("serial", [
    None, "25700", "25700/001", "25700/0001597X", "99999/00015977",
    "2JEG/00015977", "25701/12345678extra",
])
def test_unknown_or_incomplete_serial_never_invents_model(serial):
    finding = profiles.identify_model(serial, "MIScooter5977")
    assert finding.model is None
    assert finding.brand == "Xiaomi"
    assert not profiles.supports_write(profiles.AUTO_MODEL, finding, "work_mode")


def test_ble129_pro2_uses_shared_transport_but_cannot_receive_1s_writes():
    assert profiles.AUTO_MODEL in const.LEGACY_XIAOMI_MODELS
    pro2 = profiles.identify_model("25701/00015977", "MIScooter5977")
    one_s = profiles.identify_model("25700/00015977", "MIScooter5977")
    assert profiles.effective_profile(profiles.AUTO_MODEL, pro2).protocol == profiles.BLE129
    assert profiles.supports_write(profiles.AUTO_MODEL, one_s, "is_lock_on")
    assert not profiles.supports_write(profiles.AUTO_MODEL, pro2, "is_lock_on")
    assert not profiles.supports_write(const.MODEL, pro2, "work_mode")


def test_conflicting_serials_disable_writes_without_changing_selected_model():
    import logging

    scope = dict(identify_model=profiles.identify_model,
                 _LOGGER=logging.getLogger("scooter-test"))
    coordinator_tree = parse_source((PACKAGE_PATH / "coordinator.py").read_text())
    coordinator_class = next(node for node in coordinator_tree.body
                             if isinstance(node, ast.ClassDef) and node.name == "ScooterCoordinator")
    identify_node = next(node for node in coordinator_class.body
                         if isinstance(node, ast.FunctionDef) and node.name == "_identify_serial")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                              identify_node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), "<model-identification>", "exec"), scope)
    identify = scope["_identify_serial"]
    obj = SimpleNamespace(device_name="MIScooter5977", model=const.MODEL,
                          _model_identification=profiles.identify_model(None, "MIScooter5977"),
                          _model_conflict=False)
    identify(obj, b"25700/00015977")
    assert obj._model_identification.model == const.MODEL
    identify(obj, "25701/00015977")
    assert obj._model_conflict
    assert obj.model == const.MODEL


def test_verified_model_updates_ha_device_metadata_without_changing_entry():
    import logging

    tree = parse_source((PACKAGE_PATH / "coordinator.py").read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ScooterCoordinator")
    node = next(node for node in cls.body
                if isinstance(node, ast.FunctionDef) and node.name == "_sync_model_to_registry")
    registry_updates = []
    device = SimpleNamespace(id="stable-device-id", model=const.MODEL)
    registry = SimpleNamespace(
        async_get_device=lambda *, identifiers: device if identifiers == {("ninebot_e_scooters", "AA:BB")} else None,
        async_update_device=lambda *args, **kwargs: registry_updates.append((args, kwargs)),
    )
    scope = dict(device_registry=SimpleNamespace(async_get=lambda _hass: registry),
                 DOMAIN="ninebot_e_scooters", MANUFACTURER="Xiaomi",
                 _LOGGER=logging.getLogger("scooter-test"))
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                              node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), "<device-registry>", "exec"), scope)
    sync = scope["_sync_model_to_registry"]
    obj = SimpleNamespace(display_model="Mi Electric Scooter Pro 2", model=const.MODEL,
                          address="AA:BB", hass=object(), _registered_model=None,
                          _model_identification=profiles.identify_model("25701/00015977"))
    sync(obj)
    sync(obj)
    assert registry_updates == [(('stable-device-id',), {
        "model": "Mi Electric Scooter Pro 2", "manufacturer": "Xiaomi",
    })]
    assert obj.model == const.MODEL


def test_new_auto_config_entry_persists_the_verified_model_without_reload():
    import logging

    tree = parse_source((PACKAGE_PATH / "coordinator.py").read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ScooterCoordinator")
    sync = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_sync_model_to_registry")
    scope = dict(device_registry=SimpleNamespace(async_get=lambda _hass: SimpleNamespace(
                     async_get_device=lambda **_kw: None)),
                 CONF_MODEL="model", DOMAIN="ninebot_e_scooters", MANUFACTURER="Xiaomi",
                 _LOGGER=logging.getLogger("scooter-test"))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[sync], type_ignores=[])),
                 "<auto-model>", "exec"), scope)
    updates = []
    entry = SimpleNamespace(options={"model": profiles.AUTO_MODEL})
    hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_update_entry=lambda actual, **kw: updates.append((actual, kw))))
    obj = SimpleNamespace(_auto_model_pending=True, detected_model=const.MODEL,
                          model=profiles.AUTO_MODEL, address="AA:BB", hass=hass,
                          entry=entry, _registered_model=None, display_model=const.MODEL)
    obj._model_identification = profiles.identify_model("25700/00015977")
    scope["_sync_model_to_registry"](obj)
    scope["_sync_model_to_registry"](obj)
    assert obj.model == const.MODEL
    assert len(updates) == 1 and updates[0][1] == {"options": {"model": const.MODEL}}


def test_unsupported_write_never_sends_a_ble_packet():
    from test_pairing_queue import ScooterConnectionError

    gate = method("_async_write_setting", dict(ScooterConnectionError=ScooterConnectionError))
    obj = SimpleNamespace(supports_action=lambda _field: False, control_ready=True)

    async def check():
        with pytest.raises(ScooterConnectionError, match="nicht bestätigt"):
            await gate(obj, 0x75, 2, 0x75, 2, "work_mode", 2)

    asyncio.run(check())


def test_unsupported_lock_action_does_not_claim_success_for_a_noop():
    from test_pairing_queue import ScooterConnectionError

    action = method("async_set_lock", dict(ScooterConnectionError=ScooterConnectionError))
    obj = SimpleNamespace(supports_action=lambda _field: False,
                          data=SimpleNamespace(is_lock_on=True))

    async def check():
        with pytest.raises(ScooterConnectionError, match="nicht geprüft"):
            await action(obj, True)

    asyncio.run(check())
