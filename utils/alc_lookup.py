"""Agricultural Land Classification lookup — Natural England + planning.data.gov.uk."""

import logging
import httpx

log = logging.getLogger("princeps.alc")

# ALC grade descriptions and development suitability
ALC_GRADES = {
    "1": {"label": "Grade 1 — Excellent", "quality": "excellent", "bmv": True, "developable": False, "description": "Best and Most Versatile (BMV). Development strongly resisted by NPPF."},
    "2": {"label": "Grade 2 — Very Good", "quality": "very_good", "bmv": True, "developable": False, "description": "Best and Most Versatile (BMV). Sequential test required — must justify why BMV land needed."},
    "3a": {"label": "Grade 3a — Good", "quality": "good", "bmv": True, "developable": False, "description": "Best and Most Versatile (BMV). May be acceptable for solar with strong justification."},
    "3b": {"label": "Grade 3b — Moderate", "quality": "moderate", "bmv": False, "developable": True, "description": "NOT BMV. Generally acceptable for solar/wind development. Most common grade for UK solar farms."},
    "3": {"label": "Grade 3 — Good to Moderate", "quality": "moderate", "bmv": False, "developable": True, "description": "Undifferentiated Grade 3. Detailed survey needed to determine 3a vs 3b."},
    "4": {"label": "Grade 4 — Poor", "quality": "poor", "bmv": False, "developable": True, "description": "Not BMV. Suitable for development with minimal agricultural constraint."},
    "5": {"label": "Grade 5 — Very Poor", "quality": "very_poor", "bmv": False, "developable": True, "description": "Not BMV. Rough grazing, moorland. Suitable for wind farms."},
    "non_agricultural": {"label": "Non-Agricultural", "quality": "n/a", "bmv": False, "developable": True, "description": "Urban, forestry, or other non-agricultural use. No ALC constraint."},
    "urban": {"label": "Urban", "quality": "n/a", "bmv": False, "developable": True, "description": "Built-up area. Brownfield development may be preferred by planners."},
}


async def lookup_alc(lat: float, lon: float) -> dict:
    """Look up ALC grade for a location using multiple data sources."""

    result = {
        "lat": lat, "lon": lon,
        "grade": None, "label": None, "bmv": None,
        "developable": None, "description": None,
        "source": None, "confidence": None,
    }

    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "Princeps/1.0"}) as client:
        # Try planning.data.gov.uk first (most reliable for point queries)
        try:
            resp = await client.get(
                "https://www.planning.data.gov.uk/entity.json",
                params={"dataset": "agricultural-land-classification", "longitude": lon, "latitude": lat, "limit": 5},
            )
            if resp.status_code == 200:
                entities = resp.json().get("entities", [])
                if entities:
                    entity = entities[0]
                    grade_str = entity.get("name", "") or entity.get("reference", "")
                    grade = _parse_grade(grade_str)
                    if grade and grade in ALC_GRADES:
                        info = ALC_GRADES[grade]
                        result.update({
                            "grade": grade, "label": info["label"], "bmv": info["bmv"],
                            "developable": info["developable"], "description": info["description"],
                            "source": "planning.data.gov.uk", "confidence": "high",
                            "raw_name": grade_str,
                        })
                        return result
        except Exception as e:
            log.debug("planning.data.gov.uk ALC query failed: %s", e)

        # Try Natural England ArcGIS
        for service_url in [
            "https://services.arcgis.com/JJzESW51TqeY9uj5/arcgis/rest/services/Provisional_Agricultural_Land_Classification_ALC/FeatureServer/0/query",
            "https://services.arcgis.com/JJzESW51TqeY9uj5/arcgis/rest/services/Agricultural_Land_Classification_Provisional_England/FeatureServer/0/query",
        ]:
            try:
                resp = await client.get(service_url, params={
                    "geometry": f"{lon},{lat}",
                    "geometryType": "esriGeometryPoint",
                    "spatialRel": "esriSpatialRelIntersects",
                    "outFields": "*",
                    "returnGeometry": "false",
                    "f": "json",
                })
                if resp.status_code == 200:
                    data = resp.json()
                    features = data.get("features", [])
                    if features:
                        attrs = features[0].get("attributes", {})
                        # Try common field names
                        grade_str = (attrs.get("ALC_GRADE") or attrs.get("GRADE") or
                                    attrs.get("alc_grade") or attrs.get("Grade") or
                                    attrs.get("LAND_CLASS") or "")
                        grade = _parse_grade(str(grade_str))
                        if grade and grade in ALC_GRADES:
                            info = ALC_GRADES[grade]
                            result.update({
                                "grade": grade, "label": info["label"], "bmv": info["bmv"],
                                "developable": info["developable"], "description": info["description"],
                                "source": "natural_england_arcgis", "confidence": "high",
                            })
                            return result
            except Exception as e:
                log.debug("NE ArcGIS ALC query failed (%s): %s", service_url, e)

    # Fallback: latitude-based estimate (UK regional approximation)
    grade = _estimate_grade_by_location(lat, lon)
    info = ALC_GRADES.get(grade, ALC_GRADES["3b"])
    result.update({
        "grade": grade, "label": info["label"], "bmv": info["bmv"],
        "developable": info["developable"], "description": info["description"],
        "source": "latitude_estimate", "confidence": "low",
        "note": "ALC API unavailable — using regional estimate. Commission soil survey for accurate classification.",
    })
    return result


def _parse_grade(raw: str) -> str | None:
    """Parse ALC grade from various formats."""
    s = raw.strip().upper()
    if "GRADE 1" in s or s == "1": return "1"
    if "GRADE 2" in s or s == "2": return "2"
    if "3A" in s: return "3a"
    if "3B" in s: return "3b"
    if "GRADE 3" in s or s == "3": return "3"
    if "GRADE 4" in s or s == "4": return "4"
    if "GRADE 5" in s or s == "5": return "5"
    if "NON" in s or "URBAN" in s: return "non_agricultural"
    return None


def _estimate_grade_by_location(lat: float, lon: float) -> str:
    """Regional ALC estimate when API unavailable."""
    # England's best agricultural land is in the East (Fens, Lincolnshire)
    # and East Midlands. Wales/uplands are Grade 4-5.
    if lon > 0 and lat < 53.5: return "2"  # East Anglia, Lincolnshire
    if lon > -1 and lat < 53: return "3a"  # East Midlands
    if lat < 52 and lon > -2: return "3b"  # South/Southeast
    if lat > 54: return "4"  # Northern England uplands
    if lon < -3: return "4"  # Wales/Southwest uplands
    return "3b"  # Default moderate
