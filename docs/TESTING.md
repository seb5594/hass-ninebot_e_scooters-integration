# Validation and hardware acceptance

The regression suite contains **202 active Python tests** and two frontend cases.
Superseded tests for unavailable historical ZIPs have been removed. No current
functionality is skipped.

`.github/tests/fixtures/xiaomi_1s_vectors.json` contains synthetic vectors produced by the
unchanged 0.9.13 implementation, not hardware captures. Updated default Xiaomi
crypto must produce identical encrypted bytes.

New tests cover word/register boundaries, phone/PC key transitions, complete
multiword reads, concurrent legacy requests, backoff, key validation, assembled
coordinator imports and encrypted saved-session resume with fragmented notifications.

HA-facing tests use doubles. API signatures were checked against HA 2026.9.3.
No running HA installation or real BLE adapter was available. Automated success
is regression evidence, not proof of quieter or faster hardware pairing.

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
