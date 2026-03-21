"""Land registry router — property boundaries, ALC, listings, price paid, and planning density."""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, Query

from app.deps import get_pool

router = APIRouter(tags=["land"])


@router.get("/api/land/parcels")
async def land_parcels(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
    min_area_ha: float = Query(0.5),
):
    """HM Land Registry INSPIRE polygons as GeoJSON for map overlay."""
    from utils.land_registry import get_land_parcels
    return await get_land_parcels((west, south, east, north), min_area_ha=min_area_ha)


@router.get("/api/land/alc")
async def land_alc(lat: float = Query(...), lon: float = Query(...)):
    """Agricultural Land Classification grade at a point."""
    from utils.land_registry import get_agricultural_land_class
    return await get_agricultural_land_class(lat, lon)


@router.get("/api/land/listings")
async def land_listings(
    lat: float = Query(...), lon: float = Query(...),
    radius_km: float = Query(10), land_type: str = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Land listings from REPD stalled projects + portal search links."""
    from utils.land_registry import search_commercial_listings
    return await search_commercial_listings(lat, lon, radius_km=radius_km, land_type=land_type, pool=pool)


@router.get("/api/land/price-paid")
async def price_paid(postcode: str = Query(..., description="UK postcode e.g. SW1A 1AA")):
    """HMLR Price Paid data for a postcode area."""
    from utils.land_registry import get_price_paid
    return await get_price_paid(postcode)


@router.get("/api/land/planning-density")
async def planning_density(
    lat: float = Query(...), lon: float = Query(...),
    radius_km: float = Query(10),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Planning application density around a point — REPD projects by status/technology."""
    from utils.planning_density import get_planning_density
    return await get_planning_density(pool, lat, lon, radius_km=radius_km)


# ---------------------------------------------------------------------------
# ML-Enhanced Land Classification
# ---------------------------------------------------------------------------

@router.get("/api/land/alc-real")
async def land_alc_real(
    lat: float = Query(..., description="Latitude (WGS84)"),
    lon: float = Query(..., description="Longitude (WGS84)"),
    radius_m: float = Query(500, description="Search radius in metres"),
):
    """Real Agricultural Land Classification from Natural England ArcGIS API.
    Returns actual ALC grade (not latitude-band approximation), BMV status,
    development suitability score, and all grades found within radius."""
    from utils.land_classification_ml import query_natural_england_alc
    return await query_natural_england_alc(lat, lon, radius_m)


@router.get("/api/land/alc-adjusted")
async def land_alc_adjusted(
    lat: float = Query(...),
    lon: float = Query(...),
    slope_mean_deg: float = Query(3, description="Mean slope in degrees"),
    slope_p90_deg: float = Query(6, description="P90 slope in degrees"),
):
    """ALC grade adjusted for terrain slope.
    MAFF guidelines: slopes >7° limit agricultural capability.
    Returns slope-adjusted grade and development implications."""
    from utils.land_classification_ml import query_natural_england_alc, adjust_alc_for_slope
    alc = await query_natural_england_alc(lat, lon)
    return adjust_alc_for_slope(alc, slope_mean_deg, slope_p90_deg)


from pydantic import BaseModel


class CropClassifyRequest(BaseModel):
    monthly_ndvi: list[float]


@router.post("/api/land/crop-classify")
async def crop_classify(req: CropClassifyRequest):
    """Classify crop type from 12-month NDVI profile using UK phenological matching.
    Distinguishes: winter wheat, spring barley, oilseed rape, permanent pasture,
    sugar beet, maize. Returns confidence, typical ALC grade, growth period."""
    from utils.land_classification_ml import classify_crop_from_ndvi_profile
    if len(req.monthly_ndvi) < 12:
        from fastapi import HTTPException
        raise HTTPException(400, "Need 12 monthly NDVI values (Jan-Dec)")
    return classify_crop_from_ndvi_profile(req.monthly_ndvi)


class LandSuitabilityRequest(BaseModel):
    alc_score: float = 50
    slope_mean_deg: float = 3
    slope_p90_deg: float = 6
    elevation_m: float = 80
    south_facing_pct: float = 50
    developable_pct: float = 65
    built_pct: float = 10
    trees_pct: float = 12
    water_pct: float = 2
    ndvi_mean: float = 0.5
    ndvi_amplitude: float = 0.3
    flood_zone: int = 1
    grid_distance_km: float = 5
    grid_headroom_mw: float = 10
    sssi_proximity_km: float = 5
    aonb_inside: int = 0
    green_belt: int = 0
    ghi_kwh_m2: float = 1000


@router.post("/api/land/ml-suitability")
async def land_ml_suitability(req: LandSuitabilityRequest):
    """ML land suitability prediction (0-100) using XGBoost with 18 features.
    Combines ALC grade, terrain, land use, constraints, grid access, solar resource.
    Returns score, verdict (SUITABLE/MARGINAL/UNSUITABLE), constraints, SHAP factors."""
    from utils.land_classification_ml import predict_land_suitability
    return predict_land_suitability(req.model_dump())


@router.get("/api/land/comprehensive")
async def land_comprehensive(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    """Run full ML land classification pipeline:
    1. Query real ALC from Natural England
    2. Adjust for slope from GeeFlow terrain
    3. ML suitability prediction with SHAP
    4. Constraint overlay
    Returns comprehensive land assessment with overall verdict and score."""
    from utils.land_classification_ml import comprehensive_land_assessment
    return await comprehensive_land_assessment(lat, lon)


# ---------------------------------------------------------------------------
# Companies House — identify landowner companies near sites
# ---------------------------------------------------------------------------

@router.get("/api/land/companies")
async def nearby_companies(
    lat: float = Query(..., description="Latitude (WGS84)"),
    lon: float = Query(..., description="Longitude (WGS84)"),
    radius_km: float = Query(5, description="Search radius in km"),
):
    """Search Companies House for land/property/agriculture/energy companies
    near a location. Requires COMPANIES_HOUSE_API_KEY env var (free to register).
    Returns companies filtered by relevant SIC codes with relevance scoring."""
    from utils.companies_house import search_landowner_companies
    return await search_landowner_companies(lat, lon, radius_km=radius_km)


@router.get("/api/land/company/{company_number}")
async def company_detail(company_number: str):
    """Get full Companies House company details including officers and filing history."""
    from utils.companies_house import get_company_detail
    return await get_company_detail(company_number)


# ---------------------------------------------------------------------------
# PINS / NSIP — Nationally Significant Infrastructure Projects
# ---------------------------------------------------------------------------

@router.get("/api/planning/nsip")
async def nsip_projects(
    technology: str = Query(None, description="Filter by technology (solar, wind, nuclear, etc.)"),
    status: str = Query(None, description="Filter by stage (pre-application, examination, decision, etc.)"),
):
    """Fetch NSIP projects from the Planning Inspectorate register.
    These are large energy projects (>50MW solar, >100MW wind, nuclear, data centres)
    that use the DCO process. Returns project list with capacity, status, location."""
    from utils.pins_nsip import fetch_nsip_projects
    return await fetch_nsip_projects(technology=technology, status=status)


@router.get("/api/planning/nsip-conflicts")
async def nsip_conflicts(
    lat: float = Query(..., description="Latitude (WGS84)"),
    lon: float = Query(..., description="Longitude (WGS84)"),
    radius_km: float = Query(20, description="Search radius in km"),
):
    """Check for NSIP projects near a location that could cause conflicts —
    competing grid connections, cumulative landscape impact, or planning precedent.
    Returns conflict assessment with distance and risk levels."""
    from utils.pins_nsip import check_nsip_conflicts
    return await check_nsip_conflicts(lat, lon, radius_km=radius_km)
