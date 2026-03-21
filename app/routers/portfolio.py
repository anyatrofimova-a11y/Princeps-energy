"""Portfolio optimisation router — multi-site portfolio construction & analysis."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from utils.portfolio_optimiser import (
    optimise_portfolio,
    diversification_analysis,
    sensitivity_analysis,
    compare_portfolios,
    auto_generate_portfolio,
)

router = APIRouter(tags=["portfolio"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class SiteInput(BaseModel):
    lat: float
    lon: float
    capacity_mw: float
    technology: str = "solar"
    capex_gbp: float
    estimated_irr: float = 8.0
    risk_score: float = 50.0
    revenue_type: str = "merchant"
    name: str | None = None


class Constraints(BaseModel):
    max_single_site_pct: float = 30.0
    min_sites: int = 3
    technology_diversification: bool = True
    max_technology_pct: float = 70.0


class OptimiseRequest(BaseModel):
    budget_gbp: float
    sites: list[SiteInput]
    constraints: Constraints | None = None


class DiversificationRequest(BaseModel):
    sites: list[SiteInput]


class SensitivityRequest(BaseModel):
    portfolio: dict
    variables: list[str] | None = None
    n_montecarlo: int = 2000


class CompareRequest(BaseModel):
    portfolios: list[dict]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/api/portfolio/optimise")
async def api_portfolio_optimise(body: OptimiseRequest):
    """Select the optimal combination of sites within a GBP budget."""
    sites = [s.model_dump() for s in body.sites]
    constraints = body.constraints.model_dump() if body.constraints else None
    return optimise_portfolio(body.budget_gbp, sites, constraints)


@router.post("/api/portfolio/diversification")
async def api_portfolio_diversification(body: DiversificationRequest):
    """Analyse geographic, technology and revenue diversification."""
    sites = [s.model_dump() for s in body.sites]
    return diversification_analysis(sites)


@router.post("/api/portfolio/sensitivity")
async def api_portfolio_sensitivity(body: SensitivityRequest):
    """Tornado chart + Monte Carlo sensitivity analysis."""
    return sensitivity_analysis(
        body.portfolio,
        body.variables,
        body.n_montecarlo,
    )


@router.post("/api/portfolio/compare")
async def api_portfolio_compare(body: CompareRequest):
    """Compare 2-4 portfolio configurations side-by-side."""
    return compare_portfolios(body.portfolios)


@router.get("/api/portfolio/auto")
async def api_portfolio_auto(
    request: Request,
    budget_gbp: float = Query(..., description="Total budget in GBP"),
    target_irr: float = Query(8.0, description="Target portfolio IRR (%)"),
    region: str | None = Query(None, description="Filter by UK region"),
    technologies: str | None = Query(None, description="Comma-separated tech filter (solar,wind,bess)"),
):
    """Auto-generate an optimised portfolio from the projects pipeline."""
    pool = request.app.state.pool
    tech_list = [t.strip() for t in technologies.split(",")] if technologies else None
    return await auto_generate_portfolio(
        budget_gbp=budget_gbp,
        target_irr=target_irr,
        region=region,
        technologies=tech_list,
        pool=pool,
    )
