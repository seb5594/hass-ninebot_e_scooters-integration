# Contributing

Write English code, comments and docstrings. User strings belong in the translation
files. Keep `ninebot_e_scooters` and entity unique IDs stable after Beta 1.

## Checks

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m compileall -q custom_components
python -m pycodestyle custom_components
node --test .github/tests/frontend/*.test.cjs
python .github/checks/frontend_cache_version.py
```

Tests live in `.github/tests`. The pull request pipeline runs the same checks through the
shared engine and builds the installation ZIP.

The suite uses pure protocol modules and HA doubles. It does not connect to hardware.
Follow [TESTING.md](TESTING.md) before marking a model/firmware verified.

## Reuse an existing model adapter

Establish the BLE firmware, frame prefix, GATT characteristics, host role and read
layout first. Marketing names and shared UART services do not prove compatibility.
If all match the G30 adapter, add a record to `models/profiles.py`:

```python
# Example only; enable after collecting protocol evidence.
ModelProfile("Ninebot New G30 Variant", "Segway-Ninebot", "ninebot_max")
```

Add full-serial fixtures if the prefix is documented and a profile-selection test.
Do not infer an exact model from an incomplete serial or advertised name. Keep
`hardware_tested=False` and empty `writable_settings` until reviewed hardware evidence exists.

## Add a read register

Insert its descriptor in `protocols/ninebot/registers.py`, ordered by target/index.
The existing current register demonstrates signed hundredths of an ampere:

```python
RegisterSpec(
    DeviceId.BMS, 0x33, ("battery_current_a",),
    encoding="signed", scale=0.01,
)
```

Reads request two bytes per word. Multiword blocks advance the register index and
are committed only when every word arrives. Add a decoding fixture:

```python
data = ScooterData()
packet = NinebotPacket(DeviceId.BMS, DeviceId.PHONE, CMD_READ_ACK, 0x33, b"\x85\xff")
assert apply_packet(data, packet)
assert data.battery_current_a == -1.23
```

Test short data, wrong source/destination and unsupported opcodes too. Controller
`0x17` contains pairing credentials and must not become telemetry. Keep uncertain
reads optional and backed off. Missing optional registers must not destroy good sessions.

## New authentication and controls

A new frame prefix or handshake needs a separate implementation. `5A A5`,
`5A AB`, `55 AA` and `55 AB` are distinct protocols. Provide fixtures for key
transitions, fragments, replay rejection, counter rollover and link loss. Preserve
the default phone-address Xiaomi wire vectors. The F adapter's PC host role is
intentional and owned by its transport profile.

Controls require separate evidence: register, legal values, current stationary
telemetry and confirmed readback. Never reuse Xiaomi lock/light/mode values on
Ninebot solely because a register number matches. A readable status bit does not
authorize a write. Review [THIRD_PARTY.md](../THIRD_PARTY.md) before publication.

## Submit a change

1. Fork the repository and create a branch, for example `model/g30-variant`.
2. Make one focused change; add protocol fixtures and run the checks above.
3. Open a pull request describing the model/firmware, expected behavior and test results.
4. Include hardware evidence before changing a profile to verified. Never submit app keys.

For reports without code, follow [COMPATIBILITY.md](COMPATIBILITY.md). A successful
read on one firmware is a result for that firmware, not a claim for a whole family.
