# Validation report — 2026.11.11.1

Local verification on 2026-11-11 used Python 3.13.18, pytest 9.1.1, cryptography 50.0.1
and Node.js 22. Home Assistant could not be installed in that environment.

| Check | Result |
| --- | --- |
| Integration regression suite (`.github/tests`) | 304 passed; no skips |
| Rewritten session crypto against the 1.0.0b5 implementation | 10,822 randomized operations in 400 sessions identical: outputs, counters, rejection reasons |
| Recorded sessions of 1.0.0b5 (`released_crypto_sessions.json`) | Reproduced byte for byte |
| Synthetic Xiaomi 1S vectors (`xiaomi_1s_vectors.json`) | Byte-identical |
| Pairing dialog (frontend doubles) | 2 passed |
| Python compilation, cache-version check | Passed |
| Suite inside a genuine Home Assistant (`.github/ha_tests`) | Not run locally; runs in CI |
| pycodestyle | Not run locally; runs in CI |

## What was validated for models without hardware

Every selectable model family runs a complete simulated session: handshake, pairing, one
full read cycle. The simulator is described in [TESTING.md](TESTING.md).

| Family | Checked against | Outcome |
| --- | --- | --- |
| Xiaomi Pro 2, Essential, M365 Pro | Shared 1S block layout | Values decode; no write reaches the scooter |
| Ninebot ES, E, Max G30, F | Register tables of ownbee/ninebot-ble and the ES protocol PDF; serial letters of the ScooterHacking wiki | All 20 documented values decode; one word per request; controller register 0x17 is never read |
| Ninebot Max G2 | Vendor command table | Same registers as the classic families. Trip distance removed from all families: F keeps it at 0xB9, Max G2 at 0xB7 |
| Ninebot D18, D28, D38 | Vendor device table only | Listed with the chained crypto; register table assumed equal to the Max G2 |
| Ninebot F2, E2 | Vendor device table | Listed without the chained crypto. Their adapter was withdrawn before release |
| Ninebot F65 | Third-party hardware report | Added to the F family |
| Ninebot F3, F3 Pro, Max G3 | Vendor command table of the F3 and an owner's measurements | New adapter, see below |

Corrections that came out of the review: every `N2G` serial was taken for an E series
although the ES series shares that prefix, so ES1 to ES4 were never identified. The letters
of the ES series are added, and an `N2G` serial with an unlisted letter no longer names a
family. G30M and the regional E and F editions (E22D/E, E25A/D/E, F20A/D, F30D/E, F40A/D/E,
F60/F60A) were shown as their family only and now carry their own name.

## Ninebot F3 generation (issue 16)

A reported F3 Pro connected and showed no data. The cause: this generation answers the
handshake on Bluetooth module 0x04 instead of the dashboard 0x21 and keeps its values on a
vehicle control unit 0x16. Both are implemented from public documentation and from what
owners measured with other projects. No scooter of this generation was available, and the
diagnostics file of the report could not be retrieved. Until an owner confirms it, the
adapter counts as unverified.

No physical scooter and no live BLE connection were available for any of this. Hardware
acceptance remains in [TESTING.md](TESTING.md).
