<!-- header:begin (generated from project metadata) -->
<h1 align="center">Ninebot E-Scooters</h1>

<p align="center">
  <img src="https://raw.githubusercontent.com/seb5594/hass-ninebot_e_scooters-integration/main/custom_components/ninebot_e_scooters/brand/logo@2x.png" alt="Ninebot E-Scooters" width="160" height="160">
</p>

---

<p align="center">
  <a href="https://paypal.me/seb5594"><img src="https://img.shields.io/static/v1?label=Support&amp;message=PayPal&amp;color=0070BA&amp;logo=paypal&amp;logoColor=white&amp;style=for-the-badge" alt="PayPal" height="40"></a>
  <a href="https://buymeacoffee.com/seb5594"><img src="https://img.shields.io/static/v1?label=Support&amp;message=Buy%20Me%20a%20Coffee&amp;color=FFDD00&amp;logo=buy-me-a-coffee&amp;logoColor=black&amp;style=for-the-badge" alt="Buy Me a Coffee" height="40"></a><br>
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=seb5594&amp;repository=hass-ninebot_e_scooters-integration&amp;category=integration"><img src="https://img.shields.io/static/v1?label=HACS%20%C2%B7%20Marketplace&amp;message=Add%20integration&amp;color=41BDF5&amp;logo=homeassistantcommunitystore&amp;logoColor=white&amp;style=for-the-badge" alt="HACS · Marketplace" height="28"></a>
  <a href="https://github.com/seb5594/hass-ninebot_e_scooters-integration/actions/workflows/compat.yml"><img src="https://img.shields.io/static/v1?label=home%20assistant&amp;message=%E2%89%A5%202023.2.0&amp;color=1877A5&amp;style=for-the-badge" alt="home assistant" height="28"></a>
  <a href="https://github.com/seb5594/hass-ninebot_e_scooters-integration/releases/tag/v2026.11.11.1"><img src="https://img.shields.io/static/v1?label=version&amp;message=2026.11.11.1&amp;color=1877A5&amp;style=for-the-badge" alt="version" height="28"></a><br>
  <a href="https://github.com/seb5594/hass-ninebot_e_scooters-integration/stargazers"><img src="https://img.shields.io/github/stars/seb5594/hass-ninebot_e_scooters-integration?label=stars&amp;style=flat" alt="stars" height="20"></a>
  <a href="https://github.com/seb5594/hass-ninebot_e_scooters-integration/releases"><img src="https://img.shields.io/github/downloads/seb5594/hass-ninebot_e_scooters-integration/v2026.11.11.1/total?label=downloads&amp;color=1877A5&amp;style=flat" alt="downloads" height="20"></a>
  <a href="https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues"><img src="https://img.shields.io/github/issues/seb5594/hass-ninebot_e_scooters-integration?label=issues&amp;style=flat" alt="issues" height="20"></a>
  <img src="https://img.shields.io/static/v1?label=tests&amp;message=304%20passed&amp;color=2F855A&amp;style=flat" alt="tests" height="20">
  <a href="https://github.com/seb5594/hass-ninebot_e_scooters-integration/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/seb5594/hass-ninebot_e_scooters-integration/ci.yml?branch=main&amp;label=checks&amp;style=flat" alt="checks" height="20"></a>
  <a href="https://github.com/seb5594/hass-ninebot_e_scooters-integration#license"><img src="https://img.shields.io/github/license/seb5594/hass-ninebot_e_scooters-integration?label=license&amp;style=flat" alt="license" height="20"></a>
</p>
<!-- header:end -->

[🇬🇧 English](README.md) · [🇩🇪 Deutsch](docs/README.de.md)

> [!IMPORTANT]
> **Only 1 of 10 model groups has been verified on real hardware so far.** Do you own another
> one? Please [tell me in two minutes whether it works](https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues/new?template=scooter-report.yml).
> It is a short form, and a report that everything works helps as much as a bug report.

Local Home Assistant integration for Ninebot/Segway e-scooters and compatible Xiaomi models.
No cloud account required.

The reference device is a Xiaomi 1S with BLE 1.29 and DRV 1.28. Other profiles are
experimental and need hardware feedback. The integration keeps a working Bluetooth session
alive and reuses stored keys.

## Models and firmware

