"""Unit tests for the Substation Tracker.

Covers:
  * SubstationProject schema round-trip + validator behaviour
  * UKPN ODS record → project mapping (no HTTP)
  * Entity resolver name normalisation + clustering
  * Canonical picker + confidence scoring

No live HTTP fetch, no database. Run with:

    .venv/bin/pytest tests/test_substation_tracker.py -v
"""

from __future__ import annotations

import pathlib
import sys
from datetime import datetime

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from utils.substation_tracker.schema import (
    SubstationProject,
    PARENT_COMPANY_BY_DEVELOPER,
    COUNTRY_BY_DEVELOPER,
)
from utils.substation_tracker.entity_resolver import (
    EntityResolver,
    normalise_name,
    haversine_m,
    _pick_canonical,
    _score_cluster,
)
from utils.substation_tracker.ltds_excel_parser import _ukpn_to_project
from utils.substation_tracker.riio_cv_extractor import (
    classify_source,
    _guess_upgrade,
    _guess_station_type,
)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class TestSchema:
    def test_minimal_record_roundtrip(self):
        p = SubstationProject(
            project_id="SUB-UKPN-BRAMLEY-LIVE",
            substation_name="Bramley",
            region="EPN",
            developer="UKPN",
            source_type="LTDS",
        )
        assert p.substation_name == "Bramley"
        assert p.construction_status == "unknown"   # default
        assert p.country == "England"              # default
        assert p.confidence == 0.5                 # default
        assert p.sme_reviewed is False
        # Round-trip through model_dump
        d = p.model_dump(mode="json")
        assert d["project_id"] == "SUB-UKPN-BRAMLEY-LIVE"
        assert isinstance(d["last_updated"], str)

    def test_price_base_coerced_to_two_digit(self):
        p = SubstationProject(
            project_id="x", substation_name="x", region="r",
            developer="UKPN", source_type="RIIO_ED",
            capex_price_base_year=2018,
        )
        assert p.capex_price_base_year == 18

        p2 = SubstationProject(
            project_id="y", substation_name="y", region="r",
            developer="UKPN", source_type="RIIO_ED",
            capex_price_base_year=20,
        )
        assert p2.capex_price_base_year == 20

    def test_source_links_capped_at_six(self):
        p = SubstationProject(
            project_id="x", substation_name="x", region="r",
            developer="UKPN", source_type="LTDS",
            source_links=[f"https://ex.com/{i}" for i in range(12)],
        )
        assert len(p.source_links) == 6

    def test_confidence_range_enforced(self):
        with pytest.raises(Exception):
            SubstationProject(
                project_id="x", substation_name="x", region="r",
                developer="UKPN", source_type="LTDS",
                confidence=1.5,
            )

    def test_parent_company_lookup_tables_complete(self):
        """Every licensee must have a parent_company and country."""
        for dev in ("NGET", "SPT", "SHE-T", "UKPN", "SSEN", "SPEN", "NGED", "NPG", "ENWL"):
            assert dev in PARENT_COMPANY_BY_DEVELOPER
            assert dev in COUNTRY_BY_DEVELOPER


# ---------------------------------------------------------------------------
# UKPN mapping
# ---------------------------------------------------------------------------
class TestUkpnMapping:
    def test_valid_record_produces_project(self):
        rec = {
            "sitename": "Bramley 132kV",
            "sitefunctionallocation": "UKPN-EPN-BRAMLEY-132",
            "licencearea": "EPN",
            "sitevoltage": 132.0,
            "transratingsummer": 120,
            "transratingwinter": 180,
            "sitetype": "Primary Substation",
            "county": "Hampshire",
            "geo_point_2d": {"lat": 51.35, "lon": -1.14},
        }
        proj = _ukpn_to_project(rec)
        assert proj is not None
        assert proj.developer == "UKPN"
        assert proj.parent_company == "UK Power Networks Holdings Ltd"
        assert proj.voltage_kv_primary == 132.0
        assert proj.equipment_capacity_mva == 180  # max(120, 180)
        assert proj.geom_wkt.startswith("POINT(")
        assert "EPN" in proj.region or proj.region == "Eastern Power Networks"
        assert proj.source_type == "LTDS"
        assert proj.country == "England"

    def test_missing_name_returns_none(self):
        assert _ukpn_to_project({"licencearea": "EPN"}) is None

    def test_no_coords_still_produces_project(self):
        rec = {
            "sitename": "Nameonly",
            "licencearea": "LPN",
            "sitevoltage": 33,
        }
        proj = _ukpn_to_project(rec)
        assert proj is not None
        assert proj.geom_wkt is None


# ---------------------------------------------------------------------------
# Entity resolver
# ---------------------------------------------------------------------------
class TestNormalisation:
    def test_strip_voltage_suffix(self):
        assert normalise_name("Bramley 400kV Substation") == "bramley"

    def test_strip_qualifiers(self):
        assert normalise_name("Bramley Substation Extension") == "bramley"
        assert normalise_name("Bramley 132kV Primary Substation") == "bramley"

    def test_handle_punctuation(self):
        assert normalise_name("Bramley/North-Substation") == "bramley north"

    def test_empty_input(self):
        assert normalise_name("") == ""
        assert normalise_name(None) == ""


