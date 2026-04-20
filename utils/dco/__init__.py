"""
Princeps DCO (Development Consent Order) sub-package.

Each module builds ONE Reg 5 document skeleton per the Infrastructure
Planning (Applications: Prescribed Forms and Procedure) Regulations 2009
(SI 2009/2264, as amended). The orchestrator at ``utils/dco_pack.py``
assembles them into a single bound PDF.

Reg 5 document inventory (SI 2009/2264 reg 5(2)):
    (a) the application form                        -> application_form.py
    (b) a plan showing the location of the land,
        the limits of deviation, and the land to
        which the application relates (works + land plans, etc.)
                                                    -> land_plans.py + works_plans.py
    (c) a copy of the order the applicant is seeking
                                                    -> draft_order.py
    (d) an explanatory memorandum                   -> explanatory_memorandum.py
    (e) a statement of reasons                      -> statement_of_reasons.py
    (f) a funding statement                         -> funding_statement.py
    (g) an environmental statement (where EIA devt) -> environmental_statement_skeleton.py
    (h) a report summarising consultation (s.42 /
        s.47 / s.48)                                -> consultation_report.py
    (i) where CA powers sought, a book of reference -> book_of_reference.py
    (j) any other documents required by the relevant
        Act / Regulations (incl. statements of fact
        relating to use of land, s.59)              -> handled inline
"""

from __future__ import annotations

__all__ = [
    "application_form",
    "draft_order",
    "explanatory_memorandum",
    "statement_of_reasons",
    "consultation_report",
    "book_of_reference",
    "land_plans",
    "works_plans",
    "funding_statement",
    "environmental_statement_skeleton",
]
