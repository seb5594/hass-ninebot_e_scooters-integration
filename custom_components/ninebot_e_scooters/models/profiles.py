"""Model identification and capability profiles, independent of BLE transport.

Adding a serial mapping identifies hardware only. Transport and write support
must be confirmed separately before they are enabled for a new family.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from ..protocols.ninebot.packet import DeviceId
from .serials import NINEBOT_SERIAL, inspect_ninebot_serial


AUTO_MODEL = "Automatisch"
BLE129 = "xiaomi_ble129"
M365_PRO_CRYPTO = "xiaomi_m365_pro_crypto"
M365_LEGACY = "xiaomi_m365_legacy"
UNVERIFIED = "unverified"

NINEBOT_ES = "ninebot_es"
NINEBOT_MAX = "ninebot_max"
NINEBOT_E = "ninebot_e"
NINEBOT_F = "ninebot_f"
NINEBOT_MAX_G2 = "ninebot_max_g2"
NINEBOT_D = "ninebot_d"
# F3 and Max G3: a vehicle control unit replaces the ESC as the board to ask.
NINEBOT_VCU = "ninebot_vcu"

# Families polled through the read-only Ninebot word registers.
NINEBOT_WORD_REGISTER_PROTOCOLS = frozenset({
    NINEBOT_ES, NINEBOT_MAX, NINEBOT_E, NINEBOT_F,
    NINEBOT_MAX_G2, NINEBOT_D, NINEBOT_VCU,
})

XIAOMI = "Xiaomi"
SEGWAY_NINEBOT = "Segway-Ninebot"

# Shown when the scooter is known by its board numbering alone.
VCU_GENERATION = "Ninebot F3 / Max G3"
GENERATION_EVIDENCE = "handshake_board"

# Settings the reference scooter accepts and confirms by a readback.
XIAOMI_1S_WRITABLE_SETTINGS = frozenset({
    "work_mode", "kers_mode", "is_lock_on", "is_cruise_on", "is_tail_light_on",
})


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """Describe identification, BLE transport and explicitly permitted writes."""

    name: str
    brand: str
    protocol: str
    serial_prefixes: tuple[str, ...] = ()
    writable_settings: frozenset[str] = frozenset()
    hardware_tested: bool = False
    # Regional editions are recognized by their serial but not offered in the
    # setup form, where the model line they belong to is enough.
    selectable: bool = True


def _ninebot_models(protocol: str, models: str, regional: str = "") -> tuple[ModelProfile, ...]:
    """Read-only profiles for one Ninebot model line, named like their serial hint."""
    return (
        *(ModelProfile(f"Ninebot {model}", SEGWAY_NINEBOT, protocol) for model in models.split()),
        *(ModelProfile(f"Ninebot {model}", SEGWAY_NINEBOT, protocol, selectable=False)
          for model in regional.split()),
    )


def _ninebot_named(protocol: str, *names: str) -> tuple[ModelProfile, ...]:
    """Read-only profiles whose marketed name contains a space."""
    return tuple(ModelProfile(f"Ninebot {name}", SEGWAY_NINEBOT, protocol) for name in names)


# These serial prefixes identify a marketed model, not its current region or
# actual firmware. Changing the serial in custom firmware can change the hint.
# Sources: https://wiki.scooterhacking.org/doku.php?id=mi365 and
# https://github.com/scooterhacking/NinebotCrypto (BLE129 support list).
# German 25700/25701 IDs: https://www.axdiaservice.com/produkt/scooter-datenbestaetigung-anfordern/
PROFILES: tuple[ModelProfile, ...] = (
    ModelProfile("Mi Electric Scooter 1S", XIAOMI, BLE129, ("25699", "25700"),
                 XIAOMI_1S_WRITABLE_SETTINGS, True),
    ModelProfile("Mi Electric Scooter Pro 2", XIAOMI, BLE129, ("26354", "30371", "25701", "30372")),
    ModelProfile("Mi Electric Scooter Essential", XIAOMI, BLE129, ("25702", "25600")),
    ModelProfile("Mi Electric Scooter Pro", XIAOMI, M365_PRO_CRYPTO, ("18832", "21886")),
    ModelProfile("Mi Electric Scooter", XIAOMI, M365_LEGACY,
                 ("13678", "13679", "16133", "21074", "16132", "21073", "16349", "16348")),
    ModelProfile("Mi Electric Scooter 3", XIAOMI, UNVERIFIED, ("30807", "30806")),
    ModelProfile("Mi Electric Scooter 3 Lite", XIAOMI, UNVERIFIED),
    ModelProfile("Mi Electric Scooter 4", XIAOMI, UNVERIFIED, ("46442", "46443", "46441", "46440")),
    ModelProfile("Mi Electric Scooter 4 Pro", XIAOMI, UNVERIFIED,
                 ("35802", "38191", "35803", "35804", "35806", "41839")),
    ModelProfile("Mi Electric Scooter 4 Lite", XIAOMI, UNVERIFIED,
                 ("46416", "46419", "46415", "46418", "46417")),
    ModelProfile("Mi Electric Scooter 4 Ultra", XIAOMI, UNVERIFIED, ("40595", "37829", "40594")),
    ModelProfile("Mi Electric Scooter 4 Go", XIAOMI, UNVERIFIED, ("45482", "45480", "45481")),
    # Family entries for scooters whose exact model the owner does not know.
    ModelProfile("Ninebot ES", SEGWAY_NINEBOT, NINEBOT_ES),
    ModelProfile("Ninebot Max", SEGWAY_NINEBOT, NINEBOT_MAX),
    ModelProfile("Ninebot E series", SEGWAY_NINEBOT, NINEBOT_E),
    ModelProfile("Ninebot F series", SEGWAY_NINEBOT, NINEBOT_F),
    ModelProfile(VCU_GENERATION, SEGWAY_NINEBOT, NINEBOT_VCU),
    *_ninebot_models(NINEBOT_ES, "ES1 ES2 ES3 ES4", regional="ES2L"),
    *_ninebot_models(NINEBOT_MAX, "G30 G30P G30D G30E G30LP G30LE G30LD", regional="G30M"),
    *_ninebot_models(NINEBOT_E, "E22 E25 E45", regional="E22D E22E E25A E25D E25E E45D E45E"),
    *_ninebot_models(NINEBOT_F, "F20 F25 F30 F40 F65",
                     regional="F20A F20D F30D F30E F40A F40D F40E F60 F60A"),
    # The generation after the ones above. The vendor app drives it with the
    # same chained crypto; nobody has reported a result with this integration.
    *_ninebot_named(NINEBOT_MAX_G2, "Max G2", "Max G2E", "Max G2D"),
    *_ninebot_named(NINEBOT_D, "D18", "D28", "D38"),
    # The E2 Pro completed the chained-crypto handshake on the dashboard board
    # (issue #18), so it is read like the E series. Its registers are not
    # confirmed yet. Unlike the E2 Pro, the vendor device table lists these
    # without the chained crypto (see protocols/research.py): named only.
    *_ninebot_named(NINEBOT_E, "E2 Pro"),
    *_ninebot_named(UNVERIFIED, "F2", "F2 Plus", "F2 Pro", "E2", "E2 Plus"),
    # Other projects read an F3, an F3 Pro and a Max G3 this way (see
    # docs/PROTOCOL_SOURCES.md); this integration has no report of its own yet.
    *_ninebot_named(NINEBOT_VCU, "F3", "F3 Pro", "Max G3"),
)

PROFILES_BY_NAME = {profile.name: profile for profile in PROFILES}
# Offered in the setup form. A model name labels a protocol profile; it is not
# proof of support for every dashboard firmware or every writable setting.
CONFIGURABLE_MODELS = (AUTO_MODEL,) + tuple(
    profile.name for profile in PROFILES
    if profile.protocol != UNVERIFIED and profile.selectable
)
PROFILES_BY_PREFIX = {
    prefix: profile for profile in PROFILES for prefix in profile.serial_prefixes
}

XIAOMI_SERIAL = re.compile(r"([0-9]{5})/[0-9]{8}")
XIAOMI_NAME_PREFIX = "miscooter"
NINEBOT_NAME_PREFIXES = ("ninebot", "nbscooter", "segway")


@dataclass(frozen=True, slots=True)
class ModelIdentification:
    """Represent evidence without mistaking a shared BLE version for a model."""

    model: str | None
    brand: str | None
    evidence: str
    serial_prefix: str | None = None


def identify_model(serial: str | bytes | None, advertised_name: str | None = None) -> ModelIdentification:
    """Identify only complete, known scooter serials; names reveal at most a brand."""
    if isinstance(serial, bytes):
        serial = serial.rstrip(b"\x00").decode("ascii", errors="replace")
    name = (advertised_name or "").casefold()
    # Newer Ninebot generations advertise their serial as Bluetooth name.
    ninebot = inspect_ninebot_serial(serial) or inspect_ninebot_serial(advertised_name)
    if ninebot is not None:
        # Serial variants refine the display; family profiles retain the same adapter.
        concrete = f"Ninebot {ninebot.model_hint}" if ninebot.model_hint else None
        model = concrete if concrete in PROFILES_BY_NAME else ninebot.family
        return ModelIdentification(model, SEGWAY_NINEBOT, "ninebot_serial", ninebot.series)
    match = XIAOMI_SERIAL.fullmatch(serial or "")
    if match:
        prefix = match.group(1)
        profile = PROFILES_BY_PREFIX.get(prefix)
        if profile is not None:
            return ModelIdentification(profile.name, profile.brand, "serial_prefix", prefix)
        return ModelIdentification(
            None, XIAOMI if name.startswith(XIAOMI_NAME_PREFIX) else None,
            "unknown_serial_prefix", prefix,
        )
    if name.startswith(XIAOMI_NAME_PREFIX):
        return ModelIdentification(None, XIAOMI, "advertisement_name")
    if name.startswith(NINEBOT_NAME_PREFIXES) or NINEBOT_SERIAL.fullmatch(advertised_name or ""):
        return ModelIdentification(None, SEGWAY_NINEBOT, "advertisement_name")
    return ModelIdentification(None, None, "unknown")


def identify_generation(answering_board: int) -> ModelIdentification | None:
    """Name the generation whose Bluetooth module answered the handshake.

    Only the VCU generation is told apart this way: the dashboard address is
    shared by every Xiaomi and every classic Ninebot.
    """
    if answering_board != DeviceId.VCU_BLUETOOTH:
        return None
    return ModelIdentification(VCU_GENERATION, SEGWAY_NINEBOT, GENERATION_EVIDENCE)


def uses_ninebot_word_registers(profile: ModelProfile | None) -> bool:
    """Whether a profile is polled through the Ninebot word registers."""
    return profile is not None and profile.protocol in NINEBOT_WORD_REGISTER_PROTOCOLS


def effective_profile(configured_model: str, identification: ModelIdentification) -> ModelProfile | None:
    """Resolve explicit choice or a confidently identified automatic model."""
    chosen = identification.model if configured_model == AUTO_MODEL else configured_model
    profile = PROFILES_BY_NAME.get(chosen) if chosen else None
    if identification.evidence != GENERATION_EVIDENCE:
        return profile
    # The scooter itself showed which generation it is. The registers of
    # another Ninebot family, picked by name, would stay unanswered.
    proven = PROFILES_BY_NAME[identification.model]
    contradicted = uses_ninebot_word_registers(profile) and profile.protocol != proven.protocol
    return proven if contradicted else profile


def supports_write(configured_model: str, identification: ModelIdentification, field: str) -> bool:
    """Allow only known writes, and block a positively identified model mismatch."""
    profile = effective_profile(configured_model, identification)
    return bool(
        profile is not None
        and profile.protocol == BLE129
        and field in profile.writable_settings
        and (identification.brand is None or identification.brand == profile.brand)
        and (identification.model is None or identification.model == profile.name)
    )
