# Changelog

## v1.0.0 Beta 1 (`1.0.0b1`)

- Technical domain changed to `ninebot_e_scooters`; one-time setup required for earlier installations.
- Pairing confirmation remains centered in the active frontend with the bundled animation.
- Existing Xiaomi session, crypto and telemetry behavior retained.
- Experimental read-only ES, Max G30, E and F profiles retained.
- Runs on Home Assistant 2023.2 and newer (Python 3.10+): release differences live in `compat.py`; releases before 2026.9 skip the active scan and advertisement replay.
- Tests also run inside a real Home Assistant core, on every release from 2023.2.5 to 2026.9.4.
- Superseded release documents, disabled historical tests and commented-out assertions removed.
- Repository metadata, badges, compatibility reports and beta release instructions added.
- HACS/manual/source ZIPs and checksums prepared through the shared workflow engine.

Additional model and firmware combinations require hardware acceptance.
