"""BLE transport capabilities separated from scooter identity and register writes.

An implemented adapter and a documented firmware are not hardware validation.
Xiaomi blocks and Ninebot word tables share only their UART and crypto envelope.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..protocols.gatt import NINEBOT_UART, NORDIC_UART, UartService
from ..protocols.ninebot.packet import DeviceId
from ..protocols.ninebot.registers import CLASSIC_REGISTERS, VCU_REGISTERS, RegisterMap
from .profiles import (
    BLE129,
    M365_LEGACY,
    M365_PRO_CRYPTO,
    NINEBOT_D,
    NINEBOT_E,
    NINEBOT_ES,
    NINEBOT_F,
    NINEBOT_MAX,
    NINEBOT_MAX_G2,
    NINEBOT_VCU,
    UNVERIFIED,
)


@dataclass(frozen=True, slots=True)
class TransportProfile:
    """Describe the GATT and authentication requirements for one family."""

    family: str
    documented_ble_versions: tuple[str, ...] = ()
    adapter_implemented: bool = False
    # The serial service the family is documented with. A session prefers it
    # and falls back to whichever known service the scooter really offers.
    uart: UartService | None = None
    host_id: DeviceId = DeviceId.PHONE
    # Bluetooth modules that may answer the 0x5B handshake, most likely first.
    handshake_boards: tuple[DeviceId, ...] = (DeviceId.DASHBOARD,)
    # Layout of the word registers; None for the Xiaomi block reads.
    registers: RegisterMap | None = None
    # The scooter keeps one session password. A host that knows it logs in
    # with 0x5D alone; sending 0x5C again would ask for the power button.
    resumes_with_password: bool = False


# A Ninebot name does not tell the two board numberings apart, so a session
# asks the documented Bluetooth module first and the other one after silence.
CLASSIC_HANDSHAKE = (DeviceId.DASHBOARD, DeviceId.VCU_BLUETOOTH)
VCU_HANDSHAKE = (DeviceId.VCU_BLUETOOTH, DeviceId.DASHBOARD)


def _implemented(
    family: str,
    *documented_ble_versions: str,
    uart: UartService = NORDIC_UART,
    host_id: DeviceId = DeviceId.PHONE,
) -> TransportProfile:
    """A Xiaomi family the integration can open a session with."""
    return TransportProfile(family, documented_ble_versions, True, uart, host_id)


def _ninebot(
    family: str,
    *documented_ble_versions: str,
    uart: UartService = NORDIC_UART,
    host_id: DeviceId = DeviceId.PHONE,
) -> TransportProfile:
    """A classic Ninebot family: ESC and BMS word registers, read-only."""
    return TransportProfile(family, documented_ble_versions, True, uart, host_id,
                            CLASSIC_HANDSHAKE, CLASSIC_REGISTERS)


# BLE versions are the ones ScooterHacking/NinebotCrypto lists per family. The
# vendor app also uses the chained crypto for the Max G2 and the D series,
# which have no public version list yet, so none is claimed here.
TRANSPORT_PROFILES: dict[str, TransportProfile] = {
    profile.family: profile for profile in (
        TransportProfile(UNVERIFIED),
        _implemented(BLE129, "BLE129"),
        # M365 Pro BLE110/122 uses the 5A A5 chained crypto handshake. The
        # original four-dot M365 uses unencrypted 55 AA over the same UART.
        _implemented(M365_PRO_CRYPTO, "BLE110", "BLE122"),
        _implemented(M365_LEGACY, "55 AA (four-dot display)"),
        _ninebot(NINEBOT_ES, "BLE109", "BLE110"),
        _ninebot(NINEBOT_MAX, "BLE110", "BLE113", "BLE114"),
        _ninebot(NINEBOT_E, "BLE209", "BLE213"),
        # ownbee/ninebot-ble uses the PC address on its tested F-series scooter.
        _ninebot(NINEBOT_F, "BLE307", host_id=DeviceId.PC),
        _ninebot(NINEBOT_MAX_G2, uart=NINEBOT_UART),
        _ninebot(NINEBOT_D, uart=NINEBOT_UART),
        # F3 and Max G3 offer both serial services and answer on the Nordic one.
        TransportProfile(NINEBOT_VCU, (), True, NORDIC_UART, DeviceId.PHONE,
                         VCU_HANDSHAKE, VCU_REGISTERS, resumes_with_password=True),
    )
}


def transport_for_family(family: str) -> TransportProfile | None:
    """Return a capability record; callers must check adapter_implemented."""
    return TRANSPORT_PROFILES.get(family)
