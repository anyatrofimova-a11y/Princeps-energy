"""Substation Tracker v1 — UK canonical Substation Tracker build.

Exposes one canonical 30-field schema (`SubstationProject`) and a set of
source-specific parsers (LTDS Excel, RIIO CV/BP, NESO NOA/CSNP), plus an
entity resolver that fuses duplicate records across sources and a pipeline
that writes the resolved rows into the shared `data_subscriptions` /
`data_subscription_rows` tables.

See `docs/audits/substation_tracker_feasibility_2026.md` (ship pending) for
the field-level coverage matrix, source availability notes, and refresh
cadence.

Public surface
--------------
    from utils.substation_tracker import (
        SubstationProject,
        parse_ltds_workbook,
        extract_from_riio_cv,
        ingest_noa,
        EntityResolver,
        run_pipeline,
    )
"""

from __future__ import annotations

from .schema import SubstationProject, ConstructionStatus, SourceType, StationType, UpgradeType
from .entity_resolver import EntityResolver, ResolvedMatch

# Parser/ingester imports are guarded — they pull in heavy deps (pdfplumber,
# camelot, openpyxl) so we keep them lazy for test/import speed.
try:
    from .ltds_excel_parser import parse_ltds_workbook, DNO_DISPATCHERS  # noqa: F401
except Exception:  # pragma: no cover - optional heavy dep
    parse_ltds_workbook = None  # type: ignore
    DNO_DISPATCHERS = {}  # type: ignore

try:
    from .riio_cv_extractor import extract_from_riio_cv  # noqa: F401
except Exception:  # pragma: no cover
    extract_from_riio_cv = None  # type: ignore

try:
    from .noa_ingester import ingest_noa  # noqa: F401
except Exception:  # pragma: no cover
    ingest_noa = None  # type: ignore

try:
    from .pipeline import run_pipeline  # noqa: F401
except Exception:  # pragma: no cover
    run_pipeline = None  # type: ignore


__all__ = [
    "SubstationProject",
    "ConstructionStatus",
    "SourceType",
    "StationType",
    "UpgradeType",
    "EntityResolver",
    "ResolvedMatch",
    "parse_ltds_workbook",
    "DNO_DISPATCHERS",
    "extract_from_riio_cv",
    "ingest_noa",
    "run_pipeline",
]
