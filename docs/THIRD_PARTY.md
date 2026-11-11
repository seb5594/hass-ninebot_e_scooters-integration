# Third-party provenance

The project is published under the MIT License (see `LICENSE`). Attribution and license
obligations for existing third-party material remain independent of that choice and of the
project's acknowledgements.

| Material | Origin and status |
| --- | --- |
| Session crypto (`protocols/ninebot/crypto.py`) | Rewritten for 2026.11.11.1 from the public description of the scheme at nootnooot.codeberg.page/segway-ninebot-ble (documentation under Apache-2.0). Up to 1.0.0b5 the module went back to ScooterHacking/NinebotCrypto (AGPL-3.0). The rewrite shares no code with it, but it was not a clean-room effort: the earlier module was known to the author. Recorded sessions of 1.0.0b5 keep both byte-identical on the wire. |
| Firmware constant | The 16-byte seed of the first handshake key is a value of the scooter firmware and appears in every public implementation. |
| Xiaomi packet definitions | The supplied baseline cites the public M365 protocol and m365py message definitions. Those source attributions are retained. |
| Register layouts | Indices, widths and scales are protocol facts taken from the sources in PROTOCOL_SOURCES.md; the tables and decoders are written for this project. |
| Research comparisons | dnandha/miauth (AGPL-3.0), BobMcGlobus/ha-ninebot (AGPL-3.0) and camilo-sx/ha-segway-ninebot (Apache-2.0) were consulted for what their authors measured on hardware, not for code. ownbee/ninebot-ble (MIT) informed register/host-role research; its client source is not bundled. |
| Runtime dependencies | Home Assistant, Bleak, bleak-retry-connector and cryptography retain their respective licenses. |

Changing names, formatting or expressions does not remove obligations for reused
code. No statement here grants a commercial relicensing right over third-party
material. Protocol facts and independently written code must be distinguished
from copied expression during the rights review.

Primary protocol documentation and pinned research references are in
[PROTOCOL_SOURCES.md](PROTOCOL_SOURCES.md). The explicit acknowledgement
appears in the README and is dedicated to ScooterHacking.
