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

Reviewed on 2026-11-14, from [ScooterHacking Utility](https://utility.cfw.sh/), v2.7 of its
Android build: a GATT-connected scheme the newer Xiaomi generations it supports speak, on the
MiBeacon service this file already uses (`0000fe95-...`). The register exchange (ECDH on the
NIST P-256 curve, then a key-confirmation step) runs over characteristic `00000019-...`; the
login that follows and the property traffic after it run over `00000010-...`. A full public
key never crosses the wire: only its raw 64-byte X‖Y pair does, reassembled from several
16-byte GATT writes, each side re-adding the "uncompressed point" marker locally. Once both
sides confirm the same ECDH secret with `HKDF-SHA256(secret, salt=device_nonce+host_nonce,
info="mible-login-info")`, each of the resulting keys is checked with an
`HMAC-SHA256(key, device_nonce+host_nonce)` the other side already sent; a mismatch ends the
session. The 40-byte HKDF output splits into what receives (verifies and decrypts what the
device sends) and what sends, 16 bytes each, then a 4-byte nonce seed for each direction.
A data-channel frame's AES-CCM nonce is that direction's 4-byte seed, four zero bytes, the
frame's own 2-byte little-endian sequence number, then two more zero bytes — 12 bytes. The
frame itself is `55 AB`, a length byte, the sequence, the AES-CCM payload with a 4-byte tag,
and a checksum that is the same one's-complement 16-bit byte sum this file's Ninebot
candidates already use — not something specific to this scheme. It rides over the same Nordic
UART characteristics (`6e400002`/`6e400003`) the plain, unencrypted scheme already on this
service uses; only the register and login exchange has its own two characteristics. The client
announces itself with a string such as `blt.4.159` plus ten random characters, comparable to a
user agent. The one paired-key bundle a device needs is kept locally once obtained, indexed by
the scooter's Bluetooth MAC address — not by anything that would identify its model.

Three independent public projects for other, non-scooter Xiaomi hardware corroborate the shape:

| Source | Revision | Purpose |
| --- | --- | --- |
| [haohaozi328-arch/miot-ble-sdk](https://github.com/haohaozi328-arch/miot-ble-sdk/tree/90dd918fb82f565329c37c0ccd51b2fefd58e2e0) | `90dd918f` | The same GATT handles 0x0010/0x0019/0x001A; tested on ten-plus sensors, a button and a body scale |
| [clairefiorettiythzr6802-eng/xiaomi-diffuser-ble](https://github.com/clairefiorettiythzr6802-eng/xiaomi-diffuser-ble/tree/96268a53e3c8ba4443dd322ecaede606ec7c89c6) | `96268a53` | The ECDH+HKDF shape and the 4-byte AES-CCM tag, on a Mijia smart diffuser |
| [kbpk/xiaomi-s400-homeassistant](https://github.com/kbpk/xiaomi-s400-homeassistant/tree/60569f5826658c9bab617a0d9f2c86988ca48fa2) | `60569f58` | Names the P-256 curve explicitly; the same two 4-byte responses, 0x11000000/0x21000000 |

[Home Assistant's Xiaomi BLE integration](https://www.home-assistant.io/integrations/xiaomi_ble/)
documents the paired key these devices need as a "bindkey" or "beaconkey": 12 bytes for the
older MiBeacon v2/v3 devices, 16 bytes for v4/v5, normally read from a signed-in Xiaomi account.
None of the four sources say how a scooter would obtain one. `protocols/research.py` keeps the
primitives and the frame shape so a future, hardware-tested adapter does not have to look them
up again; without a way to obtain the paired key, none of it is reachable from a live session.

`docs/tools/fetch_xiaomi_ble_credentials.py` reimplements the openly published Xiaomi cloud
login that [PiotrMachowski/Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor)
and other long-standing community tools already use, to read the one piece of this that lives
outside any firmware: the "beaconkey" (bindkey) a signed-in Mi account already holds for a
device. Run by hand, with your own account, it cannot get the second value this scheme's login
needs, a "device token": no public source documents the endpoint for it (the diffuser project
above only names it, as `/v2/blemesh/query_dev`), so the tool's attempt at it is openly
unverified and may simply fail. Fetching either value is not something this integration, or any
tool that ships with it, does on its own; it stays a manual, one-time step on hardware this file
does not otherwise touch.

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
