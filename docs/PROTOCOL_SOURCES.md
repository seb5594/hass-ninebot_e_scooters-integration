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

## MIoT BLE Spec v2 (xiaomi_mi_ec research candidate)

Reviewed on 2026-11-14. Three independent projects, none about scooters, document a
GATT-connected scheme other Xiaomi IoT devices use (sensors, a body scale, buttons, lights):
an ECDH exchange on the NIST P-256 curve, HKDF-SHA256 session keys and AES-CCM framing.

| Source | Revision | Purpose |
| --- | --- | --- |
| [haohaozi328-arch/miot-ble-sdk](https://github.com/haohaozi328-arch/miot-ble-sdk/tree/90dd918fb82f565329c37c0ccd51b2fefd58e2e0) | `90dd918f` | GATT handles 0x0010/0x0019/0x001A; tested on ten-plus sensors, buttons and a scale |
| [clairefiorettiythzr6802-eng/xiaomi-diffuser-ble](https://github.com/clairefiorettiythzr6802-eng/xiaomi-diffuser-ble/tree/96268a53e3c8ba4443dd322ecaede606ec7c89c6) | `96268a53` | ECDH+HKDF shape, 4-byte AES-CCM tag, login opcode 0x50 (replacing an older 0x20) |
| [kbpk/xiaomi-s400-homeassistant](https://github.com/kbpk/xiaomi-s400-homeassistant/tree/60569f5826658c9bab617a0d9f2c86988ca48fa2) | `60569f58` | Names the P-256 curve; register/login success as 4-byte frames 0x11000000/0x21000000 |

[Home Assistant's Xiaomi BLE integration](https://www.home-assistant.io/integrations/xiaomi_ble/)
documents the paired key these devices need as a "bindkey" or "beaconkey": 12 bytes for the
older MiBeacon v2/v3 devices, 16 bytes for v4/v5. None of the three sources above say how a
scooter would obtain one, and none names a scooter at all; this was filed as `xiaomi_mi_ec`
under a "55 AB" frame prefix inherited from the older, plain Xiaomi serial stream, which does
not apply here — it is a sequence of 4-byte opcodes written to a GATT handle, not a
byte-prefixed stream. `protocols/research.py` keeps the primitives (ECDH on P-256, HKDF-SHA256,
AES-CCM) so a future, hardware-tested adapter does not have to look them up again; without a
way to obtain the paired key, nothing here is reachable from a live session.

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
