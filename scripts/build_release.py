"""Build deterministic installation and source archives from the repository."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "custom_components/ninebot_e_scooters/manifest.json"
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".git", ".venv", "dist", ".engine", "node_modules"}


def write_archive(path: Path, files: list[Path], *, relative_to: Path = ROOT) -> None:
    """Fixed metadata makes identical source trees produce identical ZIPs."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in sorted(files):
            info = zipfile.ZipInfo(file.relative_to(relative_to).as_posix(), (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, file.read_bytes())


def main() -> None:
    """Keep the installation package separate from contributor material."""
    version = json.loads(MANIFEST.read_text())["version"]
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    files = [file for file in ROOT.rglob("*") if file.is_file()
             and not (set(file.relative_to(ROOT).parts) & EXCLUDED_PARTS)
             and file.suffix not in {".zip", ".pyc"}]
    component = [file for file in files if file.relative_to(ROOT).parts[0] == "custom_components"]
    install = list(component)
    install.extend(ROOT / name for name in ("README.md", "THIRD_PARTY.md", "CHANGELOG.md"))
    install.extend(file for file in files if file.relative_to(ROOT).parts[0] == "docs"
                   and "history" not in file.relative_to(ROOT).parts)
    write_archive(output / f"ninebot_e_scooters_{version}_install.zip", install)
    write_archive(output / f"ninebot_e_scooters-{version}-manual.zip", component)
    write_archive(output / "ninebot_e_scooters.zip", component, relative_to=MANIFEST.parent)
    write_archive(output / f"ninebot_e_scooters_{version}_source.zip", files)
    (output / "SHA256SUMS.txt").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in sorted(output.glob("*.zip"))
    ))
    print(f"Built installation and source archives for {version}")


if __name__ == "__main__":
    main()
