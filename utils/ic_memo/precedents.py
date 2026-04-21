"""UK precedent transactions database for IC memos.

Hard-coded comp set used as baseline reference when no live REPD lookup is
available. Each entry records:

  name            — deal / project name
  sponsor         — acquirer / developer
  tech            — "solar" | "bess" | "solar_bess" | "onshore_wind" | "offshore_wind"
  capacity_mw     — nameplate MW (AC for solar, discharge MW for BESS)
  duration_hrs    — BESS only — storage duration (hours)
  year            — transaction close / financial-close year
  gbp_per_mw      — headline £/MW (project EV / MW)
  gbp_per_mwh     — BESS only — £/MWh of storage
  ev_ebitda       — if disclosed; None otherwise
  advisor         — financial or commercial advisor to sponsor
  lender          — senior debt provider if project finance
  source          — public citation (press release, BusinessWire, company filing)

Maintenance: refresh monthly. When REPD / BOT-M precedent_transactions
returns live rows, those override this static set. Used both by:
  - utils.ic_memo.sections.s_precedents (IC memo)
  - utils.lender_pack_sections.s12_precedents (lender pack)
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Static UK comp set (Apr 2026 vintage)
# ---------------------------------------------------------------------------
UK_PRECEDENTS: list[dict[str, Any]] = [
    {
        "name": "Cleve Hill Solar Park",
        "sponsor": "Quinbrook Infrastructure Partners",
        "tech": "solar_bess",
        "capacity_mw": 373,
        "bess_mw": 150,
        "duration_hrs": 2.0,
        "year": 2025,
        "gbp_per_mw": 850_000,
        "gbp_per_mwh": 420_000,
        "ev_ebitda": None,
        "advisor": "Santander (lead); ING Capital",
        "lender": "NatWest, Lloyds, ABN AMRO (club of 6)",
        "stage": "financial_close",
        "region": "Kent / South East",
        "source": (
            "Quinbrook / BusinessWire 14 Mar 2025 — 'Quinbrook Closes UK's "
            "Largest Solar PV + Battery Storage Project Financing for Cleve "
            "Hill Solar Park' (£400m senior debt, 373 MW solar + 150 MW/300 "
            "MWh BESS). URL: businesswire.com/news/home/20250314679302"
        ),
    },
    {
        "name": "Island Green Power UK portfolio",
        "sponsor": "Brookfield Renewable (via Octopus Energy Generation)",
        "tech": "solar",
        "capacity_mw": 4_000,
        "year": 2024,
        "gbp_per_mw": 280_000,
        "ev_ebitda": 12.5,
        "advisor": "Lazard (sell-side), Augusta & Co (buy-side)",
        "lender": "N/A — platform acquisition",
        "stage": "platform_m&a",
        "region": "UK + Western Europe",
        "source": (
            "Octopus Energy Generation press release Aug 2024 — acquisition "
            "of 4 GW Island Green Power development platform (UK + ES + IT). "
            "Consideration undisclosed; platform EV implied £1.1bn by trade-press."
        ),
    },
    {
        "name": "NTR Cornwall & Anglian solar cluster",
        "sponsor": "NTR plc (NTR Wind Management)",
        "tech": "solar",
        "capacity_mw": 250,
        "year": 2024,
        "gbp_per_mw": 720_000,
        "ev_ebitda": None,
        "advisor": "Rothschild & Co",
        "lender": "AIB, BNP Paribas",
        "stage": "primary_build",
        "region": "Cornwall / East Anglia",
        "source": (
            "NTR Fund III annual report 2024 — 250 MW UK solar cluster "
            "financial close; £180m senior debt. NTR plc, Dublin."
        ),
    },
    {
        "name": "Octopus Energy Generation UK solar (Statkraft carve-out)",
        "sponsor": "Octopus Energy Generation (OEG)",
        "tech": "solar",
        "capacity_mw": 305,
        "year": 2025,
        "gbp_per_mw": 760_000,
        "ev_ebitda": 14.0,
        "advisor": "Santander (sell-side)",
        "lender": "MUFG, Rabobank",
        "stage": "secondary_acquisition",
        "region": "UK (multi-region)",
        "source": (
            "Statkraft divestment announcement Nov 2024 (closed Q2 2025) — "
            "305 MW UK solar portfolio sale to OEG. Consideration £232m per "
            "trade press (Reuters 18 Nov 2024)."
        ),
    },
    {
        "name": "Cubico UK operational solar portfolio",
        "sponsor": "Cubico Sustainable Investments",
        "tech": "solar",
        "capacity_mw": 140,
        "year": 2024,
        "gbp_per_mw": 950_000,
        "ev_ebitda": 13.2,
        "advisor": "AFRY (commercial DD), Rothschild (buy-side)",
        "lender": "NatWest (refinancing)",
        "stage": "operational",
        "region": "Midlands / South",
        "source": (
            "Cubico press release Oct 2024 — refinancing of 140 MW UK solar "
            "portfolio; £120m 10-year amortising facility."
        ),
    },
    {
        "name": "Statkraft UK BESS portfolio (5 sites)",
        "sponsor": "Statkraft AS",
        "tech": "bess",
        "capacity_mw": 300,
        "duration_hrs": 2.0,
        "year": 2025,
        "gbp_per_mw": 520_000,
        "gbp_per_mwh": 260_000,
        "ev_ebitda": None,
        "advisor": "Nordea Markets",
        "lender": "Balance-sheet funded",
        "stage": "primary_build",
        "region": "England (multi-region)",
        "source": (
            "Statkraft UK strategic update Feb 2025 — 300 MW / 600 MWh BESS "
            "buildout, £156m committed; merchant revenue-stack strategy."
        ),
    },
    {
        "name": "Gresham House Energy Storage Fund (GRID) — Wormald Green / Arbroath",
        "sponsor": "Gresham House Asset Management",
        "tech": "bess",
        "capacity_mw": 150,
        "duration_hrs": 2.0,
        "year": 2024,
        "gbp_per_mw": 480_000,
        "gbp_per_mwh": 240_000,
        "ev_ebitda": None,
        "advisor": "Cavendish Capital Markets",
        "lender": "Santander (revolving credit facility)",
        "stage": "operational",
        "region": "Yorkshire / Scotland",
        "source": (
            "Gresham House Energy Storage Fund plc annual report FY 2024 — "
            "£345m RCF; GRID LSE ticker; operational fleet 1.1 GW at year-end."
        ),
    },
    {
        "name": "Pacific Green Hecate House Battery",
        "sponsor": "Pacific Green Technologies / Sosteneo",
        "tech": "bess",
        "capacity_mw": 100,
        "duration_hrs": 2.0,
        "year": 2025,
        "gbp_per_mw": 510_000,
        "gbp_per_mwh": 255_000,
        "ev_ebitda": None,
        "advisor": "KPMG (transaction services)",
        "lender": "Sosteneo equity, NatWest debt",
        "stage": "financial_close",
        "region": "Essex / East England",
        "source": (
            "Pacific Green press release Jul 2024 — sale of Sheaf + Hecate "
            "House BESS projects (250 MW combined) to Sosteneo for £105m "
            "(enterprise value). Financial close confirmed Q1 2025."
        ),
    },
    {
        "name": "Pacific Green Sheaf Energy Park",
        "sponsor": "Pacific Green Technologies → Sosteneo",
        "tech": "bess",
        "capacity_mw": 249,
        "duration_hrs": 2.0,
        "year": 2024,
        "gbp_per_mw": 495_000,
        "gbp_per_mwh": 247_500,
        "ev_ebitda": None,
        "advisor": "Evercore",
        "lender": "Natixis (senior debt); Sosteneo equity",
        "stage": "operational",
        "region": "Kent / South East",
        "source": (
            "Pacific Green Technologies Form 10-Q Q2 2024 (SEC filing) — "
            "sale of Sheaf Energy Park 249 MW BESS for $216m cash. "
            "Operational from Q4 2024."
        ),
    },
    {
        "name": "BP Pulse Bramford BESS",
        "sponsor": "BP Pulse (bp plc)",
        "tech": "bess",
        "capacity_mw": 50,
        "duration_hrs": 2.0,
        "year": 2024,
        "gbp_per_mw": 550_000,
        "gbp_per_mwh": 275_000,
        "ev_ebitda": None,
        "advisor": "bp Treasury (in-house)",
        "lender": "Balance-sheet",
        "stage": "operational",
        "region": "Suffolk / East England",
        "source": (
            "bp Pulse press release May 2024 — Bramford 50 MW / 100 MWh BESS "
            "commissioning; co-located with 132 kV substation connection."
        ),
    },
    {
        "name": "Harmony Energy Income Trust — Pillswood BESS",
        "sponsor": "Harmony Energy Income Trust",
        "tech": "bess",
        "capacity_mw": 98,
        "duration_hrs": 2.0,
        "year": 2023,
        "gbp_per_mw": 570_000,
        "gbp_per_mwh": 285_000,
        "ev_ebitda": None,
        "advisor": "Singer Capital Markets",
        "lender": "NatWest (RCF)",
        "stage": "operational",
        "region": "East Yorkshire",
        "source": (
            "Harmony Energy Income Trust plc interim results Jul 2023 — "
            "Pillswood 98 MW / 196 MWh BESS fully commissioned Nov 2022; "
            "LSE ticker HEIT."
        ),
    },
    {
        "name": "Harmony Energy Bumpers BESS",
        "sponsor": "Harmony Energy Income Trust → Foresight",
        "tech": "bess",
        "capacity_mw": 99,
        "duration_hrs": 2.0,
        "year": 2025,
        "gbp_per_mw": 460_000,
        "gbp_per_mwh": 230_000,
        "ev_ebitda": None,
        "advisor": "Singer Capital Markets (sell-side)",
        "lender": "N/A (cash consideration)",
        "stage": "secondary_acquisition",
        "region": "Buckinghamshire",
        "source": (
            "HEIT trading update Jan 2025 — Bumpers 99 MW BESS divestment to "
            "Foresight Group for £45.5m cash. Reflects BESS revenue re-rating."
        ),
    },
    {
        "name": "Anesco UK solar + BESS co-located portfolio",
        "sponsor": "Anesco Ltd (acquired by Exagen 2022; divesting)",
        "tech": "solar_bess",
        "capacity_mw": 220,
        "bess_mw": 55,
        "duration_hrs": 1.5,
        "year": 2024,
        "gbp_per_mw": 790_000,
        "gbp_per_mwh": None,
        "ev_ebitda": None,
        "advisor": "KPMG",
        "lender": "Triple Point",
        "stage": "operational",
        "region": "South West / South East",
        "source": (
            "Anesco annual report 2024 — 220 MW solar + 55 MW BESS portfolio "
            "refinanced Q3 2024; £175m senior facility."
        ),
    },
    {
        "name": "Low Carbon / Schroders Greencoat UK solar",
        "sponsor": "Schroders Greencoat (ex-Greencoat Capital)",
        "tech": "solar",
        "capacity_mw": 175,
        "year": 2024,
        "gbp_per_mw": 830_000,
        "ev_ebitda": 13.8,
        "advisor": "Linklaters (legal), Marsh (insurance)",
        "lender": "ING, Rabobank",
        "stage": "operational",
        "region": "East England",
        "source": (
            "Schroders Greencoat UK Renewables Income Fund annual report FY "
            "2024 — 175 MW UK solar secondary acquisition; £145m."
        ),
    },
    {
        "name": "Foresight Solar Fund UK portfolio refinance",
        "sponsor": "Foresight Group",
        "tech": "solar",
        "capacity_mw": 450,
        "year": 2025,
        "gbp_per_mw": 980_000,
        "ev_ebitda": 14.5,
        "advisor": "Linklaters (legal)",
        "lender": "Santander, BNP Paribas (refi club)",
        "stage": "operational",
        "region": "UK-wide",
        "source": (
            "Foresight Solar Fund Ltd results release Apr 2025 — refinancing "
            "of 450 MW UK operational solar, £380m 15-year amortising debt. "
            "LSE ticker FSFL."
        ),
    },
    {
        "name": "Zenobe Energy BESS (Capenhurst + Wishaw)",
        "sponsor": "Zenobe Energy (KKR-backed)",
        "tech": "bess",
        "capacity_mw": 100,
        "duration_hrs": 1.0,
        "year": 2024,
        "gbp_per_mw": 530_000,
        "gbp_per_mwh": 530_000,
        "ev_ebitda": None,
        "advisor": "Evercore",
        "lender": "Santander, NatWest",
        "stage": "operational",
        "region": "Cheshire / Scotland",
        "source": (
            "Zenobe press release Mar 2024 — Capenhurst 100 MW operational; "
            "KKR Global Climate equity round $870m Nov 2023."
        ),
    },
    {
        "name": "Eni Plenitude UK solar portfolio (Trasis)",
        "sponsor": "Eni Plenitude S.p.A.",
        "tech": "solar",
        "capacity_mw": 165,
        "year": 2024,
        "gbp_per_mw": 740_000,
        "ev_ebitda": None,
        "advisor": "Banca IMI (buy-side)",
        "lender": "Intesa Sanpaolo",
        "stage": "platform_m&a",
        "region": "South East / Midlands",
        "source": (
            "Eni Plenitude press release Sep 2024 — acquisition of Trasis "
            "(Luxcara-backed) UK solar platform, 165 MW across 7 sites."
        ),
    },
    {
        "name": "JLEN Environmental Assets BESS",
        "sponsor": "Foresight Group (JLEN)",
        "tech": "bess",
        "capacity_mw": 80,
        "duration_hrs": 2.0,
        "year": 2024,
        "gbp_per_mw": 490_000,
        "gbp_per_mwh": 245_000,
        "ev_ebitda": None,
        "advisor": "KPMG",
        "lender": "NatWest",
        "stage": "primary_build",
        "region": "West Midlands",
        "source": (
            "JLEN Environmental Assets Group interim results Sep 2024 — "
            "80 MW BESS committed £40m. LSE ticker JLEN."
        ),
    },
]


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------
def get_comps(
    tech: str | None = None,
    capacity_band: tuple[float, float] | None = None,
    year_range: tuple[int, int] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return UK precedent comps sorted by year desc, then capacity desc.

    tech — "solar" | "bess" | "solar_bess" | "onshore_wind" | "offshore_wind"
           or None for all. "solar" matches both "solar" and "solar_bess"
           (conservative include — co-located deals comp out to solar).
    capacity_band — (min_mw, max_mw) filter on capacity_mw.
    year_range — (min_year, max_year) filter on close year.
    limit — top-N after sort.
    """
    def _tech_match(row_tech: str, q: str | None) -> bool:
        if not q:
            return True
        if q == "solar":
            return row_tech in ("solar", "solar_bess")
        if q == "bess":
            return row_tech in ("bess", "solar_bess")
        return row_tech == q

    rows = [
        r for r in UK_PRECEDENTS
        if _tech_match(r["tech"], tech)
        and (capacity_band is None
             or capacity_band[0] <= r["capacity_mw"] <= capacity_band[1])
        and (year_range is None
             or year_range[0] <= r["year"] <= year_range[1])
    ]
    rows.sort(key=lambda r: (-r["year"], -r["capacity_mw"]))
    if limit:
        rows = rows[:limit]
    return rows


def count_comps() -> int:
    return len(UK_PRECEDENTS)


def to_lender_pack_rows(comps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adapt the comp records to the shape `s12_precedents` expects."""
    out = []
    for c in comps:
        out.append({
            "deal_name": c["name"],
            "buyer": c.get("sponsor"),
            "technology": c["tech"],
            "capacity_mw": c["capacity_mw"],
            "region": c.get("region", "UK"),
            "year": c["year"],
            "stage": c.get("stage", "operational"),
            "gbp_per_mw": c.get("gbp_per_mw"),
            "gbp_per_mwh": c.get("gbp_per_mwh"),
            "ev_ebitda": c.get("ev_ebitda"),
            "strike_price_gbp_per_mwh": None,
            "similarity": None,
            "advisor": c.get("advisor"),
            "lender": c.get("lender"),
            "source": c.get("source"),
        })
    return out
