"""Compatibility imports; implementation lives in protocols.research."""

from .protocols.research import (
    ProtocolCandidate as ProtocolCandidate,
    PROTOCOL_CANDIDATES as PROTOCOL_CANDIDATES,
    NINEBOT_SERIAL_HINTS as NINEBOT_SERIAL_HINTS,
    NinebotSerialHint as NinebotSerialHint,
    inspect_ninebot_serial as inspect_ninebot_serial,
    RegisterCandidate as RegisterCandidate,
    NINEBOT_READ_CANDIDATES as NINEBOT_READ_CANDIDATES,
)
