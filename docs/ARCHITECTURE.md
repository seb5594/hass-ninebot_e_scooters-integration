# Architecture

The technical domain is `ninebot_e_scooters`. Home Assistant domains use
underscores; hyphens remain valid in the repository and display name. Changing
from `xiaomi_scooter` requires a one-time setup as documented in the README.

```text
custom_components/ninebot_e_scooters/
  __init__.py        HA lifecycle and fresh advertisement callbacks
  config_flow.py     Discovery, model choice, options and reconfiguration
  coordinator.py     Session ownership and HA coordinator initialization
  const.py           Domain, platforms and option keys
  entity.py          Common HA device metadata and registry cleanup
  sensor.py / binary_sensor.py / switch.py / lock.py / select.py
  diagnostics.py     Export redaction
  helpers/           Shared by the config flow, the coordinator and the platforms
    compat.py        Everything that differs between Home Assistant releases
    discovery.py     Conservative advertisement identification
    feedback.py      Invitation to report an unverified model
    sensor_groups.py Optional sensor groups chosen in setup and options
    storage.py       Last verified telemetry, without crypto material
    utilities.py     Key/numeric validation, retry policy and Python 3.10 shims
  models/
    profiles.py      Model/serial evidence and write capabilities
    serials.py       Model hints from Segway-Ninebot serial numbers
    transports.py    Per family: serial service, host role, handshake boards, register map
  protocols/
    data.py          Transport-independent ScooterData
    constants.py     GATT and wire constants, independent of HA
    gatt.py          The two serial services and how one is chosen
    xiaomi.py        Legacy framing and Xiaomi block decoding
    legacy.py        Serialized 55 AA requests
    research.py      Inert future candidates
    ninebot/
      packet.py      Logical frames, opcodes and ordered offsets
      crypto.py      Session encryption and its three handshake keys
      registers.py   Read-only register maps: classic (ESC/BMS) and VCU generation
  runtime/
    connection.py    Fresh devices and deterministic cleanup
    session.py       Handshake, saved-key resume and physical pairing
    requests.py      Fragments, encryption and reply correlation
    telemetry.py     Polling, freshness and snapshots
    ninebot.py       Word reads and optional-read rotation
    controls.py      Xiaomi stationary/readback gates
    device.py        Identity, capabilities and diagnostics
    constants.py     Timing and the retained Xiaomi probe schedule
    errors.py        Shared session error
  brand/             Icon and logo for discovery (Home Assistant 2026.3+)
```

Runtime mixins share one coordinator and one command lock. Authentication and
reads hold that lock. Shutdown wakes a pending waiter, acquires the same lock
and releases the original client. Notification callbacks bind to that exact
client so old-client traffic cannot mutate a replacement session.

Only modules Home Assistant loads by name stay at the top level. The compatibility
imports of earlier releases (`protocol.py`, `ninebot_crypto.py` and others) are gone;
nothing outside the integration used them.

A session asks the Bluetooth module for a challenge before anything else. Classic
scooters answer on the dashboard address 0x21, the F3 generation on board 0x04. A family
names the board it is documented with; after complete silence a Ninebot session asks the
other one, and an unidentified scooter is then recognized by the board that answered.
Xiaomi sessions never leave 0x21.

Xiaomi blocks and Ninebot word registers have separate decoders. Word tables are
ordered by target/index; byte-offset structures follow wire order. The Xiaomi
optional read schedule retains its existing priority order to preserve which
measurements appear first on the reference scooter.

Only decoded telemetry resets retry backoff. GATT alone is not authentication.
Keys remain saved across transient errors; reconfiguration to another physical
address starts with separate credentials. Scanner failover remains disabled.
