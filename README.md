# Ninebot E-Scooters

<!-- badges:begin (generated from project metadata) -->
[![HACS](https://img.shields.io/static/v1?label=HACS&message=Add%20integration&color=41BDF5&style=flat&logo=homeassistantcommunitystore&logoColor=white)](https://my.home-assistant.io/redirect/hacs_repository/?owner=seb5594&repository=hass-ninebot_e_scooters-integration&category=integration) ![setup](https://img.shields.io/static/v1?label=setup&message=UI%20config%20flow&color=157F71&style=flat)<br>
![home assistant](https://img.shields.io/static/v1?label=home%20assistant&message=%E2%89%A5%202026.9.0&color=1877A5&style=flat) [![version](https://img.shields.io/static/v1?label=version&message=1.0.0b1&color=1877A5&style=flat)](https://github.com/seb5594/hass-ninebot_e_scooters-integration/releases) [![released](https://img.shields.io/github/release-date-pre/seb5594/hass-ninebot_e_scooters-integration?label=released&style=flat)](https://github.com/seb5594/hass-ninebot_e_scooters-integration/releases) [![checks](https://img.shields.io/github/actions/workflow/status/seb5594/hass-ninebot_e_scooters-integration/ci.yml?branch=main&label=checks&style=flat)](https://github.com/seb5594/hass-ninebot_e_scooters-integration/actions/workflows/ci.yml)<br>
[![downloads](https://img.shields.io/github/downloads/seb5594/hass-ninebot_e_scooters-integration/total?label=downloads&style=flat)](https://github.com/seb5594/hass-ninebot_e_scooters-integration/releases) [![latest release](https://img.shields.io/github/downloads/seb5594/hass-ninebot_e_scooters-integration/latest/total?label=latest%20release&style=flat)](https://github.com/seb5594/hass-ninebot_e_scooters-integration/releases/latest)<br>
[![stars](https://img.shields.io/github/stars/seb5594/hass-ninebot_e_scooters-integration?label=stars&style=flat)](https://github.com/seb5594/hass-ninebot_e_scooters-integration/stargazers) [![issues](https://img.shields.io/github/issues/seb5594/hass-ninebot_e_scooters-integration?label=issues&style=flat)](https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues) [![updated](https://img.shields.io/github/last-commit/seb5594/hass-ninebot_e_scooters-integration?label=updated&style=flat)](https://github.com/seb5594/hass-ninebot_e_scooters-integration/commits/main)<br>
![tests](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fseb5594%2Fhass-ninebot_e_scooters-integration%2Fbadges%2Ftests.json&style=flat) ![HACS zip](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fseb5594%2Fhass-ninebot_e_scooters-integration%2Fbadges%2Fzip-size.json&style=flat) ![last build](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fseb5594%2Fhass-ninebot_e_scooters-integration%2Fbadges%2Flast-build.json&style=flat)<br>
[![Buy Me a Coffee](https://img.shields.io/static/v1?label=Support&message=Buy%20Me%20a%20Coffee&color=FFDD00&logo=buy-me-a-coffee&logoColor=black&style=flat)](https://buymeacoffee.com/seb5594) [![PayPal](https://img.shields.io/static/v1?label=Support&message=PayPal&color=0070BA&logo=paypal&logoColor=white&style=flat)](https://www.paypal.com/donate/?hosted_button_id=QMQPNRENXDN26)
<!-- badges:end -->

[English](README.md) · [Deutsch](docs/README.de.md)

Local Home Assistant integration for Ninebot/Segway e-scooters and compatible Xiaomi models.
No cloud account required.

The reference device is a Xiaomi 1S with BLE 1.29 and DRV 1.28. Other profiles are
experimental and need hardware feedback. The integration keeps a working Bluetooth session
alive and reuses stored keys.

## Models and firmware

| Model / family | Protocol / firmware | Features | Status |
| --- | --- | --- | --- |
| Xiaomi 1S | 5A A5, BLE129 / DRV1.28 | Telemetry and guarded controls | Reference device |
| Xiaomi Pro 2 / Essential | 5A A5, BLE129 | Telemetry | Hardware test pending |
| Xiaomi M365, four-dot display | Unencrypted 55 AA | Telemetry | Hardware test pending |
| Xiaomi M365 Pro | 5A A5, BLE110/122 | Telemetry | Hardware test pending |
| Ninebot ES1 / ES2 / ES3 / ES4 | 5A A5, BLE109/110 | Read-only word registers | Experimental |
| Ninebot Max G30 / G30P / G30D / G30E / G30LP / G30LE / G30LD | 5A A5, BLE110/113/114 | Read-only word registers | Experimental |
| Ninebot E22 / E25 / E45 | 5A A5, BLE209/213 | Read-only word registers | Experimental |
| Ninebot F20 / F25 / F30 / F40 | 5A A5, BLE307, PC address | Read-only word registers | Experimental |

These BLE versions come from public implementations. They do not guarantee compatibility with
every region, dashboard or firmware variant. Xiaomi BLE132 with 5A AB, Xiaomi 3/4 and Ninebot
G2, F2, ZT and GT are not supported. Model notes in the research catalog do not mean support.

Ninebot scooters report battery level, current, voltage, battery temperatures and the status
word. Odometer, firmware, errors and battery health are queried step by step. Current speed,
external ES batteries and write control for Ninebot are not implemented yet. Missing values stay
unknown.

## Installation

Requirements: **Home Assistant 2026.9 or newer** and a Bluetooth adapter or an active ESPHome
Bluetooth proxy. Disconnect other scooter apps before setup.

1. Install through HACS (see below), or manually from the Home Assistant terminal (SSH or
   Terminal app) with the version you want from the
   [releases](https://github.com/seb5594/hass-ninebot_e_scooters-integration/releases):

   ```bash
   cd /config
   mkdir -p custom_components/ninebot_e_scooters
   wget -O /tmp/ninebot_e_scooters.zip \
     https://github.com/seb5594/hass-ninebot_e_scooters-integration/releases/download/v1.0.0b1/ninebot_e_scooters.zip
   unzip -o /tmp/ninebot_e_scooters.zip -d custom_components/ninebot_e_scooters
   rm /tmp/ninebot_e_scooters.zip
   ```

   Replace `v1.0.0b1` with the version you want, then restart Home Assistant.
2. Go to **Settings → Devices & services → Add integration** and search for
   **Ninebot E-Scooters**. Switch the scooter on and select the matching model.
3. Press the power button once, briefly, only when the centered pairing prompt appears.

For HACS, once the repository is public: add it as a **custom repository → Integration** and
enable beta versions. `ninebot_e_scooters.zip` contains the integration directly in the ZIP root
and serves HACS and manual installs alike.

**Migrating from `xiaomi_scooter`:** the new technical domain is `ninebot_e_scooters`. This is
not an automatic update of the old config entry. Create a Home Assistant backup first, note your
current entity IDs and remove the old integration. Remove the old component folder, install the
new one and set the scooter up again. Pairing has to be confirmed again. Afterwards check entity
IDs and automations. Both integrations must not connect to the same scooter at the same time.
Do not edit files under `.storage` by hand.

If no device is found: search again, or enter the Bluetooth address and the exact advertised
Bluetooth name. The name is part of the encryption and can differ from the device name you
chose yourself.

## Connection and values

The default polling interval is ten seconds; the options allow five to 120 seconds. For a parked
scooter 20–30 seconds is often enough.

A working session stays open. After an interruption the next attempt needs a fresh Bluetooth
sighting. A stored session is checked first with an encrypted read. Timeouts do not replace the
app key. Repeated failures lengthen the pause; an unconfirmed pairing is retried after one
minute at the earliest. This is meant to reduce unnecessary reconnects. Connection tones
triggered by the firmware can still occur.

"Connection", "Telemetry stale" and "Last telemetry" show the connection and data status.
Measured values carry `last_live_telemetry` and `value_is_cached`. After more than ten minutes
old values are no longer reported as available. The 1S reference range is a simple estimate from
the battery percentage.

Lock, tail light, recuperation, ride mode and cruise control stay limited to the confirmed
Xiaomi 1S profile. Controls need current standstill telemetry and confirmed read-back. For
Ninebot these control entities stay unavailable.

## When the connection hangs

- Disconnect other Bluetooth apps; keep the scooter switched on and close to the adapter while pairing.
- Check the exact Bluetooth name, model and firmware.
- Press the button only after the prompt and wait out the retry pause.
- Do not reload repeatedly or delete the stored key.
- Download the diagnostics from the integration menu and state model, BLE/DRV, adapter/proxy and what happened.

Enable debug logging if needed:

```yaml
logger:
  logs:
    custom_components.ninebot_e_scooters: debug
```

## Check compatibility and help out

1. Note model, region and BLE/DRV/BMS version in the manufacturer app.
2. Pick the matching profile and check telemetry only at first. Compare battery level, voltage,
   temperature and odometer with the manufacturer app; use the apps one after the other.
3. Test a Home Assistant restart, a scooter restart and a brief range interruption.
4. [Create a model report](https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues/new?template=model-support.yml):
   attach the result, firmware, adapter/proxy and sanitized diagnostics.

An identical Bluetooth name or a successful GATT connection does not prove protocol
compatibility. Missing values, repeated pairing prompts or a differing frame are helpful
feedback as well.

[Detailed test procedure](docs/COMPATIBILITY.md) ·
[Development and model templates](docs/CONTRIBUTING.md) ·
[Architecture](docs/ARCHITECTURE.md) · [Release guide](docs/RELEASING.md) ·
[Changelog](CHANGELOG.md)

## Acknowledgements

Many thanks to **ScooterHacking** for the reverse engineering, the
[wiki](https://wiki.scooterhacking.org/doku.php?id=nbdocs) and the detailed
[Ninebot ES Scooter Protocol PDF](https://wiki.scooterhacking.org/lib/exe/fetch.php?media=ninebot_es_scooter_protocol_918.pdf).
This documentation is the project's most important protocol source.

## License

The project license has not been decided yet. The publication is prepared until the rights are
clarified; this grants no general permission to use. Existing third-party rights remain in
effect. See the [license decision](docs/LICENSING.md) and the
[provenance notes](docs/THIRD_PARTY.md).
