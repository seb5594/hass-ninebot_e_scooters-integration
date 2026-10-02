"""Validate the Home Assistant, HACS and prerelease packaging contract."""

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
manifests = list((ROOT / "custom_components").glob("*/manifest.json"))
assert len(manifests) == 1, "Exactly one integration is expected"
manifest = json.loads(manifests[0].read_text())
domain = manifest["domain"]
assert re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", domain), "Domain must be a Home Assistant slug"
assert manifests[0].parent.name == domain, "Domain must match its folder"
assert re.fullmatch(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?", manifest["version"]), "Invalid release version"
hacs = json.loads((ROOT / "hacs.json").read_text())
assert hacs["zip_release"] is True and hacs["filename"] == f"{domain}.zip"
setup = (manifests[0].parent / "__init__.py").read_text()
assert f"pairing_dialog.js?v={manifest['version']}" in setup, "Update frontend cache version"
print(f"Validated {domain} {manifest['version']}")
