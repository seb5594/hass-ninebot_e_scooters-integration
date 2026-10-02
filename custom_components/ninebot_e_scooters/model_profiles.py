"""Compatibility imports; implementation lives in models.profiles."""

from .models.profiles import (
    AUTO_MODEL as AUTO_MODEL,
    BLE129 as BLE129,
    M365_PRO_CRYPTO as M365_PRO_CRYPTO,
    M365_LEGACY as M365_LEGACY,
    UNVERIFIED as UNVERIFIED,
    ModelProfile as ModelProfile,
    PROFILES as PROFILES,
    PROFILES_BY_NAME as PROFILES_BY_NAME,
    PROFILES_BY_PREFIX as PROFILES_BY_PREFIX,
    ModelIdentification as ModelIdentification,
    identify_model as identify_model,
    effective_profile as effective_profile,
    supports_write as supports_write,
)
