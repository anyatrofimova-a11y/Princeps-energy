"""License registry — single source of truth for every commercial vs non-commercial
artifact (model weights, datasets, libraries) Princeps depends on.

Inference paths must call ``assert_commercial_safe(artifact_id)`` before serving
output. The LicenseGuardMiddleware enforces the same invariant at the response
boundary as defense-in-depth.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

logger = logging.getLogger("princeps.license_guard")

LICENSES_YAML: Final = Path(__file__).parent / "licenses.yaml"


class LicenseBlockedError(Exception):
    """Raised when a commercial request path tries to use a non-commercial artifact."""

    def __init__(self, artifact_id: str, license_: str, source: str, alternative: str = ""):
        self.artifact_id = artifact_id
        self.license = license_
        self.source = source
        self.alternative = alternative
        msg = (
            f"Artifact '{artifact_id}' is licensed under {license_} (non-commercial). "
            f"Source: {source}."
        )
        if alternative:
            msg += f" Alternative: {alternative}"
        super().__init__(msg)


@dataclass(frozen=True, slots=True)
class ArtifactLicense:
    artifact_id: str
    license: str
    commercial_use: bool
    source: str
    notes: str = ""
    alternative: str = ""


@dataclass(frozen=True, slots=True)
class Policies:
    research_path_prefixes: tuple[str, ...]
    unknown_artifact_fails_closed: bool


_REGISTRY: dict[str, ArtifactLicense] = {}
_POLICIES: Policies | None = None


def _load() -> None:
    global _POLICIES
    if _REGISTRY and _POLICIES is not None:
        return
    with LICENSES_YAML.open() as f:
        data = yaml.safe_load(f)

    for aid, fields in (data.get("artifacts") or {}).items():
        if aid in _REGISTRY:
            continue
        _REGISTRY[aid] = ArtifactLicense(
            artifact_id=aid,
            license=fields["license"],
            commercial_use=bool(fields.get("commercial_use", False)),
            source=fields.get("source", ""),
            notes=fields.get("notes", "") or "",
            alternative=fields.get("alternative", "") or "",
        )

    pol = data.get("policies") or {}
    _POLICIES = Policies(
        research_path_prefixes=tuple(pol.get("research_path_prefixes") or ()),
        unknown_artifact_fails_closed=bool(pol.get("unknown_artifact_fails_closed", True)),
    )


def get_license(artifact_id: str) -> ArtifactLicense:
    _load()
    if artifact_id not in _REGISTRY:
        if _POLICIES and _POLICIES.unknown_artifact_fails_closed:
            raise KeyError(
                f"Unknown artifact: {artifact_id!r}. Register it in "
                f"app/license_guard/licenses.yaml before use."
            )
        logger.warning("license_guard: unknown artifact %s — failing open (dev mode).", artifact_id)
        return ArtifactLicense(
            artifact_id=artifact_id,
            license="UNKNOWN",
            commercial_use=False,
            source="",
        )
    return _REGISTRY[artifact_id]


def is_commercial_safe(artifact_id: str) -> bool:
    return get_license(artifact_id).commercial_use


def assert_commercial_safe(artifact_id: str) -> None:
    lic = get_license(artifact_id)
    if not lic.commercial_use:
        raise LicenseBlockedError(
            artifact_id=artifact_id,
            license_=lic.license,
            source=lic.source,
            alternative=lic.alternative,
        )


def list_artifacts() -> list[ArtifactLicense]:
    _load()
    return sorted(_REGISTRY.values(), key=lambda a: a.artifact_id)


def get_policies() -> Policies:
    _load()
    assert _POLICIES is not None
    return _POLICIES
