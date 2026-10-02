"""Model identification and capability profiles, independent of BLE transport.

Adding a serial mapping identifies hardware only. Transport and write support
must be confirmed separately before they are enabled for a new family.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from ..protocols.research import inspect_ninebot_serial


AUTO_MODEL = "Automatisch"
BLE129 = "xiaomi_ble129"
M365_PRO_CRYPTO = "xiaomi_m365_pro_crypto"
M365_LEGACY = "xiaomi_m365_legacy"
UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """Describe identification, BLE transport and explicitly permitted writes."""

    name: str
    brand: str
    protocol: str
    serial_prefixes: tuple[str, ...] = ()
    writable_settings: frozenset[str] = frozenset()
    hardware_tested: bool = False


# These serial prefixes identify a marketed model, not its current region or
# actual firmware. Changing the serial in custom firmware can change the hint.
# Sources: https://wiki.scooterhacking.org/doku.php?id=mi365 and
# https://github.com/scooterhacking/NinebotCrypto (BLE129 support list).
# German 25700/25701 IDs: https://www.axdiaservice.com/produkt/scooter-datenbestaetigung-anfordern/
PROFILES: tuple[ModelProfile, ...] = (
    ModelProfile("Mi Electric Scooter 1S", "Xiaomi", BLE129, ("25699", "25700"),
                 frozenset({"work_mode", "kers_mode", "is_lock_on", "is_cruise_on", "is_tail_light_on"}), True),
    ModelProfile("Mi Electric Scooter Pro 2", "Xiaomi", BLE129, ("26354", "30371", "25701", "30372")),
    ModelProfile("Mi Electric Scooter Essential", "Xiaomi", BLE129, ("25702", "25600")),
    ModelProfile("Mi Electric Scooter Pro", "Xiaomi", M365_PRO_CRYPTO, ("18832", "21886")),
    ModelProfile("Mi Electric Scooter", "Xiaomi", M365_LEGACY,
                 ("13678", "13679", "16133", "21074", "16132", "21073", "16349", "16348")),
    ModelProfile("Mi Electric Scooter 3", "Xiaomi", UNVERIFIED, ("30807", "30806")),
    ModelProfile("Mi Electric Scooter 3 Lite", "Xiaomi", UNVERIFIED),
    ModelProfile("Mi Electric Scooter 4", "Xiaomi", UNVERIFIED, ("46442", "46443", "46441", "46440")),
    ModelProfile("Mi Electric Scooter 4 Pro", "Xiaomi", UNVERIFIED,
                 ("35802", "38191", "35803", "35804", "35806", "41839")),
    ModelProfile("Mi Electric Scooter 4 Lite", "Xiaomi", UNVERIFIED,
                 ("46416", "46419", "46415", "46418", "46417")),
    ModelProfile("Mi Electric Scooter 4 Ultra", "Xiaomi", UNVERIFIED, ("40595", "37829", "40594")),
    ModelProfile("Mi Electric Scooter 4 Go", "Xiaomi", UNVERIFIED, ("45482", "45480", "45481")),
    # Model records for future adapters; discovery and controls remain off.
    ModelProfile("Ninebot ES", "Segway-Ninebot", "ninebot_es"),
    ModelProfile("Ninebot Max", "Segway-Ninebot", "ninebot_max"),
    ModelProfile("Ninebot E series", "Segway-Ninebot", "ninebot_e"),
    ModelProfile("Ninebot F series", "Segway-Ninebot", "ninebot_f"),
    *(ModelProfile(f"Ninebot {model}", "Segway-Ninebot", "ninebot_es")
      for model in ("ES1", "ES2", "ES3", "ES4")),
    *(ModelProfile(f"Ninebot {model}", "Segway-Ninebot", "ninebot_max")
      for model in ("G30", "G30P", "G30D", "G30E", "G30LP", "G30LE", "G30LD")),
    *(ModelProfile(f"Ninebot {model}", "Segway-Ninebot", "ninebot_e")
      for model in ("E22", "E25", "E45")),
    *(ModelProfile(f"Ninebot {model}", "Segway-Ninebot", "ninebot_f")
      for model in ("F20", "F25", "F30", "F40")),
)

PROFILES_BY_NAME = {profile.name: profile for profile in PROFILES}
PROFILES_BY_PREFIX = {
    prefix: profile for profile in PROFILES for prefix in profile.serial_prefixes
}


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
    ninebot = inspect_ninebot_serial(serial)
    if ninebot is not None:
        # Serial variants refine the display; family profiles retain the same adapter.
        concrete = f"Ninebot {ninebot.model_hint}" if ninebot.model_hint else None
        model = concrete if concrete in PROFILES_BY_NAME else ninebot.family
        return ModelIdentification(model, "Segway-Ninebot", "ninebot_serial", ninebot.series)
    match = re.fullmatch(r"([0-9]{5})/[0-9]{8}", serial or "")
    if match:
        prefix = match.group(1)
        profile = PROFILES_BY_PREFIX.get(prefix)
        if profile is not None:
            return ModelIdentification(profile.name, profile.brand, "serial_prefix", prefix)
        return ModelIdentification(
            None, "Xiaomi" if (advertised_name or "").casefold().startswith("miscooter") else None,
            "unknown_serial_prefix", prefix,
        )
    if (advertised_name or "").casefold().startswith("miscooter"):
        return ModelIdentification(None, "Xiaomi", "advertisement_name")
    if (advertised_name or "").casefold().startswith(("ninebot", "nbscooter", "segway")):
        return ModelIdentification(None, "Segway-Ninebot", "advertisement_name")
    return ModelIdentification(None, None, "unknown")


def effective_profile(configured_model: str, identification: ModelIdentification) -> ModelProfile | None:
    """Resolve explicit choice or a confidently identified automatic model."""
    chosen = identification.model if configured_model == AUTO_MODEL else configured_model
    return PROFILES_BY_NAME.get(chosen) if chosen else None


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
