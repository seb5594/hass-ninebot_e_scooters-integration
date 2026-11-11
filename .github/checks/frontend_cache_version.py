"""The pairing dialog URL carries the installed version so browsers reload new releases."""
from pathlib import Path

setup = Path("custom_components/ninebot_e_scooters/__init__.py").read_text()
assert "pairing_dialog.js?v={integration.version}" in setup, (
    "Build the frontend cache version from the installed integration"
)
print("Frontend cache version follows the manifest")