class TestHaversine:
    def test_zero_distance(self):
        assert haversine_m(51.5, -0.1, 51.5, -0.1) == pytest.approx(0, abs=1e-3)

    def test_known_distance(self):
        # London → Reading ~ 56 km
        d = haversine_m(51.5074, -0.1278, 51.4543, -0.9781)
        assert 55_000 < d < 60_000


class TestResolver:
    def _make(self, name, dev="UKPN", src="LTDS", conf=0.8, wkt=None):
        return SubstationProject(
            project_id=f"SUB-{dev}-{name.upper().replace(' ', '-')}-LIVE",
            substation_name=name,
            region="EPN",
            developer=dev,
            source_type=src,
            confidence=conf,
            geom_wkt=wkt,
        )

    def test_single_record_one_cluster(self):
        r = EntityResolver()
        out = r.resolve([self._make("Bramley")])
        assert len(out) == 1
        assert out[0].canonical.substation_name == "Bramley"

    def test_duplicate_names_cluster(self):
        r = EntityResolver()
        out = r.resolve([
            self._make("Bramley 400kV", src="LTDS"),
            self._make("Bramley Substation", src="NOA", dev="NGET"),
        ])
        # Names match but developers differ — without coords, shouldn't merge.
        assert len(out) == 2

    def test_same_developer_fuzzy_match_clusters(self):
        r = EntityResolver()
        out = r.resolve([
            self._make("Bramley 132kV", dev="UKPN", src="LTDS"),
            self._make("Bramley Substation", dev="UKPN", src="RIIO_ED"),
        ])
        assert len(out) == 1
        assert len(out[0].members) == 2

    def test_geo_tiebreaker_merges_cross_developer(self):
        r = EntityResolver(geo_threshold_m=600)
        # Two records at ~100m apart — same name after normalisation, different developer.
        a = self._make("Bramley", dev="UKPN", src="LTDS", wkt="POINT(-1.14 51.35)")
        b = self._make("Bramley North Substation", dev="NGET", src="NOA",
                       wkt="POINT(-1.141 51.3502)")
        out = r.resolve([a, b])
        assert len(out) == 1

    def test_canonical_prefers_ltds_over_noa(self):
        ltds = self._make("Bramley", src="LTDS", conf=0.7)
        noa  = self._make("Bramley Substation", src="NOA", conf=0.9)
        chosen = _pick_canonical([noa, ltds])
        assert chosen.source_type == "LTDS"

    def test_cluster_score_bonus_for_multi_source(self):
        members = [
            self._make("Bramley", src="LTDS", conf=0.6),
            self._make("Bramley", src="NOA", conf=0.6),
            self._make("Bramley", src="RIIO_ED", conf=0.6),
        ]
        assert _score_cluster(members) == pytest.approx(0.8, abs=1e-3)

    def test_cluster_score_caps_at_1(self):
        members = [self._make("x", src=s, conf=0.95) for s in ("LTDS", "NOA", "CSNP", "RIIO_ED", "RIIO_ET", "NSIP_DCO")]
        assert _score_cluster(members) == 1.0


# ---------------------------------------------------------------------------
# RIIO classification + heuristics
# ---------------------------------------------------------------------------
class TestRiioHeuristics:
    def test_classify_source_by_developer(self):
        assert classify_source(pathlib.Path("whatever.xlsx"), "NGET") == "RIIO_ET"
        assert classify_source(pathlib.Path("whatever.xlsx"), "UKPN") == "RIIO_ED"
        assert classify_source(pathlib.Path("whatever.xlsx"), "SHE-T") == "RIIO_ET"

    def test_classify_source_by_filename_fallback(self):
        assert classify_source(pathlib.Path("riio_et2_cv.xlsx"), "UNKNOWN") == "RIIO_ET"
        assert classify_source(pathlib.Path("ed2-cv-matrix.xlsx"), "UNKNOWN") == "RIIO_ED"

    def test_guess_upgrade_new_vs_replacement(self):
        assert _guess_upgrade("Greenfield 400kV", "", "") == "new"
        assert _guess_upgrade("", "asset renewal", "") == "replacement"
        assert _guess_upgrade("", "", "reinforcement") == "upgrade"
        assert _guess_upgrade("misc", "misc", "") == "unknown"

    def test_guess_station_type(self):
        assert _guess_station_type("Bramley Switching Station", "") == "switching_station"
        assert _guess_station_type("Bramley Substation", "") == "substation"


# ---------------------------------------------------------------------------
# Pipeline glue (no DB — just smoke)
# ---------------------------------------------------------------------------
class TestPipelineGlue:
    def test_infer_developer_from_filename(self):
        from utils.substation_tracker.pipeline import _infer_developer_from_filename
        assert _infer_developer_from_filename("UKPN_cv_2025.xlsx") == "UKPN"
        assert _infer_developer_from_filename("she-t_bp.xlsx") == "SHE-T"
        assert _infer_developer_from_filename("nothing_here.xlsx") == "NGET"  # default
