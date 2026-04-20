import React, { useCallback, useState } from "react";
import styles from "./TrackerLanding.module.css";
import HeroTriplicate from "./components/HeroTriplicate";
import PillarCard from "./components/PillarCard";
import PersonaCard from "./components/PersonaCard";
import DataPreviewTable from "./components/DataPreviewTable";
import OtherProductsRow from "./components/OtherProductsRow";
import TrustStrip from "./components/TrustStrip";
import BookDemoModal from "./BookDemoModal";

/* ─────────────────────────────────────────────────────────────────────────
 * Princeps Substation Tracker — public marketing landing at /tracker.
 *
 * Sections, in order:
 *   1. Marketing nav (transparent)
 *   2. Hero (triplicated animated line)
 *   3. Recent updates strip
 *   4. Three pillars (Track · Forecast · Benchmark)
 *   5. How we help — 4 buyer personas
 *   6. Data methodology
 *   7. 30-field schema list
 *   8. Data preview table (5 realistic UK rows)
 *   9. Other products teaser
 *  10. Trust strip
 *  11. CTA footer (Book demo / Talk to sales)
 *  12. Page footer
 *
 * One CTA: Book demo. No self-serve, no pricing transparency.
 * ──────────────────────────────────────────────────────────────────────── */

// ─── Personas ────────────────────────────────────────────────────────────
const PERSONAS = [
  {
    icon: "OEM",
    title: "Equipment manufacturers",
    pitch: "See every planned transformer, GIS bay and switchgear order 3–7 years out, filtered by kV and developer.",
  },
  {
    icon: "U",
    title: "Utilities & licensees",
    pitch: "Benchmark your CV cost matrix line items against NGET, SPT, SHE-T and the 6 DNOs — priced in RIIO base years.",
  },
  {
    icon: "DC",
    title: "Developers (DC · BESS · Solar)",
    pitch: "Target the substations with firm headroom and dated energisation — before the queue picks them up.",
  },
  {
    icon: "I",
    title: "Investors & finance",
    pitch: "Diligence the T&D capex programme — by TO zone, by voltage class, by price base year — in minutes not weeks.",
  },
];

// ─── 30-field schema, grouped for readability ────────────────────────────
const SCHEMA_GROUPS = [
  {
    label: "Identity",
    fields: [
      ["project_id", "str"],
      ["external_ids", "map"],
      ["substation_name", "str"],
    ],
  },
  {
    label: "Project context",
    fields: [
      ["station_type", "enum"],
      ["parent_project", "str?"],
      ["project_description", "str?"],
      ["upgrade_or_new", "enum"],
    ],
  },
  {
    label: "Location",
    fields: [
      ["region", "str"],
      ["lpa", "str?"],
      ["county", "str?"],
      ["country", "enum"],
      ["geom_wkt", "wkt?"],
      ["osgb_easting", "float?"],
      ["osgb_northing", "float?"],
    ],
  },
  {
    label: "Developer",
    fields: [
      ["parent_company", "str?"],
      ["developer", "str"],
    ],
  },
  {
    label: "Electrical",
    fields: [
      ["voltage_kv_primary", "float?"],
      ["voltage_kv_secondary", "float?"],
      ["voltage_description", "str?"],
      ["equipment_description", "str?"],
      ["equipment_capacity_mva", "float?"],
    ],
  },
  {
    label: "Timeline",
    fields: [
      ["construction_year", "int?"],
      ["construction_date_detail", "str?"],
      ["construction_status", "enum"],
      ["operation_year", "int?"],
      ["operation_date_detail", "str?"],
    ],
  },
  {
    label: "Finance",
    fields: [
      ["capex_gbp_millions", "float?"],
      ["capex_description", "str?"],
      ["capex_price_base_year", "int?"],
      ["financial_description", "str?"],
    ],
  },
  {
    label: "Provenance & housekeeping",
    fields: [
      ["source_type", "enum"],
      ["source_docket_id", "str?"],
      ["docket_profile_url", "url?"],
      ["source_links", "url[]"],
      ["capex_source_link", "url?"],
      ["last_updated", "datetime"],
      ["confidence", "float"],
      ["sme_reviewed", "bool"],
    ],
  },
];

// Sanity check: 30 fields exactly.
const TOTAL_FIELDS = SCHEMA_GROUPS.reduce((n, g) => n + g.fields.length, 0);

