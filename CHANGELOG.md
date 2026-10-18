# Changelog

## Beta 3 (`1.0.0b3`)

- Renamed scooters are discovered: besides the Bluetooth name, discovery now recognizes the
  manufacturer data of the Ninebot BLE module (company IDs 0x424E and 0x434E) and serial-style
  names of newer Ninebot generations. Unrelated devices with the Nordic UART service alone are
  still ignored.
- The manufacturer reference range moved into the optional riding group and is no longer
  created by default; existing installations drop it until the group is ticked.

## Beta 2 (`1.0.0b2`)

- Leaner device page: only battery, odometer, range and connection sensors are created by
  default. Riding data, temperatures, battery health, device information and raw status codes
  are optional groups, ticked during setup or later in the options. Unticking a group removes
  its sensors.
- "Problem", "Telemetry stale", "Last telemetry" and "Scooter model" are gone. The model stays
  on the device page; every measured value still carries `last_live_telemetry` and
  `value_is_cached`.
- "Work mode" shows Drive, Eco or Sport instead of 0, 1 or 2.
- Own icon and logo, shown in Bluetooth discovery and on the integrations page from Home
  Assistant 2026.3 on.
- Bluetooth session, pairing and protocol handling are unchanged.

## Beta 1 (`1.0.0b1`)

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
