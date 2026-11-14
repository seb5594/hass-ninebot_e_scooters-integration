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

## A closed-source companion app (static analysis only)

Reviewed on 2026-11-14. A closed-source scooter companion app, which ships no public source, was
read as compiled text, both its public web build and its Android package; nothing was run against
a scooter, and the Windows and Linux builds were not examined. Compiled code keeps class and
variable names short, but the literal strings it embeds (error messages, enum tags, UUIDs) survive
compilation and are readable. What they confirm:

- **Four base protocol families**, named `ninebot`, `ninebotCrypto`, `xiaomi` and `xiaomiCrypto` —
  the same split this integration already keeps between the Ninebot word registers, the Ninebot
  chained crypto, the Xiaomi legacy block and Xiaomi 1S crypto.
- **A fifth, distinct Xiaomi service**, discovered separately from the Nordic UART
  (`6e400001-b5a3-f393-e0a9-e50e24dcca9e`, already used here) and the MiBeacon service
  (`0000fe95-0000-1000-8000-00805f9b34fb`, already used here), with its own session counter and an
  ECDH key exchange instead of the BLE129/M365 shared-secret scheme. Error strings name it
  "elliptic." No scooter model is named with it, and the exact service or characteristic UUID and
  the curve could not be confirmed, so this stays a research candidate
  (`protocols/research.py:xiaomi_elliptic`) and nothing more. It would explain why the Xiaomi
  3/4-series models stay unverified here.
- **Register access is categorized** as `writeRegister`, `writeRegisterNoReply`, `readRegister`,
  `readRegisterNoRetry`, `awaitGenericUpdateMsg` and `notifyComplete`. This matches the write/read/
  write-without-reply split already in `protocols/ninebot/packet.py`; `readRegisterNoRetry` reads as
  a client-side retry policy, not a distinct wire command, so it changes nothing here.
- **Writes are verified by a readback**, with dedicated failure states named `REG_VERIFY_FAIL` and
  `CONFIRMATION NOT EQUAL`. `runtime/controls.py` already reads a setting back after writing it
  before accepting the change; this is independent confirmation of that design, not a new one.
- **Ninebot ESC firmware images are TEA- or XTEA-encrypted** for flashing, with a user-overridable
  16-byte key and an "automatic" mode that uses "each device's live configuration." This belongs to
  firmware flashing, which this integration does not perform, so it stays a research note.
- An **"AirLock" feature** is the app's own phone-proximity automation on top of a scooter's
  existing lock, not a property of the BLE protocol itself.

What this pass could **not** recover, and why: no manufacturer company ID, no numeric register
address, and nothing that names or identifies the E2 Pro. A search for model codes (`ES1`…`ES4`,
`G30…`, `E22`/`E25`/`E45`, `F20`…`F65`, `D18`/`D28`/`D38`, `1S`, …) in both builds did turn up
matches, but every one checked in context was a false positive: keyboard key names, minified
identifiers, asset names or compressed font data that happens to contain the same characters, not a
model-to-protocol table. No such table is kept as readable text in either build; a model's protocol
is very likely chosen by code that branches on its serial or advertised name, the same approach this
integration takes, which compiles away into logic no amount of string reading recovers. The native
Windows and Linux clients were not downloaded or inspected, so they may hold more than these two
builds do; this is not a claim that they hold nothing.

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