// ─── Marketing nav ───────────────────────────────────────────────────────
function MarketingNav({ onBookDemo }) {
  return (
    <header className={styles.nav}>
      <a href="/tracker" className={styles.brand}>
        <span className={styles.brandDot} aria-hidden="true" />
        Princeps
      </a>
      <ul className={styles.navLinks}>
        <li><a href="#product">Product</a></li>
        <li><a href="#schema">Data</a></li>
        <li><a href="#about">About</a></li>
        <li>
          <a
            href="#book-demo"
            onClick={(e) => { e.preventDefault(); onBookDemo(); }}
          >
            Book demo
          </a>
        </li>
      </ul>
    </header>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────
export default function TrackerLanding() {
  const [demoOpen, setDemoOpen] = useState(false);
  const [demoReason, setDemoReason] = useState(null);

  const openDemo = useCallback((reason) => {
    setDemoReason(typeof reason === "string" ? reason : null);
    setDemoOpen(true);
  }, []);
  const closeDemo = useCallback(() => setDemoOpen(false), []);

  return (
    <div className={styles.page}>
      <MarketingNav onBookDemo={() => openDemo("nav")} />

      {/* 1. Hero ─────────────────────────────────────────────────────── */}
      <section className={styles.hero}>
        <div className={styles.heroInner}>
          <div>
            <span className={styles.heroEyebrow}>
              <span className="dot" />
              UK Substation & Switching-Station Tracker
            </span>
            <div style={{ height: 28 }} />
            <HeroTriplicate
              lines={["Track.", "Forecast.", "Benchmark."]}
              accent={{ line: 0, word: 0 }}
            />
            <p className={styles.heroCaption}>
              Every planned UK substation and switching station — asset-level
              timelines, price base years, CV costs and changes — refreshed
              monthly. Days of desk research compressed into minutes.
            </p>
            <div className={styles.heroCta}>
              <button
                type="button"
                className={`${styles.btn} ${styles.btnPrimary}`}
                onClick={() => openDemo("hero_primary")}
              >
                Book a demo
              </button>
              <a
                href="#preview"
                className={`${styles.btn} ${styles.btnSecondary}`}
              >
                See the dataset
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* 2. Recent updates strip ─────────────────────────────────────── */}
      <section className={styles.updatesStrip} aria-label="Recent updates">
        <div className={styles.updatesInner}>
          <span className={styles.updatesBadge}>Recent</span>
          <span className={styles.updatesText}>
            <span className={styles.updatesStat}>93</span> new station projects
            across the Eastern Green Link landing corridor this month, including
            <span className={styles.updatesStat}>{" "}14</span> at 400 kV.
          </span>
          <span className={styles.updatesMeta}>Updated 2026-04 · Next refresh 2026-05</span>
        </div>
      </section>

      {/* 3. Three pillars ────────────────────────────────────────────── */}
      <section className={styles.section} id="product">
        <div className={styles.sectionHeader}>
          <div className={styles.sectionEyebrow}>Product</div>
          <h2 className={styles.sectionTitle}>Three things this dataset does.</h2>
          <p className={styles.sectionLede}>
            Single-source answers for the three questions every energy team asks
            about the grid build: what's coming, when it lands, how it priced.
          </p>
        </div>
        <div className={styles.pillarGrid}>
          <PillarCard
            verb="Track"
            body="Every planned substation and switching station across NGET, SPT, SHE-T and the 6 DNOs — resolved, deduplicated, source-cited per row."
            ctaLabel="See tracker coverage"
            onCtaClick={() => openDemo("pillar_track")}
          />
          <PillarCard
            verb="Forecast"
            body="Construction and energisation dates at the asset level, projected from RIIO CV costs, NOA optioneering and NSIP/DCO status."
            ctaLabel="See forecast horizons"
            onCtaClick={() => openDemo("pillar_forecast")}
          />
          <PillarCard
            verb="Benchmark"
            body="Capex by voltage, developer and price base year — normalised to RIIO 18/19 or 20/21 so you can compare like-for-like."
            ctaLabel="See benchmark cuts"
            onCtaClick={() => openDemo("pillar_benchmark")}
          />
        </div>
      </section>

      {/* 4. How we help ──────────────────────────────────────────────── */}
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <div className={styles.sectionEyebrow}>How we help</div>
          <h2 className={styles.sectionTitle}>Built for four kinds of energy professional.</h2>
          <p className={styles.sectionLede}>
            Each persona reads the same dataset through a different lens — the
            tracker exposes the cuts each one needs.
          </p>
        </div>
        <div className={styles.personaGrid}>
          {PERSONAS.map((p) => (
            <PersonaCard key={p.title} icon={p.icon} title={p.title} pitch={p.pitch} />
          ))}
        </div>
      </section>

      {/* 5. Data methodology ─────────────────────────────────────────── */}
      <section className={styles.methodology}>
        <div className={styles.sectionEyebrow}>Data methodology</div>
        <h2 className={styles.sectionTitle} style={{ marginBottom: 20 }}>
          Sourced from every public UK register, reconciled into one row per project.
        </h2>
        <p className={styles.methodologyBody}>
          We ingest <strong>DNO Long Term Development Statements</strong> (annual, November),
          NESO's <strong>Network Options Assessment</strong> and <strong>Centralised Strategic Network Plan</strong>,
          Ofgem's <strong>RIIO-ET2/T3 and RIIO-ED2 CV cost matrices</strong>, PINS's <strong>NSIP / DCO register</strong>,
          <strong> DESNZ Section 37 consents</strong>, Ofgem's <strong>OFTO tender packs</strong>,
          and every relevant <strong>Local Planning Authority</strong> application via PlanIt.
          Parsers emit candidate rows against one canonical 30-field schema; an entity resolver
          collapses duplicates on project ID, grid reference and licensee. Every cell carries
          a source link and a confidence score (0–1); rows below 0.65 enter an SME review queue.
          Refresh cadence is monthly, matching LTDS filing windows and NOA quarterly updates.
        </p>
      </section>

      {/* 6. Schema list ──────────────────────────────────────────────── */}
      <section className={styles.section} id="schema">
        <div className={styles.sectionHeader}>
          <div className={styles.sectionEyebrow}>Schema</div>
          <h2 className={styles.sectionTitle}>
            {TOTAL_FIELDS} canonical fields per project.
          </h2>
          <p className={styles.sectionLede}>
            UK-specific: OSGB 27700 coordinates round-tripped with WGS84,
            GBP capex tagged with RIIO price base year, DNO/TO licensee codes as
            first-class identifiers.
          </p>
        </div>
        <div className={styles.schemaBlock}>
          {SCHEMA_GROUPS.map((g) => (
            <div key={g.label} className={styles.schemaGroup}>
              <h4 className={styles.schemaGroupLabel}>
                {g.label}
                <span className={styles.schemaGroupCount}>· {g.fields.length} fields</span>
              </h4>
              <ul className={styles.schemaList}>
                {g.fields.map(([name, type]) => (
                  <li key={name}>
                    <span className={styles.schemaFieldName}>{name}</span>
                    <span className={styles.schemaFieldType}>{type}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* 7. Data preview ─────────────────────────────────────────────── */}
      <section className={styles.section} id="preview">
        <div className={styles.sectionHeader}>
          <div className={styles.sectionEyebrow}>Preview</div>
          <h2 className={styles.sectionTitle}>Real UK rows. Real citations.</h2>
          <p className={styles.sectionLede}>
            Five projects from across the tracker — transmission conversions,
            DNO uprates, and DC-adjacent bulk supply points. Every row is
            source-cited and RIIO-priced.
          </p>
        </div>
        <DataPreviewTable />
        <div style={{ marginTop: 24, textAlign: "center" }}>
          <button
            type="button"
            className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={() => openDemo("preview")}
          >
            Reach out to access the full dataset
          </button>
        </div>
      </section>

      {/* 8. Other data products ──────────────────────────────────────── */}
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <div className={styles.sectionEyebrow}>Other data products</div>
          <h2 className={styles.sectionTitle}>The rest of the Princeps data spine.</h2>
          <p className={styles.sectionLede}>
            Substations is the first dataset we opened — the pipeline datasets
            below sit on the same schema, refresh cadence and citation model.
          </p>
        </div>
        <OtherProductsRow />
      </section>

      {/* 9. Trust strip ──────────────────────────────────────────────── */}
      <TrustStrip />

      {/* 10. CTA footer ─────────────────────────────────────────────── */}
      <section className={styles.ctaFooter} id="book-demo">
        <div className={styles.ctaFooterInner}>
          <h2 className={styles.ctaFooterTitle}>Put the grid build on your desk.</h2>
          <p className={styles.ctaFooterSub}>
            20-minute demo. We'll cut the tracker to your portfolio, your voltage
            class, your RIIO base year — live.
          </p>
          <div className={styles.ctaFooterButtons}>
            <button
              type="button"
              className={`${styles.btn} ${styles.btnPrimary}`}
              onClick={() => openDemo("footer_cta")}
            >
              Book a demo
            </button>
            <a
              className={`${styles.btn} ${styles.btnSecondary}`}
              href="mailto:sales@princeps.energy?subject=Substation%20Tracker%20-%20Talk%20to%20sales"
            >
              Talk to sales
            </a>
          </div>
        </div>
      </section>

      {/* 11. Page footer ────────────────────────────────────────────── */}
      <footer className={styles.pageFooter} id="about">
        <span>© {new Date().getFullYear()} Princeps Energy Ltd · London</span>
        <span>
          <a href="#about">About</a>
          <a href="#schema">Data methodology</a>
          <a href="mailto:security@princeps.energy">Security</a>
        </span>
      </footer>

      <BookDemoModal open={demoOpen} onClose={closeDemo} reason={demoReason} />
    </div>
  );
}
