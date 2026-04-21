"""Lender Technical Due Diligence (TDD) helpers.

Modules in this package close the three biggest Princeps-vs-lender-TDD gaps
identified by RESEARCH-3 (see ``docs/competitive/tdd_standard_2026.md``):

  1. :mod:`utils.tdd.warranty` — warranty matrix, parent-company-guarantee
     (PCG) register, O&M / LTSA contract review checklist.
  2. :mod:`utils.tdd.insurance_sign_off` — construction-all-risks / delay
     start-up / operational / liability / cyber insurance adequacy,
     chartered-engineer sign-off block and reliance / addressee package.
  3. :mod:`utils.tdd.bess_commercial` — BESS augmentation plan, year-on-year
     capacity-retention curve, UL 9540A conformance audit and PAS
     63100:2024 cross-walk.  Complements :mod:`utils.bess_thermal` (which is
     thermodynamic only).

Everything is analytic / table-driven; no external solvers, no network
calls, deterministic outputs suitable for lender reliance once a chartered
engineer signs the final report.
"""

from utils.tdd.warranty import (  # noqa: F401
    WarrantyMatrix,
    WarrantyLine,
    PCGRegister,
    OMContractReview,
    build_warranty_matrix,
    manufacturer_pcg_lookup,
    om_contract_checklist,
)

from utils.tdd.insurance_sign_off import (  # noqa: F401
    InsuranceProgramme,
    CoverLine,
    CEngSignOffBlock,
    ReliancePackage,
    Addressee,
    build_insurance_programme,
    default_ceng_sign_off,
    default_reliance_package,
)

from utils.tdd.bess_commercial import (  # noqa: F401
    AugmentationPlan,
    AugmentationEvent,
    CapacityRetentionPoint,
    UL9540AAudit,
    UL9540AFinding,
    PAS63100CrossWalk,
    PAS63100Mapping,
    build_augmentation_plan,
    run_ul_9540a_audit,
    build_pas_63100_crosswalk,
)

__all__ = [
    "WarrantyMatrix", "WarrantyLine", "PCGRegister", "OMContractReview",
    "build_warranty_matrix", "manufacturer_pcg_lookup", "om_contract_checklist",
    "InsuranceProgramme", "CoverLine", "CEngSignOffBlock", "ReliancePackage",
    "Addressee",
    "build_insurance_programme", "default_ceng_sign_off",
    "default_reliance_package",
    "AugmentationPlan", "AugmentationEvent", "CapacityRetentionPoint",
    "UL9540AAudit", "UL9540AFinding", "PAS63100CrossWalk", "PAS63100Mapping",
    "build_augmentation_plan", "run_ul_9540a_audit", "build_pas_63100_crosswalk",
]
