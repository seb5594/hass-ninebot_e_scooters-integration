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

## P4: ECDH and AES-CCM (xiaomi_mi_ec research candidate)

Reviewed on 2026-11-14. A peer-reviewed security paper, Casagrande, Cestaro, Losiouk, Conti and
Antonioli, ["E-Spoofer: Attacking and Defending Xiaomi Electric Scooter
Ecosystem"](https://francozappa.github.io/publication/2023/espoofer/paper.pdf) (WiSec '23, DOI
10.1145/3558482.3590176), names and fully describes this as one of four Xiaomi
application-layer protocols found across all Xiaomi e-scooters from 2016 to 2021. Its Table 4
gives the exact bytes of every step; the account below follows it, and the byte values are
transcribed from that table, so check them against the paper before relying on them.

**Pairing** runs on characteristic `00000019-...`, unencrypted. The e-scooter advertises a
pairable window for seventeen seconds after its headlight button is held down — the paper's
root cause V2, "Unintentional Pairing mode" — the same kind of physical confirmation this
integration's own Ninebot and Xiaomi 1S pairing already uses, not a cloud step. The scooter
sends a sixteen-byte challenge (`chal`); the devices exchange public keys on the NIST P-256
curve (as a raw 64-byte X‖Y pair each, reassembled from several 16-byte GATT writes) and derive
an ECDH shared secret (`ss`). From it, `pk||otk=HKDF-SHA256(ss, salt="", info="mible-setup-info")`
gives a pairing key (`pk`) and a one-time key (`otk`); the app alone proves it reached the same
`otk` with `resp=AES-CCM(key=otk, input=chal)`. **Pairing authenticates the app to the scooter,
not the other way around** — the paper's root cause V1, "Unauthenticated Pairing": nothing in
this exchange proves the pairer is the real Mi Home app, which is also why the paper's
Malicious Pairing attack needs no Xiaomi account, no cloud connection and no pre-shared secret
of any kind to complete Pairing. A scooter is connectable and physically confirmable the same
way M365/1S already is in this codebase; the passive, cloud-issued "beaconkey" that non-
connectable Xiaomi BLE sensors need (see below) does not appear to apply here.

**Session** runs on characteristic `00000010-...`, then on the same Nordic UART characteristics
(`6e400002`/`6e400003`) this file's plain, unencrypted Ninebot/Xiaomi candidates already use.
Both sides exchange sixteen-byte randoms (`rand_app`, `rand_esc`) and derive
`sk_esc||sk_app||n_esc||n_app=HKDF-SHA256(pk, salt=rand_app‖rand_esc, info="mible-login-info")`:
two directional AES-CCM-128 keys and two nonce halves. Each side then sends
`HMAC-SHA256(key=sk_*, input=rand_esc‖rand_app)` for its own key; a mismatch ends the session.
A data-channel frame is `55 AB`, a length byte, a 2-byte sequence, the AES-CCM payload (a
4-byte tag), and a checksum that is the same one's-complement 16-bit byte sum this file's
Ninebot candidates already use — not something specific to this scheme. The exact AES-CCM
nonce construction for these frames is not stated by the paper and is not guessed at here.

Three independent public projects for other, non-scooter Xiaomi hardware corroborate the shape
(none of them need a scooter's physical pairing confirmation, since their devices use a
different, cloud-issued key instead):

| Source | Revision | Purpose |
| --- | --- | --- |
| [haohaozi328-arch/miot-ble-sdk](https://github.com/haohaozi328-arch/miot-ble-sdk/tree/90dd918fb82f565329c37c0ccd51b2fefd58e2e0) | `90dd918f` | The same GATT handles 0x0010/0x0019/0x001A; tested on ten-plus sensors, a button and a body scale |
| [clairefiorettiythzr6802-eng/xiaomi-diffuser-ble](https://github.com/clairefiorettiythzr6802-eng/xiaomi-diffuser-ble/tree/96268a53e3c8ba4443dd322ecaede606ec7c89c6) | `96268a53` | The ECDH+HKDF shape and the 4-byte AES-CCM tag, on a Mijia smart diffuser |
| [kbpk/xiaomi-s400-homeassistant](https://github.com/kbpk/xiaomi-s400-homeassistant/tree/60569f5826658c9bab617a0d9f2c86988ca48fa2) | `60569f58` | Names the P-256 curve explicitly; the same two 4-byte responses, 0x11000000/0x21000000 |

`protocols/research.py` keeps the primitives, the frame shape and every command byte Table 4
gives, so a future, hardware-tested adapter does not have to look any of it up again. This
stays a research candidate regardless: this integration has not been tested against a scooter
that speaks P4, and nothing here is wired into a live session without that.

`docs/tools/fetch_xiaomi_ble_credentials.py` reimplements the openly published Xiaomi cloud
login that [PiotrMachowski/Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor)
and other long-standing community tools already use, to read a "beaconkey" (bindkey) a signed-in
Mi account holds for a device. [Home Assistant's Xiaomi BLE
integration](https://www.home-assistant.io/integrations/xiaomi_ble/) documents that key for the
passive, non-connectable MiBeacon sensors it supports: 12 bytes for v2/v3 devices, 16 bytes for
v4/v5. The tool was first written on the understanding that a scooter's P4 pairing would need
the same kind of key; the paper above says otherwise for Pairing itself. It may still be useful
for a scooter that was already bound through Mi Home and does not need to be paired again, or
simply for other Xiaomi BLE devices that do need a cloud-issued key; it stays in the repository
for that, with this correction attached.

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
