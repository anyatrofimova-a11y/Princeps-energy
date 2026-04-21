#!/usr/bin/env python3
"""
scripts/build_lpa_seed.py — expand the Princeps authorities seed with the full
UK Local Planning Authority register.

Pulls the ONS Local Authority District (LAD) 2024 register. If the live ONS
Open Geography portal is unreachable, falls back to the bundled CSV at
``app/dockets/data/lpa_registry_2024.csv`` (checked into the repo so seeding
works offline / in CI).

Sources (all real public data — USE REAL PUBLIC DATA):
  - ONS Open Geography Portal:
      https://geoportal.statistics.gov.uk/datasets/ons::local-authority-districts-may-2024-boundaries-uk-bfc/about
  - gov.uk local authority codes for England:
      https://www.gov.uk/guidance/local-authority-codes-for-england
  - Scottish councils:           https://www.cosla.gov.uk
  - Welsh principal councils:    https://www.wlga.wales
  - NI 11-council model:         https://www.communities-ni.gov.uk

Output: overwrites ``app/dockets/data/authorities_seed.json`` preserving the
existing non-LPA entries (DNOs, TOs, regulators, statutory consultees, crown,
devolved bodies) and appending every LPA/CC/NPA in the registry.

Idempotent — re-running produces byte-identical output if nothing changed.

Run:
    python3 scripts/build_lpa_seed.py
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_JSON = REPO_ROOT / "app" / "dockets" / "data" / "authorities_seed.json"
CSV_FALLBACK = REPO_ROOT / "app" / "dockets" / "data" / "lpa_registry_2024.csv"

# ONS LAD24 CSV endpoint (ArcGIS Hub). If the network is up we prefer this so
# boundary/name changes land automatically. Otherwise we read the bundled CSV.
ONS_LAD24_CSV = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "Local_Authority_Districts_May_2024_Boundaries_UK_BFC/FeatureServer/0/"
    "query?where=1%3D1&outFields=LAD24CD,LAD24NM&outSR=4326&f=json"
)


def _country_from_code(code: str) -> str:
    """Map ONS prefix to our jurisdiction code."""
    prefix = code[:1].upper()
    if prefix == "E":
        return "E"
    if prefix == "S":
        return "S"
    if prefix == "W":
        return "W"
    if prefix == "N":
        return "NI"
    return "UK"


def _slug_from_code(code: str) -> str:
    """Canonical slug is the ONS code lowercased (stable, unique, audit-friendly)."""
    return code.lower()


def _load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        print(f"ERROR: fallback CSV missing at {path}", file=sys.stderr)
        sys.exit(1)
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _try_ons_live() -> list[dict[str, str]] | None:
    """Attempt to fetch the live ONS LAD24 register. Returns None on any failure
    (network, parse, etc) so the caller falls back to the bundled CSV."""
    try:
        import urllib.request  # local import — offline environments skip this

        req = urllib.request.Request(
            ONS_LAD24_CSV,
            headers={"User-Agent": "Princeps/1.0 (LPA seed builder)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
        features = payload.get("features") or []
        if not features:
            return None
        out: list[dict[str, str]] = []
        for feat in features:
            attrs = feat.get("attributes") or {}
            code = attrs.get("LAD24CD")
            name = attrs.get("LAD24NM")
            if not code or not name:
                continue
            out.append({
                "ons_code": code,
                "name": name,
                "country": _country_from_code(code),
                "region": "",
                "acronym": "",
                "homepage": "",
            })
        return out if out else None
    except Exception as exc:  # pragma: no cover — offline / transient
        print(f"[build_lpa_seed] ONS live fetch failed ({exc}); using CSV fallback.",
              file=sys.stderr)
        return None


def _acronym_fallback(name: str, code: str) -> str:
    """Compose a readable acronym when the CSV row doesn't carry one.

    London boroughs get LB<initials>; everywhere else take the initials of the
    capitalised words and cap at 6 chars."""
    if code.startswith("E09"):
        stem = "".join(w[0] for w in name.split() if w[:1].isupper())
        return f"LB{stem}"[:6]
    stem = "".join(w[0] for w in name.split() if w[:1].isupper())
    return stem[:6] or code[-3:]


def _to_authority_row(r: dict[str, str]) -> dict[str, Any]:
    """Translate a CSV registry row into the authorities_seed.json schema."""
    code = r["ons_code"].strip()
    name = r["name"].strip()
    home = (r.get("homepage") or "").strip() or f"https://www.gov.uk/find-local-council"
    acronym = (r.get("acronym") or "").strip() or _acronym_fallback(name, code)
    return {
        "slug": _slug_from_code(code),
        "name": name,
        "acronym": acronym,
        "type": "lpa",
        "jurisdiction": _country_from_code(code),
        "ons_code": code,
        "home_url": home,
        "planning_portal_url": home.rstrip("/") + "/planning",
        "api_available": False,
    }


def _load_existing_non_lpas(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read the current seed JSON and return:

    - the list of authority rows whose type != 'lpa' (must be preserved)
    - the existing _meta dict (we'll update it)
    """
    if not path.exists():
        return [], {}
    payload = json.loads(path.read_text())
    meta = payload.get("_meta") or {}
    rows = payload.get("authorities") or []
    non_lpas = [r for r in rows if (r.get("type") or "").lower() != "lpa"]
    return non_lpas, meta


