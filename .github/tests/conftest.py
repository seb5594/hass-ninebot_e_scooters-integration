"""Load pure protocol modules without a running Home Assistant instance."""

from pathlib import Path
import importlib.util
import sys
import types


if importlib.util.find_spec("homeassistant") is None:
    # The protocol tests import pure Python modules without loading the HA
    # config-entry setup package when Home Assistant is not installed.
    package = types.ModuleType("custom_components.ninebot_e_scooters")
    package.__path__ = [str(Path(__file__).resolve().parents[2] /
                             "custom_components" / "ninebot_e_scooters")]
    sys.modules.setdefault("custom_components.ninebot_e_scooters", package)

