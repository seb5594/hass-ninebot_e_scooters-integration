"""BLE transport capabilities separated from scooter identity and register writes.

An implemented adapter and a documented firmware are not hardware validation.
Xiaomi blocks and Ninebot word tables share only their UART and crypto envelope.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..protocols.constants import NUS_NOTIFY_UUID, NUS_SERVICE_UUID, NUS_WRITE_UUID
from ..protocols.ninebot.packet import DeviceId


@dataclass(frozen=True, slots=True)
class TransportProfile:
    """Describe the GATT and authentication requirements for one family."""

    family: str
    documented_ble_versions: tuple[str, ...]
    adapter_implemented: bool = False
    service_uuid: str | None = None
    write_uuid: str | None = None
    notify_uuid: str | None = None
    host_id: DeviceId = DeviceId.PHONE


# Version families are documented by ScooterHacking/NinebotCrypto. A future
# transport adapter must provide its own discovery filter, crypto handshake,
# telemetry register map, capability gates and readback tests.
TRANSPORT_PROFILES: dict[str, TransportProfile] = {
    "unverified": TransportProfile("unverified", ()),
    "xiaomi_ble129": TransportProfile(
        "xiaomi_ble129", ("BLE129",), True,
        NUS_SERVICE_UUID, NUS_WRITE_UUID, NUS_NOTIFY_UUID,
    ),
    # M365 Pro BLE110/122 uses the 5A A5 chained crypto handshake. The
    # original four-dot M365 uses unencrypted 55 AA over the same NUS link.
    "xiaomi_m365_pro_crypto": TransportProfile(
        "xiaomi_m365_pro_crypto", ("BLE110", "BLE122"), True,
        NUS_SERVICE_UUID, NUS_WRITE_UUID, NUS_NOTIFY_UUID,
    ),
    "xiaomi_m365_legacy": TransportProfile(
        "xiaomi_m365_legacy", ("55 AA (four-dot display)",), True,
        NUS_SERVICE_UUID, NUS_WRITE_UUID, NUS_NOTIFY_UUID,
    ),
    "ninebot_es": TransportProfile(
        "ninebot_es", ("BLE109", "BLE110"), True,
        NUS_SERVICE_UUID, NUS_WRITE_UUID, NUS_NOTIFY_UUID,
    ),
    "ninebot_max": TransportProfile(
        "ninebot_max", ("BLE110", "BLE113", "BLE114"), True,
        NUS_SERVICE_UUID, NUS_WRITE_UUID, NUS_NOTIFY_UUID,
    ),
    "ninebot_e": TransportProfile(
        "ninebot_e", ("BLE209", "BLE213"), True,
        NUS_SERVICE_UUID, NUS_WRITE_UUID, NUS_NOTIFY_UUID,
    ),
    # ownbee/ninebot-ble uses the PC address on its tested F-series scooter.
    "ninebot_f": TransportProfile(
        "ninebot_f", ("BLE307",), True,
        NUS_SERVICE_UUID, NUS_WRITE_UUID, NUS_NOTIFY_UUID, DeviceId.PC,
    ),
}


def transport_for_family(family: str) -> TransportProfile | None:
    """Return a capability record; callers must check adapter_implemented."""
    return TRANSPORT_PROFILES.get(family)
