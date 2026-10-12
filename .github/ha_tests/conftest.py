"""Fixtures that boot a real Home Assistant core around the integration.

The shared engine plugin makes custom_components discoverable. Only Bluetooth
hardware, the frontend and the web server are replaced here. Both doubles copy the
signatures of the installed Home Assistant, so a keyword the running release does
not know fails here exactly as it would on a user's installation.
"""

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import create_autospec, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.components import bluetooth  # noqa: E402
from homeassistant.components.frontend import add_extra_js_url  # noqa: E402
from homeassistant.components.http import HomeAssistantHTTP  # noqa: E402

from real_scooter import ADDRESS, NAME  # noqa: E402

BLUETOOTH_FUNCTIONS = (
    "async_register_callback",
    "async_discovered_service_info",
    "async_last_service_info",
    "async_ble_device_from_address",
    "async_request_active_scan",
    "async_clear_advertisement_history",
    "async_address_reachability_diagnostics",
)


@pytest.fixture(autouse=True)
def http(hass):
    """A web server that only checks the calls made against it."""
    hass.http = create_autospec(HomeAssistantHTTP, instance=True)
    return hass.http


@pytest.fixture(autouse=True)
def frontend_modules():
    """Record the extra JavaScript module instead of running the frontend setup."""
    with patch("custom_components.ninebot_e_scooters.add_extra_js_url", autospec=add_extra_js_url) as double:
        yield double


@pytest.fixture
def scooter_advertisement():
    """What Home Assistant's Bluetooth stack reports for a nearby scooter."""
    return SimpleNamespace(
        address=ADDRESS, name=NAME, service_uuids=[], connectable=True, device=None, time=0.0,
    )


@pytest.fixture(autouse=True)
def bluetooth_api(scooter_advertisement):
    """Replace the Bluetooth API by signature-checked doubles, as far as it exists."""
    with ExitStack() as stack:
        doubles = {
            name: stack.enter_context(patch.object(bluetooth, name, autospec=True))
            for name in BLUETOOTH_FUNCTIONS
            if hasattr(bluetooth, name)
        }
        doubles["async_discovered_service_info"].return_value = [scooter_advertisement]
        doubles["async_last_service_info"].return_value = None
        doubles["async_ble_device_from_address"].return_value = None
        yield SimpleNamespace(**doubles)