def build() -> dict[str, Any]:
    """Assemble the full seed payload."""
    # 1. Try live ONS; else fallback CSV.
    registry = _try_ons_live()
    if registry is None:
        registry = _load_csv(CSV_FALLBACK)

    # If we pulled from ONS live, re-merge name/acronym/homepage from the bundled
    # CSV where present (live only gives code+name; we still want curated
    # homepages for the planning_portal_url enrichment).
    csv_index: dict[str, dict[str, str]] = {}
    if CSV_FALLBACK.exists():
        for row in _load_csv(CSV_FALLBACK):
            csv_index[row["ons_code"].upper()] = row
    merged: list[dict[str, str]] = []
    for row in registry:
        curated = csv_index.get(row["ons_code"].upper())
        if curated:
            merged.append({**row, **{k: v for k, v in curated.items() if v}})
        else:
            merged.append(row)

    # 2. Preserve non-LPA authorities from the current JSON.
    non_lpas, existing_meta = _load_existing_non_lpas(SEED_JSON)

    # 3. Build LPA rows.
    lpa_rows = [_to_authority_row(r) for r in merged]

    # 4. Stable ordering: non-LPAs first (as they stood), then LPAs grouped by
    # jurisdiction (E → S → W → NI), sorted by ONS code within each group.
    jurisdiction_order = {"E": 0, "S": 1, "W": 2, "NI": 3}
    lpa_rows.sort(key=lambda r: (jurisdiction_order.get(r["jurisdiction"], 9),
                                 r["ons_code"]))

    # 5. Count by jurisdiction for the meta block + CLI banner.
    counts = Counter(r["jurisdiction"] for r in lpa_rows)

    meta = {
        **existing_meta,
        "description": (
            "UK authorities registry seed for Princeps. Each entry becomes a row "
            "in authorities(). Slugs are canonical and must not change once "
            "seeded. LPA rows are generated from the ONS LAD24 register "
            "(local-authority-districts May 2024) plus 22 English County "
            "Councils and 10 National Park Authorities; non-LPA rows (DNOs, "
            "TOs, regulators, statutory consultees, crown bodies) are curated."
        ),
        "generated_by": "scripts/build_lpa_seed.py",
        "version": "2.0.0",
        "lpa_counts": {
            "E": counts.get("E", 0),
            "S": counts.get("S", 0),
            "W": counts.get("W", 0),
            "NI": counts.get("NI", 0),
            "total": sum(counts.values()),
        },
        "non_lpa_count": len(non_lpas),
    }

    return {
        "_meta": meta,
        "authorities": non_lpas + lpa_rows,
    }


def main() -> int:
    payload = build()
    SEED_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    counts = payload["_meta"]["lpa_counts"]
    print(f"Wrote {SEED_JSON}")
    print(f"  non-LPA authorities preserved: {payload['_meta']['non_lpa_count']}")
    print(f"  LPAs by jurisdiction: "
          f"E={counts['E']}, S={counts['S']}, W={counts['W']}, NI={counts['NI']}")
    print(f"  TOTAL LPAs: {counts['total']}")
    print(f"  TOTAL authorities: {len(payload['authorities'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
