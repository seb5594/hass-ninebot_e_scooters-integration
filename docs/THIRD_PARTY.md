# Third-party provenance

The project is published under the MIT License (see `LICENSE`). Attribution and license
obligations for existing third-party material remain independent of that choice and of the
project's acknowledgements.

| Material | Origin and status |
| --- | --- |
| Crypto protocol implementation | The supplied baseline identifies ScooterHacking/NinebotCrypto as its basis. NinebotCrypto is AGPL-3.0; its derivative-work obligations are not replaced by the MIT License and are still to be resolved, either by compliance or by an independent implementation. |
| Xiaomi packet definitions | The supplied baseline cites the public M365 protocol and m365py message definitions. Those source attributions are retained. |
| Research comparisons | dnandha/miauth (AGPL-3.0) was examined as a comparison, not introduced as a runtime dependency. ownbee/ninebot-ble (MIT) informed register/host-role research; its client source is not bundled. |
| Runtime dependencies | Home Assistant, Bleak, bleak-retry-connector and cryptography retain their respective licenses. |

Changing names, formatting or expressions does not remove obligations for reused
code. No statement here grants a commercial relicensing right over third-party
material. Protocol facts and independently written code must be distinguished
from copied expression during the rights review.

Primary protocol documentation and pinned research references are in
[PROTOCOL_SOURCES.md](docs/PROTOCOL_SOURCES.md). The explicit acknowledgement
appears in the README and is dedicated to ScooterHacking.
