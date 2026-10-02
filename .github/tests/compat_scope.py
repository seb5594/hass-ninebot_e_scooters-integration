"""Load the real compat module without Home Assistant, around a test's own doubles.

The isolated method harnesses compile single functions with hand-made globals.
Production code now reaches Home Assistant through compat.py, so the harnesses
take those helpers from the genuine module, bound to the Bluetooth double of the
test instead of a copy of their logic.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

COMPAT = Path(__file__).resolve().parents[2] / "custom_components/ninebot_e_scooters/compat.py"
EXPORTED = (
    "async_register_scooter_callback",
    "async_register_static_files",
    "async_request_active_scan",
    "async_update_reload_and_abort",
    "clear_advertisement_history",
    "create_background_task",
    "describe_unreachable_scooter",
)


def _module(name: str, **attributes) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attributes)
    return module


def load_compat(bluetooth=None, static_path_config=None, version=(2026, 9),
                name_translations=True) -> ModuleType:
    """Execute compat.py against doubles; Home Assistant itself is never imported."""

    class Entity:
        if name_translations:
            _name_translation_key = None

    stubs = {
        "homeassistant": _module("homeassistant"),
        "homeassistant.components": _module(
            "homeassistant.components", bluetooth=bluetooth or SimpleNamespace()
        ),
        "homeassistant.components.http": _module(
            "homeassistant.components.http", StaticPathConfig=static_path_config
        ) if static_path_config else None,
        "homeassistant.config_entries": _module(
            "homeassistant.config_entries", ConfigEntry=object, ConfigFlowResult=dict
        ),
        "homeassistant.const": _module(
            "homeassistant.const", MAJOR_VERSION=version[0], MINOR_VERSION=version[1]
        ),
        "homeassistant.core": _module("homeassistant.core", HomeAssistant=object),
        "homeassistant.helpers": _module("homeassistant.helpers"),
        "homeassistant.helpers.entity": _module("homeassistant.helpers.entity", Entity=Entity),
        "homeassistant.helpers.device_registry": _module(
            "homeassistant.helpers.device_registry", DeviceInfo=dict
        ),
        "homeassistant.helpers.redact": _module(
            "homeassistant.helpers.redact", async_redact_data=lambda data, keys: data
        ),
    }
    saved = {name: sys.modules.get(name) for name in stubs}
    try:
        for name, stub in stubs.items():
            if stub is None:
                sys.modules.pop(name, None)  # absent module -> the import fallback runs
            else:
                sys.modules[name] = stub
        spec = importlib.util.spec_from_file_location("isolated_ninebot_compat", COMPAT)
        compat = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compat)
        return compat
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def add_compat_symbols(namespace: dict, bluetooth=None, static_path_config=None) -> dict:
    """Give a harness the production helpers, wired to its own Bluetooth double."""
    compat = load_compat(bluetooth or namespace.get("bluetooth"), static_path_config)
    for name in EXPORTED:
        namespace.setdefault(name, getattr(compat, name))
    return namespace
