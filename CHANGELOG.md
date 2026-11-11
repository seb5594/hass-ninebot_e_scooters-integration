# Changelog

## 2026.11.11.1

Versions are now named after their release date: `YYYY.MM.DD.BUILD`.

- **Ninebot F3, F3 Pro and Max G3 (experimental, [#16](https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues/16)):**
  this generation answers the handshake on another board and keeps its values on a vehicle
  control unit, so it connected and stayed empty. It is now read: battery level, remaining
  range and odometer on every poll, then temperature, error codes and, where the pack has its
  own board, voltage, current, capacity and charge cycles. Read-only.
- **Pairing password in the options.** A scooter remembers one session password. With the one
  the Segway app uses, Home Assistant logs in without unpairing the app. Without it, pairing
  with the power button works as before and replaces the app's password.
- A Ninebot whose handshake stays unanswered is asked on the other board. If the selected
  family does not fit the board that answers, the scooter is read as the generation it is.
- **Ninebot Max G2, D18, D28 and D38 (experimental)** use the registers of the Max G30 over the
  Ninebot serial service, which is now recognized next to the Nordic one. **F65** joins the
  F series.
- Serial numbers identify more models: ES1 to ES4, G30M, the regional E and F editions and the
  Max G2. An `N2G` serial with an unknown letter is no longer taken for an E series.
- The trip distance is no longer read on Ninebot scooters: its register differs between the F
  series and the Max G2.
- The session encryption is rewritten from the public description of the scheme and checked
  byte for byte against recorded sessions of the previous release. See `docs/LICENSING.md`.
- Shared modules moved into `helpers/`; the compatibility imports of earlier releases
  (`protocol.py`, `ninebot_crypto.py`, `model_profiles.py` and others) are removed.
- The pairing dialog is reloaded by browsers after every update without a manual version bump.
- Diagnostics list the GATT characteristics, the board that answered the handshake and whether
  the scooter already holds a session password.

## 1.0.0b5

- Prepare a release validated by the shared HASS Marketplace workflow, including HACS and Hassfest without ignored checks.
- Keep the generated Marketplace submission files available as a workflow artifact.

## Beta 4 (`1.0.0b4`)

- Renamed Xiaomi scooters are discovered: they advertise only a MiBeacon frame, so the
  manifest now matches the Xiaomi service data UUID and discovery checks the product ID
  inside the frame (Mi Electric Scooter 1S: `0x061C`). Other Xiaomi devices are rejected
  without a notification. Product IDs of further models are added to
  `XIAOMI_SCOOTER_PRODUCT_IDS` in `discovery.py`.

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
