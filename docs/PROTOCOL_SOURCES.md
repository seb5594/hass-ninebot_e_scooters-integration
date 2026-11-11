# Protocol sources

Primary documentation: [ScooterHacking Wiki](https://wiki.scooterhacking.org/doku.php?id=nbdocs)
and [Ninebot ES Scooter Protocol PDF](https://wiki.scooterhacking.org/lib/exe/fetch.php?media=ninebot_es_scooter_protocol_918.pdf).
PDF sections 2.1–2.7 describe frames, addresses, commands and checksums; sections
4–5 describe ES and BMS registers. The ES table must not be assumed valid for
every Xiaomi or newer Ninebot model.

The following pinned comparisons provide an audit trail rather than additional
acknowledgements. Reviewed on 2026-10-01:

| Source | Revision | Purpose |
| --- | --- | --- |
| [ScooterHacking/NinebotCrypto](https://github.com/scooterhacking/NinebotCrypto/tree/9ba0c551488a8433cea173d1bed843240f63ec30) | `9ba0c551` | Handshake, BLE versions, phone host |
| [ownbee/ninebot-ble](https://github.com/ownbee/ninebot-ble/tree/1850351f5bce9627f612fd1141489ed7a575be61) | `1850351f` | Word reads, scales and F PC host |
| [WalkTheEarth/ninebot-ble](https://github.com/WalkTheEarth/ninebot-ble/tree/a9b81544c85483af028c0894abff9c8b3f08d87b) | `a9b81544` | Manufacturer IDs 0x424E/0x434E and serial-style names for discovery |
| [dnandha/miauth](https://github.com/dnandha/miauth/tree/7df4f35c258f926ce396df3691d7f91d86ad761e) | `7df4f35c` | Independent crypto/key-stage comparison |
| [HA Bluetooth API](https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/components/bluetooth/api.py) | `2026.9.3` | Callback replay, active scans and history rearming |

Reviewed on 2026-11-11 for the session crypto rewrite and the newer generations:

| Source | Purpose |
| --- | --- |
| [Segway-Ninebot BLE Protocol](https://nootnooot.codeberg.page/segway-ninebot-ble/) (Apache-2.0) | Encryption and handshake description the crypto module is written from; serial services; vendor command tables of the Max G2 and the F3 |
| [BobMcGlobus/ha-ninebot issue 9](https://github.com/BobMcGlobus/ha-ninebot/issues/9) | An F3 owner's measurements: Bluetooth module 0x04, VCU 0x16, battery board 0x07, scales compared with the vendor app, unreliable button pairing |
| [camilo-sx/ha-segway-ninebot](https://github.com/camilo-sx/ha-segway-ninebot) | F3 Pro read on hardware with the vendor app's password and without a 0x5C request |
| [nbeseries](https://wiki.scooterhacking.org/doku.php?id=nbeseries), [nbmax](https://wiki.scooterhacking.org/doku.php?id=nbmax), [nbfseries](https://wiki.scooterhacking.org/doku.php?id=nbfseries) | Serial variant letters of the E, Max and F series |
| [Ninebot ESX serial/region](https://joeybabcock.me/wiki/Ninebot_ESX_Change_Serial/Region), [Max G2](https://joeybabcock.me/wiki/Ninebot_Max_G2_D) | Serial variant letters of the ES series and the Max G2 |

What rests on a single source: the odometer scale of the VCU generation (0.1 km), its
frame temperature register 0x6B and the battery board registers. The two sources disagree
on the index of speed and ride mode, so neither is read. The Max G2 command table matches
the classic registers; D18, D28 and D38 are assumed to share it, their own tables could not
be retrieved. The vendor device table lists F2 and E2 with XOR-obfuscated frames instead of
the chained crypto, so they stay without an adapter. An F65 is reported working with the
F-series protocol by [scottbambrick/ha-ninebot](https://github.com/scottbambrick/ha-ninebot).

Upstream documents ES BLE109/110, Max BLE110/113/114, E BLE209/213 and F BLE307.
Some Xiaomi BLE132 dashboards use 5A AB and remain disabled here. The ninebot-ble
author reports access to an F-series scooter and uses PC address 0x3D. That is
protocol evidence, not a hardware test of this integration.

## Issues corrected in the supplied implementation

- Discovery accepted unrelated devices advertising the shared Nordic UART service.
- Crypto key transitions were fixed to phone address 0x3E, preventing PC-host reuse.
- The legacy link promised serialized reads but had no lock; concurrent callers
  could discard each other's replies.
- Some Xiaomi blocks decoded without checking source or read opcode.
- Repeated failed sessions retained short fixed retry intervals.
- Reconfiguration retained another physical scooter's pairing state.
- Saved keys were decoded without validating the required 16-byte length.
- Authenticated receive queues had no memory bound.

The original MAC/checksum validation, stored-key probes, late pairing ACK retention,
fresh-device policy and disabled scanner failover are retained.
