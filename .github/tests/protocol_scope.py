"""Populate isolated coordinator AST harnesses with their protocol imports.

Production code imports these names at module scope. Older tests compile a
single coordinator method without its surrounding imports; keep the harnesses
representative of the actual module after protocol constants are named.
"""

import importlib.util
from pathlib import Path
import sys


PACKET_MODULE_NAME = "isolated_ninebot_packet_test_scope"
if PACKET_MODULE_NAME not in sys.modules:
    packet_path = Path(__file__).resolve().parents[2] / "custom_components/ninebot_e_scooters/protocols/ninebot/packet.py"
    spec = importlib.util.spec_from_file_location(PACKET_MODULE_NAME, packet_path)
    packet = importlib.util.module_from_spec(spec)
    sys.modules[PACKET_MODULE_NAME] = packet
    spec.loader.exec_module(packet)
else:
    packet = sys.modules[PACKET_MODULE_NAME]


PROTOCOL_SYMBOLS = (
    "BLE129_APP_KEY_LENGTH",
    "BLE129_INIT_REPLY_LENGTH",
    "CMD_WRITE",
    "CMD_WRITE_NO_REPLY",
    "DeviceId",
    "ENCRYPTED_FRAME_OVERHEAD",
    "FrameOffset",
    "LegacyM365Reply",
    "PairingStatus",
    "RegisterReadSize",
    "Xiaomi1sBmsRegister",
    "Xiaomi1sDashboardRegister",
    "Xiaomi1sEscRegister",
    "Xiaomi1sFastTelemetry",
    "XIAOMI1S_BMS_REPLY_IDS",
    "XIAOMI1S_CONTROLLER_REPLY_IDS",
    "XIAOMI1S_KNOWN_LOCK_BYTES",
)


def add_protocol_symbols(namespace: dict, packet_module=packet) -> dict:
    """Provide the real packet module names to a standalone method harness."""
    for name in PROTOCOL_SYMBOLS:
        namespace.setdefault(name, getattr(packet_module, name))
    namespace.setdefault("NINEBOT_HEADER", packet_module.HEADER)
    return namespace
