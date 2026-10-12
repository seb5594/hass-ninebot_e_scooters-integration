"""The pairing dialog URL carries the manifest version so browsers reload new releases."""
import json
from pathlib import Path

component = Path("custom_components/ninebot_e_scooters")
version = json.loads((component / "manifest.json").read_text())["version"]
setup = (component / "__init__.py").read_text()
assert f"pairing_dialog.js?v={version}" in setup, "Update the frontend cache version"
print(f"Frontend cache version matches {version}")
