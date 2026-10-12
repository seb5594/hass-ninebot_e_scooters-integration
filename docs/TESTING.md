# Validation and hardware acceptance

The regression suite contains **218 active Python tests** and two frontend cases.
Superseded tests for unavailable historical ZIPs have been removed. No current
functionality is skipped.

`.github/tests/fixtures/xiaomi_1s_vectors.json` contains synthetic vectors produced by the
unchanged 0.9.13 implementation, not hardware captures. Updated default Xiaomi
crypto must produce identical encrypted bytes.

New tests cover word/register boundaries, phone/PC key transitions, complete
multiword reads, concurrent legacy requests, backoff, key validation, assembled
coordinator imports and encrypted saved-session resume with fragmented notifications.

The regular suite uses Home Assistant doubles; `compat.py` is loaded for real, around those
doubles. A second suite in `.github/ha_tests` runs the integration inside a genuine Home
Assistant core: config, options and reconfigure flows, entity creation and naming, asset
registration, Bluetooth callback registration, diagnostics redaction and unload. Only the
Bluetooth hardware, the frontend and the web server are replaced, by doubles that copy the
signatures of the installed release.

The shared engine runs both suites on every release listed in its `ha_releases.json` at or
above the minimum in `hacs.json` (currently 2023.2.5 to 2026.9.4, on Python 3.10 to 3.14);
the Compatibility workflow does so weekly and for changes to the integration. Locally:
`python .engine/.scripts/ha_matrix.py run 2023.2.5 2026.9.4`.

No real BLE adapter or scooter was available. Automated success is regression evidence,
not proof of quieter or faster hardware pairing, and not of how the older releases behave
with a real adapter.

## Xiaomi 1S acceptance

1. Back up HA and follow the one-time domain transition described in the README.
2. Check entity IDs, device assignments and automations after setup; record any changes.
3. Test normal telemetry, HA restart and scooter power cycle.
4. Observe a connected session for 30 minutes; record disconnects, tones and button prompts.
5. Test temporary range loss and competing-app disconnection. Verify key retention and growing retry pauses.
6. Physically verify controls while stationary. Confirm controls become unavailable with stale speed or link loss.
7. Reload/unload during a pending request; ensure old-client cleanup precedes a new client.

## Each new Ninebot model

Record model/region, BLE/DRV/BMS, packet prefix, GATT properties and adapter/proxy.
Confirm profile/host role. Compare battery, signed current, voltage, temperatures,
odometer and firmware against the manufacturer app. Missing optional fields must
stay unknown. Confirm no setting-write opcode is emitted. Repeat restart, power
cycle, range and competing-app checks. Sanitize keys, serials and MACs before
sharing samples. Use `.github/ISSUE_TEMPLATE/model-support.yml` for results.
