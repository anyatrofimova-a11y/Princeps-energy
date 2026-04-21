"""
utils.dno_engagement.dno_profiles — per-DNO overrides for the engagement pack.

Each DNO has its own voltage ladder, ECR adapter, G99 protection template,
LTDS citation and RIIO-ED period assumptions. v1 ships SSEN as the pilot
DNO (fully populated) with UKPN / NGED / SPEN / NPG / ENWL / NIE stubbed
to sensible defaults that degrade gracefully.

Entry point:
    from utils.dno_engagement.dno_profiles import get_profile
    profile = get_profile("SSEN")
"""

from __future__ import annotations

from .base import DnoProfile, DEFAULT_PROFILE
from .ssen import SSEN_PROFILE
from .ukpn import UKPN_PROFILE
from .nged import NGED_PROFILE
from .spen import SPEN_PROFILE
from .npg import NPG_PROFILE
from .enwl import ENWL_PROFILE
from .nie import NIE_PROFILE

_REGISTRY: dict[str, DnoProfile] = {
    "SSEN": SSEN_PROFILE,
    "UKPN": UKPN_PROFILE,
    "NGED": NGED_PROFILE,
    "SPEN": SPEN_PROFILE,
    "NPG":  NPG_PROFILE,
    "ENWL": ENWL_PROFILE,
    "NIE":  NIE_PROFILE,
}

# Alias table — maps historical codes to canonical keys.
_ALIASES = {
    "WPD":   "NGED",
    "SP":    "SPEN",
    "SSE":   "SSEN",
    "SEPD":  "SSEN",
    "SHEPD": "SSEN",
    "NEDL":  "NPG",
    "YEDL":  "NPG",
    "NWEST": "ENWL",
    "EPN":   "UKPN",
    "LPN":   "UKPN",
    "SPN":   "UKPN",
    "NIEN":  "NIE",
}


def get_profile(code: str | None) -> DnoProfile:
    """Return the DNO profile — falls back to DEFAULT_PROFILE if unknown."""
    if not code:
        return DEFAULT_PROFILE
    k = code.strip().upper()
    if k in _REGISTRY:
        return _REGISTRY[k]
    if k in _ALIASES:
        return _REGISTRY[_ALIASES[k]]
    return DEFAULT_PROFILE


__all__ = [
    "DnoProfile",
    "DEFAULT_PROFILE",
    "SSEN_PROFILE",
    "UKPN_PROFILE",
    "NGED_PROFILE",
    "SPEN_PROFILE",
    "NPG_PROFILE",
    "ENWL_PROFILE",
    "NIE_PROFILE",
    "get_profile",
]
