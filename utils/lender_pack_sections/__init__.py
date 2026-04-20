"""
utils/lender_pack_sections — per-section builders for the lender pack.

Each section module exposes a single pure-function builder that takes the
assembled project context (from utils/lender_pack.py::_assemble_context)
and returns a dict the Jinja template can iterate over.

The sections mirror the COUNCIL-1 spec (paperwork_rewrite_spec.md §7 and
the follow-up rewrite brief): 15 sections, from the cover + reliance
addressee through to model audit trail and signature block.

Nothing here touches the network or the DB — all lookups happen in the
orchestrator in utils/lender_pack.py so these builders stay unit-testable
and deterministic.
"""
from __future__ import annotations

from .s01_cover import build_cover
from .s02_transaction import build_transaction_summary
from .s03_sources_uses import build_sources_uses
from .s04_base_case import build_base_case
from .s05_downside import build_downside_case
from .s06_breakeven import build_breakeven_case
from .s07_covenants import build_covenant_package
from .s08_mel import build_material_event_list
from .s09_tddr import build_tddr
from .s10_cp import build_cp_schedule
from .s11_cs import build_cs_schedule
from .s12_precedents import build_precedent_transactions
from .s13_security import build_security_structure
from .s14_model_audit import build_model_audit
from .s15_signature import build_signature_block

__all__ = [
    "build_cover",
    "build_transaction_summary",
    "build_sources_uses",
    "build_base_case",
    "build_downside_case",
    "build_breakeven_case",
    "build_covenant_package",
    "build_material_event_list",
    "build_tddr",
    "build_cp_schedule",
    "build_cs_schedule",
    "build_precedent_transactions",
    "build_security_structure",
    "build_model_audit",
    "build_signature_block",
]
