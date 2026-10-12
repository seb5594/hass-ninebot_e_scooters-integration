# Architecture

The technical domain is `ninebot_e_scooters`. Home Assistant domains use
underscores; hyphens remain valid in the repository and display name. Changing
from `xiaomi_scooter` requires a one-time setup as documented in the README.

```text
custom_components/ninebot_e_scooters/
  __init__.py        HA lifecycle and fresh advertisement callbacks
  config_flow.py     Discovery, model choice, options and reconfiguration
  coordinator.py     Session ownership and HA coordinator initialization
  discovery.py       Conservative advertisement identification
  utilities.py       Key/numeric validation, retry policy and Python 3.10 shims
  compat.py          Everything that differs between Home Assistant releases
  storage.py         Last verified telemetry, without crypto material
  models/
    profiles.py      Model/serial evidence and write capabilities
    transports.py    GATT family and phone/PC host roles
  protocols/
    data.py          Transport-independent ScooterData
    constants.py     GATT and wire constants, independent of HA
    xiaomi.py        Legacy framing and Xiaomi block decoding
    legacy.py        Serialized 55 AA requests
    research.py      Inert future candidates
    ninebot/
      packet.py      Logical frames, opcodes and ordered offsets
      crypto.py      Persistent chained crypto
      registers.py   Independent Ninebot read table
  runtime/
    connection.py    Fresh devices and deterministic cleanup
    session.py       Saved-key resume and physical pairing
    requests.py      Fragments, encryption and reply correlation
    telemetry.py     Polling, freshness and snapshots
    ninebot.py       Word reads and optional-read rotation
    controls.py      Xiaomi stationary/readback gates
    device.py        Identity, capabilities and diagnostics
    constants.py     Timing and the retained Xiaomi probe schedule
    errors.py        Shared session error
  entity.py          Common HA device metadata and registry cleanup
  sensor_groups.py   Optional sensor groups chosen in setup and options
  sensor.py / binary_sensor.py / switch.py / lock.py / select.py
  diagnostics.py     Export redaction
  brand/             Icon and logo for discovery (Home Assistant 2026.3+)
```

Runtime mixins share one coordinator and one command lock. Authentication and
reads hold that lock. Shutdown wakes a pending waiter, acquires the same lock
and releases the original client. Notification callbacks bind to that exact
client so old-client traffic cannot mutate a replacement session.

The old top-level protocol modules are compatibility imports. Internal code uses
the implementations directly. They do not create another HA integration domain.

Xiaomi blocks and Ninebot word registers have separate decoders. Word tables are
ordered by target/index; byte-offset structures follow wire order. The Xiaomi
optional read schedule retains its existing priority order to preserve which
measurements appear first on the reference scooter.

Only decoded telemetry resets retry backoff. GATT alone is not authentication.
Keys remain saved across transient errors; reconfiguration to another physical
address starts with separate credentials. Scanner failover remains disabled.
