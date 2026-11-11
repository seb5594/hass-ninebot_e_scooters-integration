"""Model hints from the 14-character serial of Segway-Ninebot scooters.

Example: N4GEC2110C1234 is product N4G, variant E, factory line C, built in
week 10 of 2021, revision C, unit 1234. The first three characters name the
product, the fourth the variant sold in one region. Custom firmware can
rewrite the serial, so a hint identifies the scooter but proves nothing.

Variant letters were checked on 2026-11-11 against
  https://wiki.scooterhacking.org/doku.php?id=nbeseries  (E22/E25/E45)
  https://wiki.scooterhacking.org/doku.php?id=nbmax      (Max G30)
  https://wiki.scooterhacking.org/doku.php?id=nbfseries  (F series)
  https://joeybabcock.me/wiki/Ninebot_ESX_Change_Serial/Region  (ES1-ES4)
  https://joeybabcock.me/wiki/Ninebot_Max_G2_D           (Max G2, G2E, G2D)
Letters that a source lists twice or with a question mark are left out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

FAMILY_ES = "Ninebot ES"
FAMILY_E = "Ninebot E series"
FAMILY_MAX = "Ninebot Max"
FAMILY_F = "Ninebot F series"
FAMILY_MAX_G2 = "Ninebot Max G2"


def _variants(family: str, models_by_letter: dict[str, str]) -> dict[str, tuple[str, str]]:
    """Attach the family to every variant letter of one model line."""
    return {letter: (family, model) for letter, model in models_by_letter.items()}


# Product identifier -> variant letter -> (family, marketed model).
SERIAL_VARIANTS: dict[str, dict[str, tuple[str, str]]] = {
    # The ES and the later E series share N2G; only the variant tells them apart.
    "N2G": {
        **_variants(FAMILY_ES, {
            "E": "ES1", "F": "ES1",
            "K": "ES2", "N": "ES2", "T": "ES2", "W": "ES2", "U": "ES2L",
            "C": "ES3",
            "A": "ES4", "H": "ES4", "J": "ES4", "P": "ES4", "S": "ES4",
        }),
        **_variants(FAMILY_E, {
            "D": "E22", "G": "E22E", "I": "E22D",
            "V": "E25", "Y": "E25D", "X": "E25E", "Z": "E25A",
            "Q": "E45", "R": "E45D", "O": "E45E", "M": "E45E",
        }),
    },
    "N4G": _variants(FAMILY_MAX, {
        "S": "G30P", "C": "G30", "E": "G30D", "P": "G30E", "T": "G30M",
        "N": "G30LP", "A": "G30LE", "O": "G30LE", "M": "G30LD",
    }),
    "N5G": _variants(FAMILY_F, {
        "A": "F20", "B": "F20D", "O": "F20A", "N": "F25",
        "C": "F30", "D": "F30D", "Q": "F30E",
        "E": "F40", "V": "F40", "F": "F40E", "G": "F40D", "R": "F40A",
        "H": "F60", "M": "F60A",
    }),
    # Y and T are sold as both G2E and G2D, so they name the family only.
    "01G": _variants(FAMILY_MAX_G2, {"X": "Max G2", "U": "Max G2", "Z": "Max G2D"}),
}

# Product identifiers a single family owns. An unlisted variant letter still
# names that family; N2G is missing on purpose.
FAMILY_BY_PRODUCT: dict[str, str] = {
    "N4G": FAMILY_MAX,
    "N5G": FAMILY_F,
    "01G": FAMILY_MAX_G2,
}

NINEBOT_SERIAL = re.compile(r"[A-Z0-9]{5}[0-9]{4}[A-Z0-9][0-9]{4}")


@dataclass(frozen=True, slots=True)
class NinebotSerialHint:
    """What a complete serial says about the scooter it was read from."""

    series: str
    family: str
    variant: str
    model_hint: str | None
    production_year: int
    production_week: int
    revision: str


def inspect_ninebot_serial(serial: str | bytes | None) -> NinebotSerialHint | None:
    """Return a hint for a well-formed serial of a known product, else None."""
    if isinstance(serial, bytes):
        try:
            serial = serial.rstrip(b"\x00").decode("ascii")
        except UnicodeDecodeError:
            return None
    if not isinstance(serial, str) or not NINEBOT_SERIAL.fullmatch(serial):
        return None
    product, variant = serial[:3], serial[3]
    variants = SERIAL_VARIANTS.get(product)
    if variants is None:
        return None
    family, model = variants.get(variant, (FAMILY_BY_PRODUCT.get(product), None))
    if family is None:
        return None
    year, week = 2000 + int(serial[5:7]), int(serial[7:9])
    try:
        date.fromisocalendar(year, week, 1)
    except ValueError:
        return None
    return NinebotSerialHint(product, family, variant, model, year, week, serial[9])