| Model / family | Protocol / firmware | Features | Status |
| --- | --- | --- | --- |
| Xiaomi 1S | 5A A5, BLE129 / DRV1.28 | Telemetry and guarded controls | Reference device |
| Xiaomi Pro 2 / Essential | 5A A5, BLE129 | Telemetry | Hardware test pending · [report](https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues/new?template=scooter-report.yml&model=Xiaomi%20Mi%20Electric%20Scooter%20Pro%202) |
| Xiaomi M365, four-dot display | Unencrypted 55 AA | Telemetry | Hardware test pending · [report](https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues/new?template=scooter-report.yml&model=Xiaomi%20M365%20%28four-dot%20display%29) |
| Xiaomi M365 Pro | 5A A5, BLE110/122 | Telemetry | Hardware test pending · [report](https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues/new?template=scooter-report.yml&model=Xiaomi%20M365%20Pro) |
| Ninebot ES1 / ES2 / ES3 / ES4 | 5A A5, BLE109/110 | Read-only word registers | Experimental · [report](https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues/new?template=scooter-report.yml&model=Ninebot%20ES1%20%2F%20ES2%20%2F%20ES3%20%2F%20ES4) |
| Ninebot Max G30 / G30P / G30D / G30E / G30LP / G30LE / G30LD | 5A A5, BLE110/113/114 | Read-only word registers | Experimental · [report](https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues/new?template=scooter-report.yml&model=Ninebot%20Max%20G30%20family) |
| Ninebot E22 / E25 / E45 | 5A A5, BLE209/213 | Read-only word registers | Experimental · [report](https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues/new?template=scooter-report.yml&model=Ninebot%20E22%20%2F%20E25%20%2F%20E45) |
| Ninebot F20 / F25 / F30 / F40 / F65 | 5A A5, BLE307, PC address | Read-only word registers | Experimental · [report](https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues/new?template=scooter-report.yml&model=Ninebot%20F20%20%2F%20F25%20%2F%20F30%20%2F%20F40) |
| Ninebot Max G2 / D18 / D28 / D38 | 5A A5, Ninebot serial service | Read-only word registers | Experimental, no report yet · [report](https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues/new?template=scooter-report.yml&model=Ninebot%20Max%20G2%20%2F%20D18%20%2F%20D28%20%2F%20D38) |
| Ninebot F3 / F3 Pro / Max G3 | 5A A5, VCU board numbering | Read-only VCU registers | Experimental, no report yet · [report](https://github.com/seb5594/hass-ninebot_e_scooters-integration/issues/new?template=scooter-report.yml&model=Ninebot%20F3%20%2F%20F3%20Pro%20%2F%20Max%20G3) |

These BLE versions come from public implementations. They do not guarantee compatibility with
every region, dashboard or firmware variant. Xiaomi BLE132 with 5A AB, Xiaomi 3/4 and Ninebot
F2, E2, ZT3, GT and P series are not supported. Model notes in the research catalog do not mean support.

Ninebot scooters report battery level, current, voltage, battery temperatures and the status
word. Odometer, firmware, errors and battery health are queried step by step. Current speed,
external ES batteries and write control for Ninebot are not implemented yet. Missing values stay
unknown.

### Ninebot F3, F3 Pro and Max G3

This generation numbers its boards differently and keeps its values on a vehicle control unit.
The integration reads battery level, remaining range and odometer on every poll; temperature,
error codes and, where the pack has its own board (F3), voltage, current, capacity and charge
cycles follow step by step. A scooter set to **Automatic** is recognized by the board that
answers and shown as "Ninebot F3 / Max G3".

The scooter remembers **one** session password. There are two ways to connect:

- **Pair with the power button.** Home Assistant sets its own password. The Segway app then has
  to be paired again, which in turn replaces the password of Home Assistant. Owners report that
  this generation often ignores the button press, so several attempts can be necessary.
- **Use the password of the Segway app.** Enter it under **Configure → Pairing password**
  (32 hex characters). Home Assistant then logs in like the app does and both keep working.
  The password never leaves the phone, so it has to be read from a Bluetooth capture or a phone
  backup; [ha-ninebot](https://github.com/BobMcGlobus/ha-ninebot) and
  [ha-segway-ninebot](https://github.com/camilo-sx/ha-segway-ninebot) publish tools for that.

## Installation

Requirements: **Home Assistant 2023.2 or newer** and a Bluetooth adapter or an active ESPHome
Bluetooth proxy. Disconnect other scooter apps before setup. Releases before 2026.9 cannot
request a one-shot active scan or replay the newest sighting; the integration then waits for
the scooter's next advertisement instead. Everything else behaves the same.

1. Install through HACS or the Marketplace (see below), or manually from the Home Assistant terminal (SSH or
   Terminal app) with the version you want from the
   [releases](https://github.com/seb5594/hass-ninebot_e_scooters-integration/releases):

   ```bash
   cd /config
   mkdir -p custom_components/ninebot_e_scooters
   wget -O /tmp/ninebot_e_scooters.zip \
     https://github.com/seb5594/hass-ninebot_e_scooters-integration/releases/download/v2026.11.11.1/ninebot_e_scooters.zip
   unzip -o /tmp/ninebot_e_scooters.zip -d custom_components/ninebot_e_scooters
   rm /tmp/ninebot_e_scooters.zip
   ```

   Replace `v2026.11.11.1` with the version you want, then restart Home Assistant.
2. Go to **Settings → Devices & services → Add integration** and search for
   **Ninebot E-Scooters**. Switch the scooter on, select the matching model and tick any
   additional sensors you want (see below).
3. Press the power button once, briefly, only when the centered pairing prompt appears.

For HACS (Home Assistant 2026.10 and older) or the Marketplace (2026.11 and newer, built in under
**Settings → Marketplace**), use the **HACS · Marketplace** button above or add the repository as a
**custom repository → Integration**, then download it; the newest release is installed. `ninebot_e_scooters.zip` contains the integration directly in the
ZIP root and serves HACS and manual installs alike.

**Migrating from `xiaomi_scooter`:** the new technical domain is `ninebot_e_scooters`. This is
not an automatic update of the old config entry. Create a Home Assistant backup first, note your
current entity IDs and remove the old integration. Remove the old component folder, install the
new one and set the scooter up again. Pairing has to be confirmed again. Afterwards check entity
IDs and automations. Both integrations must not connect to the same scooter at the same time.
Do not edit files under `.storage` by hand.

Scooters are recognized by the manufacturer data of their Bluetooth module, so a renamed
scooter is discovered as well. If no device is found: search again, or enter the Bluetooth
address and the exact advertised Bluetooth name. The name is part of the encryption and can differ from the device name you
chose yourself.

## Connection and values

The default polling interval is ten seconds; the options allow five to 120 seconds. For a parked
scooter 20–30 seconds is often enough.

A working session stays open. After an interruption the next attempt needs a fresh Bluetooth
sighting. A stored session is checked first with an encrypted read. Timeouts do not replace the
app key. Repeated failures lengthen the pause; an unconfirmed pairing is retried after one
minute at the earliest. This is meant to reduce unnecessary reconnects. Connection tones
triggered by the firmware can still occur.

Battery level, capacity, voltage, current and power, the odometer, the range reported by the
scooter and the connection are always created. Further sensors come in groups that start switched
off, because they barely change while the scooter is parked: riding data (including the reference
range estimate), temperatures, battery health,
device information and raw status codes. Tick them during setup or later under **Configure**;
unticking a group removes its sensors again. The model and firmware are also shown on the
device page.

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
This documentation is the project's most important protocol source. Where the code
originates and which third-party licenses apply is listed in the
[provenance notes](docs/THIRD_PARTY.md).

<!-- support:begin (generated, shared text) -->
## Say thanks

All my projects are built in my spare time, just for the fun of it. Still, they take a lot of time and care, and many of the smart home gadgets I buy end up here because I want to make them cloud-free and smart-home ready. Every bit of support means a lot to me.

If my work helped you or turned out to be useful, show your appreciation with a hot drink for my next sleepless night.

[![PayPal](https://img.shields.io/static/v1?label=Support&message=PayPal&color=0070BA&logo=paypal&logoColor=white&style=for-the-badge)](https://paypal.me/seb5594) [![Buy Me a Coffee](https://img.shields.io/static/v1?label=Support&message=Buy%20Me%20a%20Coffee&color=FFDD00&logo=buy-me-a-coffee&logoColor=black&style=for-the-badge)](https://buymeacoffee.com/seb5594)
<!-- support:end -->

<!-- license:begin (generated from the license file) -->
## License

[![license](https://img.shields.io/static/v1?label=license&message=MIT&color=5B6770&style=flat)](LICENSE)

Published under the [MIT License](LICENSE).
<!-- license:end -->
