"""DTDL v3 model registry — loads JSON-LD model files from ontology/dtdl/
and exposes lookup + validation helpers.

For full DTDL semantic parsing (extends + components + inheritance) we'd
adopt the Microsoft `dtdl-parser` Python package once stable. For now this
registry is a thin loader that:
  • lists available models
  • validates basic JSON-LD shape (@context, @id, @type, contents)
  • provides per-model contents by category (Property / Telemetry / Command / Relationship / Component)

The Conjure IDL (ontology/conjure/princeps.yml) remains the API/code-contract
source of truth. DTDL adds the asset-twin semantics (telemetry as first-class,
command/relationship as first-class) on top.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("princeps.twin_ontology")

DTDL_DIR = Path(__file__).resolve().parent.parent / "ontology" / "dtdl"
DTDL_CONTEXT = "dtmi:dtdl:context;3"


@dataclass(frozen=True)
class TwinModel:
    dtmi: str
    display_name: str
    file_path: Path
    raw: dict

    @property
    def properties(self) -> list[dict]:
        return [c for c in self.raw.get("contents", []) if c.get("@type") == "Property"]

    @property
    def telemetry(self) -> list[dict]:
        return [c for c in self.raw.get("contents", []) if c.get("@type") == "Telemetry"]

    @property
    def commands(self) -> list[dict]:
        return [c for c in self.raw.get("contents", []) if c.get("@type") == "Command"]

    @property
    def relationships(self) -> list[dict]:
        return [c for c in self.raw.get("contents", []) if c.get("@type") == "Relationship"]

    @property
    def components(self) -> list[dict]:
        return [c for c in self.raw.get("contents", []) if c.get("@type") == "Component"]


_REGISTRY: dict[str, TwinModel] = {}


def _validate(raw: dict, file_path: Path) -> None:
    if raw.get("@context") != DTDL_CONTEXT:
        raise ValueError(f"{file_path}: missing or wrong @context (expected {DTDL_CONTEXT!r})")
    if raw.get("@type") != "Interface":
        raise ValueError(f"{file_path}: @type must be 'Interface'")
    dtmi = raw.get("@id")
    if not isinstance(dtmi, str) or not dtmi.startswith("dtmi:"):
        raise ValueError(f"{file_path}: missing/invalid @id")
    if not isinstance(raw.get("contents"), list):
        raise ValueError(f"{file_path}: 'contents' must be a list")


def load_all(force_reload: bool = False) -> dict[str, TwinModel]:
    if _REGISTRY and not force_reload:
        return _REGISTRY
    _REGISTRY.clear()
    if not DTDL_DIR.exists():
        log.warning("DTDL dir does not exist: %s", DTDL_DIR)
        return _REGISTRY
    for f in sorted(DTDL_DIR.glob("*.json")):
        try:
            raw = json.loads(f.read_text())
            _validate(raw, f)
            tm = TwinModel(
                dtmi=raw["@id"], display_name=raw.get("displayName", raw["@id"]),
                file_path=f, raw=raw,
            )
            _REGISTRY[tm.dtmi] = tm
            log.debug("loaded DTDL model: %s", tm.dtmi)
        except Exception as exc:
            log.error("failed to load DTDL model %s: %s", f, exc)
    return _REGISTRY


def get_model(dtmi: str) -> TwinModel:
    load_all()
    if dtmi not in _REGISTRY:
        raise KeyError(f"unknown DTDL model: {dtmi}")
    return _REGISTRY[dtmi]


def list_models() -> list[dict]:
    load_all()
    return [
        {
            "dtmi": m.dtmi,
            "display_name": m.display_name,
            "file": str(m.file_path.name),
            "n_properties": len(m.properties),
            "n_telemetry": len(m.telemetry),
            "n_relationships": len(m.relationships),
            "n_commands": len(m.commands),
        }
        for m in _REGISTRY.values()
    ]
