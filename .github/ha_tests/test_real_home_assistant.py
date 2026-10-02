"""The integration inside a genuine Home Assistant: flows, entities, options, unload.

They need Home Assistant and pytest-homeassistant-custom-component. The shared
engine installs both for every release the Compatibility workflow lists; to run them
locally: python .engine/.scripts/ha_matrix.py run 2026.9.4
"""

import inspect
from unittest.mock import patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant import config_entries  # noqa: E402
from homeassistant.components import bluetooth  # noqa: E402
from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.const import CONF_ADDRESS, MAJOR_VERSION, MINOR_VERSION  # noqa: E402
from homeassistant.helpers import entity_registry  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.ninebot_e_scooters import compat, diagnostics  # noqa: E402
from custom_components.ninebot_e_scooters.const import (  # noqa: E402
    CONF_MODEL,
    CONF_POLL_INTERVAL,
    DOMAIN,
)

from real_scooter import ADDRESS, NAME  # noqa: E402

HA_VERSION = (MAJOR_VERSION, MINOR_VERSION)
CALLBACK_FEATURES = ("scan_interval", "scan_duration", "replay")


@pytest.fixture
def entry(hass):
    """A paired scooter that was set up before."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        title=NAME,
        data={CONF_ADDRESS: ADDRESS, "bluetooth_name": NAME, "app_key": "ab" * 16, "paired": True},
        options={CONF_MODEL: "Mi Electric Scooter 1S", CONF_POLL_INTERVAL: 10},
    )
    entry.add_to_hass(hass)
    return entry


async def test_user_flow_lists_the_scooter_and_creates_the_entry(hass):
    with patch(f"custom_components.{DOMAIN}.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        assert result["type"] == "form" and result["step_id"] == "user"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS})
        await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert result["title"] == NAME
    assert result["data"][CONF_ADDRESS] == ADDRESS


async def test_options_flow_receives_the_entry_on_every_release(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form" and result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_POLL_INTERVAL: 30, CONF_MODEL: "Mi Electric Scooter 1S"})
    assert result["type"] == "create_entry"
    assert entry.options[CONF_POLL_INTERVAL] == 30


@pytest.mark.skipif(HA_VERSION < (2024, 4), reason="reconfigure flows arrived in 2024.4")
async def test_reconfigure_flow_replaces_the_scooter_and_drops_its_credentials(
        hass, entry, scooter_advertisement):
    other = "AA:BB:CC:DD:EE:01"
    scooter_advertisement.address = other
    with patch(f"custom_components.{DOMAIN}.async_setup_entry", return_value=True), \
            patch(f"custom_components.{DOMAIN}.async_unload_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id})
        assert result["type"] == "form" and result["step_id"] == "reconfigure"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: other})
        await hass.async_block_till_done()
    assert result["type"] == "abort" and result["reason"] == "reconfigured"
    assert entry.data[CONF_ADDRESS] == other
    assert entry.data["paired"] is False
    assert entry.data["bluetooth_name"] == NAME
    assert entry.data["app_key"] != "ab" * 16


async def test_setup_serves_assets_registers_for_advertisements_and_names_entities(
        hass, entry, http, bluetooth_api, frontend_modules):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    served = ("/api/ninebot_e_scooters/power_button.gif", "/api/ninebot_e_scooters/pairing_dialog.js")
    if hasattr(http, "async_register_static_paths"):
        registered = [config.url_path for config in http.async_register_static_paths.call_args.args[0]]
    else:
        registered = [call.args[0] for call in http.register_static_path.call_args_list]
    assert tuple(registered) == served
    frontend_modules.assert_called_once()

    options = bluetooth_api.async_register_callback.call_args.kwargs
    parameters = inspect.signature(bluetooth.async_register_callback).parameters
    for feature in CALLBACK_FEATURES:
        assert (feature in options) == (feature in parameters), feature
    if hasattr(bluetooth, "BluetoothCallbackReplay"):
        assert options["replay"] is bluetooth.BluetoothCallbackReplay.NEWEST_FIRST
    if hasattr(bluetooth, "async_clear_advertisement_history"):
        bluetooth_api.async_clear_advertisement_history.assert_called_with(hass, ADDRESS)

    registry = entity_registry.async_get(hass)
    entities = entity_registry.async_entries_for_config_entry(registry, entry.entry_id)
    assert {item.domain for item in entities} == {"sensor", "binary_sensor", "switch", "lock", "select"}
    # Disabled-by-default entities have no state, but the registry keeps their name.
    names = {item.entity_id: item.original_name for item in entities}
    assert all(names.values()), names
    assert len({(item.domain, item.original_name) for item in entities}) == len(entities)
    assert hass.states.get("sensor.miscooter5977_battery").name == f"{NAME} Battery"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics_redact_through_the_release_specific_helper(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    report = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    assert ADDRESS not in str(report)
    assert "ab" * 16 not in str(report)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_background_tasks_start_lazily_and_belong_to_the_entry(hass, entry):
    order = []

    async def work():
        order.append("task")
        return "done"

    task = compat.create_background_task(entry, hass, work(), "ninebot_test")
    order.append("scheduled")
    assert await task == "done"
    assert order == ["scheduled", "task"]
