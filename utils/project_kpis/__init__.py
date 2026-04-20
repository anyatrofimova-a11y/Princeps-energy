"""Project KPI computation package.

Exposes `compute_kpis(project_id) -> ProjectKpis` which fans out across the
agent-verdict, grid, planning, finance and calendar surfaces to build the
five headline numbers shown in the project detail strip.
"""

from .compute_kpis import ProjectKpis, compute_kpis, invalidate_cache

__all__ = ["ProjectKpis", "compute_kpis", "invalidate_cache"]
