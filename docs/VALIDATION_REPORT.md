# Validation report — v1.0.0 Beta 1

Local verification on 2026-10-02 used Python 3.12.14, pytest 8.3.5,
cryptography 50.0.0 and Node.js 24.19.0.

| Check | Result |
| --- | --- |
| Integration regression suite | 202 passed; no skips |
| Centered pairing modal, notification lifecycle, hidden screen and dismissal | 2 passed with frontend doubles |
| Shared engine versions, draft/prerelease flags, checksums and immutable releases | 5 passed |
| Python compilation and pycodestyle | Passed |
| Executable Python comparison to 0.10.0 after namespace/cache-version normalization | No differences |
| Synthetic Xiaomi encrypted baseline vectors | Byte-identical |
| HACS/manual/source ZIP integrity and reproducibility | Verified locally |

The technical namespace changes to `ninebot_e_scooters`; earlier config entries
require setup under the new domain. No Bluetooth handshake, register parser or
ScooterCoordinator behavior was changed in this beta preparation.

The frontend cases use a DOM/WebSocket double. They verify the positioning rules
and notification state transitions, not rendering in a running HA browser.
No physical scooter, live BLE connection or running Home Assistant instance was
available. CI includes Python 3.12 and 3.14; only the local 3.12 run is reported
here. Hardware acceptance remains in [TESTING.md](TESTING.md).
