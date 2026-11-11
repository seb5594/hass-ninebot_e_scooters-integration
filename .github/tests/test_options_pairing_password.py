"""The options form accepts a session password the scooter already knows."""

import asyncio
from types import SimpleNamespace

from test_config_flow_transport_smoke import namespace

SETTINGS = {"poll_interval": 10, "model": "Mi Electric Scooter 1S"}


class OptionsFlow(namespace["NinebotScooterOptionsFlow"]):
    """The flow under test with the two results Home Assistant would render."""

    def async_show_form(self, **form):
        return {"type": "form", **form}

    def async_create_entry(self, **entry):
        return {"type": "entry", **entry}


def submit(user_input):
    saved = []
    entry = SimpleNamespace(options={}, data={"address": "AA:BB", "app_key": "ab" * 16, "paired": False})
    flow = OptionsFlow(entry)
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_update_entry=lambda _entry, **changes: saved.append(changes)))
    return asyncio.run(flow.async_step_init(user_input)), saved


def test_password_is_stored_as_the_paired_key_and_kept_out_of_the_options():
    result, saved = submit({**SETTINGS, "pairing_password": " 00112233 44556677\n8899AABB ccddeeff "})
    assert result["type"] == "entry"
    assert "pairing_password" not in result["data"]
    assert saved == [{"data": {"address": "AA:BB", "app_key": "00112233445566778899aabbccddeeff",
                               "paired": True}}]


def test_empty_field_keeps_the_key_home_assistant_generated():
    for user_input in (SETTINGS, {**SETTINGS, "pairing_password": "  "}):
        result, saved = submit(user_input)
        assert result["type"] == "entry" and saved == []


def test_malformed_password_is_rejected_without_touching_the_entry():
    for wrong in ("not a password", "0011", "zz" * 16, "00" * 17):
        result, saved = submit({**SETTINGS, "pairing_password": wrong})
        assert result["type"] == "form"
        assert result["errors"] == {"pairing_password": "invalid_pairing_password"}
        assert saved == []
