/**
 * DatasetsIndex — UK regulatory / market / grid dataset browser.
 *
 * Each card surfaces a primary-source UK energy dataset with publisher,
 * refresh cadence, row count, 7-day delta and an absolute "last refreshed"
 * timestamp. The page follows the industry-standard docket-card pattern
 * tuned for UK energy: every entry deep-links to the authoritative
 * publisher so any analyst can verify in one click.
 *
 * Data source: `src/data/mock-datasets.json` until the backend
 * `data_subscriptions` rows are ingested. The card shape is stable so the
 * real feed can slot in without UI changes.
 */
import React, { useEffect, useMemo, useState } from "react";
import datasetsFixture from "../../../data/mock-datasets.json";
import useDatasetLayer from "../../../hooks/useDatasetLayer";
import DatasetChangeLogModal from "./DatasetChangeLogModal";

// ── Design tokens ─────────────────────────────────────────────────────────
const C = {
  gold:          "#F5B731",
  goldDeep:      "#C8951E",
  goldSurface:   "rgba(245,183,49,0.10)",
  goldSurfaceHi: "rgba(245,183,49,0.22)",
  goldBorder:    "rgba(245,183,49,0.32)",
  ink:           "#0F1318",
  body:          "#3A3F46",
  muted:         "#6B7280",
  faint:         "#9CA3AF",
  border:        "#E5E7EB",
  borderSoft:    "#F1F1EE",
  ivory:         "#FBF8F2",
  cardBg:        "#FFFFFF",

  // Category palette
  catRegulatory: "#C8951E",   // deep gold
  catMarket:     "#2F8F87",   // warm teal
  catGrid:       "#6B7A8F",   // cool grey-blue

  // Badge palette
  badgeWired:    "#3B8A5A",   // filled green
  badgePartial:  "#E89A2A",   // amber
  badgeLink:     "#0F1318",   // ink outline

  // Delta colours
  deltaPos:      "#3B8A5A",
  deltaNeg:      "#C64545",
};

// ── Static filter vocabulary ──────────────────────────────────────────────
const CATEGORIES = [
  { id: "all",         label: "All" },
  { id: "REGULATORY",  label: "Regulatory" },
  { id: "MARKET",      label: "Market" },
  { id: "GRID",        label: "Grid" },
];

const BADGES = [
  { id: "all",         label: "All" },
  { id: "WIRED",       label: "Wired" },
  { id: "PARTIAL",     label: "Partial" },
  { id: "SOURCE_LINK", label: "Source link" },
];

const CADENCES = [
  { id: "all",         label: "All" },
  { id: "realtime",    label: "Realtime" },
  { id: "daily",       label: "Daily" },
  { id: "weekly",      label: "Weekly" },
  { id: "monthly",     label: "Monthly" },
  { id: "perRelease",  label: "Per release" },
  { id: "annual",      label: "Annual" },
];

// Match a dataset's free-text cadence to one of the filter buckets.
function bucketForCadence(cadence) {
  const c = (cadence || "").toLowerCase();
  if (c.includes("min") || c.includes("real") || c.includes("15-min") || c.includes("15 min"))
    return "realtime";
  if (c.includes("daily") || c.includes("day")) return "daily";
  if (c.includes("weekly") || c.includes("week")) return "weekly";
  if (c.includes("monthly") || c.includes("month") || c.includes("quarterly") || c.includes("quarter"))
    return "monthly";
  if (c.includes("annual") || c.includes("year")) return "annual";
  return "perRelease";
}

// ── Formatters ────────────────────────────────────────────────────────────
function fmtRows(n) {
  if (n == null) return "—";
  return n.toLocaleString("en-GB");
}

function fmtDelta(delta) {
  if (!delta) return null;
  const added = delta.added ?? 0;
  const removed = delta.removed ?? 0;
  return { added, removed };
}

function fmtRefreshed(iso) {
  if (!iso) return { short: "—", long: "" };
  try {
    const then = new Date(iso).getTime();
    const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
    let short;
    if (secs < 60) short = "just now";
    else if (secs < 3600) short = `${Math.floor(secs / 60)}m ago`;
    else if (secs < 86400) short = `${Math.floor(secs / 3600)}h ago`;
    else if (secs < 86400 * 30) short = `${Math.floor(secs / 86400)}d ago`;
    else if (secs < 86400 * 365) short = `${Math.floor(secs / (86400 * 30))}mo ago`;
    else short = `${Math.floor(secs / (86400 * 365))}y ago`;
    return { short, long: new Date(iso).toISOString() };
  } catch {
    return { short: "—", long: "" };
  }
}

// ── Chip components ───────────────────────────────────────────────────────
function CategoryChip({ category }) {
  const colour =
    category === "REGULATORY" ? C.catRegulatory
    : category === "MARKET"     ? C.catMarket
    : C.catGrid;
  const label =
    category === "REGULATORY" ? "Regulatory"
    : category === "MARKET"     ? "Market"
    : "Grid";
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 4, fontSize: 9, fontWeight: 800,
      letterSpacing: 0.6, textTransform: "uppercase",
      background: `${colour}1F`,
      color: colour,
      fontFamily: "'DM Sans', sans-serif",
    }}>{label}</span>
  );
}

function BadgeChip({ badge }) {
  if (badge === "WIRED") {
    return (
      <span style={{
        padding: "2px 8px", borderRadius: 10, fontSize: 9, fontWeight: 800,
        letterSpacing: 0.5, textTransform: "uppercase",
        background: C.badgeWired, color: "#FFFFFF",
      }}>Wired</span>
    );
  }
  if (badge === "PARTIAL") {
    return (
      <span style={{
        padding: "2px 8px", borderRadius: 10, fontSize: 9, fontWeight: 800,
        letterSpacing: 0.5, textTransform: "uppercase",
        background: "rgba(232,154,42,0.15)", color: C.badgePartial,
      }}>Partial</span>
    );
  }
  // SOURCE_LINK — outlined ink
  return (
    <span style={{
      padding: "1px 8px", borderRadius: 10, fontSize: 9, fontWeight: 800,
      letterSpacing: 0.5, textTransform: "uppercase",
      background: "transparent",
      color: C.ink, border: `1px solid ${C.ink}`,
    }}>Source link</span>
  );
}

// ── Pill filter ───────────────────────────────────────────────────────────
function PillGroup({ options, value, onChange, label }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
      <span style={{
        fontSize: 10, fontWeight: 700, letterSpacing: 0.6,
        textTransform: "uppercase", color: C.faint, marginRight: 2,
      }}>{label}</span>
      {options.map((opt) => {
        const active = opt.id === value;
        return (
          <button
            key={opt.id}
            type="button"
            onClick={() => onChange(opt.id)}
            style={{
              padding: "5px 12px",
              borderRadius: 999,
              border: active
                ? `1px solid ${C.goldBorder}`
                : `1px solid ${C.border}`,
              background: active ? C.gold : "#FFFFFF",
              color: active ? C.ink : C.body,
              fontSize: 11,
              fontWeight: active ? 700 : 600,
              fontFamily: "'DM Sans', sans-serif",
              cursor: "pointer",
              transition: "all 120ms ease",
              letterSpacing: "-0.01em",
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

// ── Stat cell ─────────────────────────────────────────────────────────────
function Stat({ label, children }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{
        fontSize: 9, fontWeight: 700, letterSpacing: 0.5,
        textTransform: "uppercase", color: C.faint,
      }}>{label}</span>
      {children}
    </div>
  );
}

// ── Dataset card ──────────────────────────────────────────────────────────
function DatasetCard({ dataset, onOpenChangeLog }) {
  const goToMap = useDatasetLayer();
  const refreshed = fmtRefreshed(dataset.refreshed);
  const delta = fmtDelta(dataset.delta_7d);

  const handleMap = () => {
    if (!dataset.show_on_map) return;
    goToMap(dataset.slug, dataset.map_layer_slug);
  };

  return (
    <div
      style={{
        background: C.ivory,
        border: `1px solid ${C.border}`,
        borderRadius: 12,
        padding: "16px 18px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        transition: "border-color 120ms ease, box-shadow 120ms ease",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = C.goldBorder;
        e.currentTarget.style.boxShadow = "0 2px 8px rgba(15,19,24,0.04)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = C.border;
        e.currentTarget.style.boxShadow = "none";
      }}
    >
      {/* Top row: publisher + category + badge + cadence */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{
          padding: "2px 8px", borderRadius: 4, fontSize: 9, fontWeight: 800,
          letterSpacing: 0.6, textTransform: "uppercase",
          background: C.goldSurface, color: C.goldDeep,
          fontFamily: "'DM Sans', sans-serif",
        }}>{dataset.publisher}</span>
        <CategoryChip category={dataset.category} />
        <BadgeChip badge={dataset.badge} />
        <span style={{ flex: 1 }} />
        <span style={{
          fontSize: 10, color: C.faint,
          fontFamily: "'JetBrains Mono', monospace",
          letterSpacing: 0.2,
        }}>
          {dataset.cadence}
        </span>
      </div>

      {/* Title */}
      <div style={{
        fontSize: 14, fontWeight: 700, color: C.ink,
        lineHeight: 1.3, letterSpacing: "-0.01em",
      }}>
        {dataset.title}
      </div>

      {/* Description */}
      <div style={{ fontSize: 12, color: C.body, lineHeight: 1.5 }}>
        {dataset.description}
      </div>

      {/* Returns */}
      <div style={{ fontSize: 11, color: C.muted, fontStyle: "italic" }}>
        Returns: {dataset.returns}
      </div>

      {/* Stats row */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr 1fr",
        gap: 10,
        padding: "10px 0",
        borderTop: `1px solid ${C.borderSoft}`,
      }}>
        <Stat label="Rows">
          <span style={{
            fontSize: 13, fontWeight: 700, color: C.ink,
            fontFamily: "'JetBrains Mono', monospace",
            fontVariantNumeric: "tabular-nums",
          }}>
            {fmtRows(dataset.rows)}
          </span>
        </Stat>
        <Stat label="7d delta">
          {delta ? (
            <span style={{
              fontSize: 13, fontWeight: 700,
              fontFamily: "'JetBrains Mono', monospace",
              fontVariantNumeric: "tabular-nums",
              display: "inline-flex", gap: 6, alignItems: "baseline",
            }}>
              <span style={{ color: delta.added > 0 ? C.deltaPos : C.faint }}>
                +{delta.added.toLocaleString("en-GB")}
              </span>
              <span style={{ color: C.faint }}>·</span>
              <span style={{ color: delta.removed > 0 ? C.deltaNeg : C.faint }}>
                -{delta.removed.toLocaleString("en-GB")}
              </span>
            </span>
          ) : (
            <span style={{
              fontSize: 13, fontWeight: 700, color: C.faint,
              fontFamily: "'JetBrains Mono', monospace",
            }}>—</span>
          )}
        </Stat>
        <Stat label="Refreshed">
          <span
            title={refreshed.long}
            style={{
              fontSize: 13, fontWeight: 700, color: C.ink,
              fontFamily: "'DM Sans', sans-serif",
              cursor: refreshed.long ? "help" : "default",
            }}
          >
            {refreshed.short}
          </span>
        </Stat>
      </div>

      {/* Actions */}
      <div style={{ display: "flex", gap: 8, marginTop: 2, flexWrap: "wrap" }}>
        <a
          href={dataset.primary_source_url}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            flex: "1 1 140px",
            padding: "8px 12px",
            borderRadius: 6,
            background: C.ink,
            color: "#FFFFFF",
            fontSize: 11,
            fontWeight: 700,
            textAlign: "center",
            textDecoration: "none",
            fontFamily: "'DM Sans', sans-serif",
          }}
        >
          Open primary source ↗
        </a>
        {dataset.show_on_map && (
          <button
            type="button"
            onClick={handleMap}
            style={{
              flex: "1 1 130px",
              padding: "8px 12px",
              borderRadius: 6,
              background: C.goldSurface,
              color: C.goldDeep,
              border: `1px solid ${C.goldBorder}`,
              fontSize: 11,
              fontWeight: 700,
              textAlign: "center",
              cursor: "pointer",
              fontFamily: "'DM Sans', sans-serif",
            }}
          >
            Show on Map →
          </button>
        )}
        {dataset.change_log_available && (
          <button
            type="button"
            onClick={() => onOpenChangeLog(dataset)}
            style={{
              flex: "1 1 130px",
              padding: "8px 12px",
              borderRadius: 6,
              background: "#FFFFFF",
              color: C.ink,
              border: `1px solid ${C.border}`,
              fontSize: 11,
              fontWeight: 700,
              textAlign: "center",
              cursor: "pointer",
              fontFamily: "'DM Sans', sans-serif",
            }}
          >
            Recent updates →
          </button>
        )}
      </div>
    </div>
  );
}

// ── Skeleton shimmer card (briefly shown before the fixture resolves) ────
function SkeletonCard() {
  return (
    <div style={{
      background: C.ivory,
      border: `1px solid ${C.border}`,
      borderRadius: 12,
      padding: "16px 18px",
      display: "flex",
      flexDirection: "column",
      gap: 12,
      minHeight: 260,
    }}>
      <div style={{ display: "flex", gap: 8 }}>
        <ShimmerBar w={46} h={14} />
        <ShimmerBar w={70} h={14} />
        <ShimmerBar w={50} h={14} />
      </div>
      <ShimmerBar w="65%" h={16} />
      <ShimmerBar w="100%" h={12} />
      <ShimmerBar w="92%" h={12} />
      <ShimmerBar w="70%" h={12} />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginTop: 8 }}>
        <ShimmerBar w="80%" h={22} />
        <ShimmerBar w="80%" h={22} />
        <ShimmerBar w="80%" h={22} />
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
        <ShimmerBar w="100%" h={30} />
        <ShimmerBar w="100%" h={30} />
      </div>
    </div>
  );
}

function ShimmerBar({ w, h }) {
  return (
    <div
      style={{
        width: w,
        height: h,
        borderRadius: 6,
        background: "linear-gradient(90deg, #EEE 0%, #F6F6F4 50%, #EEE 100%)",
        backgroundSize: "200% 100%",
        animation: "princepsShimmer 1.2s linear infinite",
      }}
    />
  );
}

// ── Main page ─────────────────────────────────────────────────────────────
export default function DatasetsIndex() {
  const [category, setCategory] = useState("all");
  const [badge, setBadge] = useState("all");
  const [cadence, setCadence] = useState("all");
  const [loading, setLoading] = useState(true);
  const [changeLogFor, setChangeLogFor] = useState(null);

  useEffect(() => {
    // Give the skeleton 300ms so tab switches don't flash empty.
    const t = window.setTimeout(() => setLoading(false), 300);
    return () => window.clearTimeout(t);
  }, []);

  const datasets = datasetsFixture.datasets || [];

  const filtered = useMemo(() => {
    return datasets.filter((d) => {
      if (category !== "all" && d.category !== category) return false;
      if (badge !== "all" && d.badge !== badge) return false;
      if (cadence !== "all" && bucketForCadence(d.cadence) !== cadence) return false;
      return true;
    });
  }, [datasets, category, badge, cadence]);

  const clearFilters = () => {
    setCategory("all");
    setBadge("all");
    setCadence("all");
  };

  return (
    <div style={{
      flex: 1,
      padding: "24px 32px 64px",
      overflowY: "auto",
      fontFamily: "'DM Sans', sans-serif",
      color: C.ink,
      background: C.ivory,
    }}>
      {/* Keyframes for skeleton shimmer */}
      <style>{`@keyframes princepsShimmer {
        0% { background-position: 200% 0; }
        100% { background-position: -200% 0; }
      }`}</style>

      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <h2 style={{
          fontSize: 18, margin: 0, fontWeight: 800,
          letterSpacing: "-0.02em",
        }}>
          UK Energy & Planning Datasets
        </h2>
        <div style={{
          fontSize: 12, color: C.muted, marginTop: 4, maxWidth: 760, lineHeight: 1.55,
        }}>
          Primary-source feeds Princeps consults for every project decision —
          NESO connection queue, Ofgem and DESNZ regulatory positions,
          balancing market data, planning decisions, environmental
          constraints. Click <em>Open primary source</em> on any card to
          verify directly.
        </div>
      </div>

      {/* Filter bar */}
      <div style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: "12px 14px",
        background: "#FFFFFF",
        border: `1px solid ${C.border}`,
        borderRadius: 10,
        marginBottom: 18,
      }}>
        <PillGroup label="Category" options={CATEGORIES} value={category} onChange={setCategory} />
        <PillGroup label="Badge" options={BADGES} value={badge} onChange={setBadge} />
        <PillGroup label="Cadence" options={CADENCES} value={cadence} onChange={setCadence} />
      </div>

      {/* Grid or empty/loading */}
      {loading ? (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
          gap: 14,
        }}>
          {Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
      ) : filtered.length === 0 ? (
        <div style={{
          padding: "64px 20px",
          textAlign: "center",
          color: C.muted,
          border: `1px dashed ${C.border}`,
          borderRadius: 12,
          background: "#FFFFFF",
        }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.ink, marginBottom: 8 }}>
            No datasets match your filters
          </div>
          <button
            type="button"
            onClick={clearFilters}
            style={{
              marginTop: 6,
              padding: "6px 14px",
              borderRadius: 999,
              border: `1px solid ${C.goldBorder}`,
              background: C.goldSurface,
              color: C.goldDeep,
              fontSize: 12,
              fontWeight: 700,
              cursor: "pointer",
              fontFamily: "'DM Sans', sans-serif",
            }}
          >
            Clear filters
          </button>
        </div>
      ) : (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
          gap: 14,
        }}>
          {filtered.map((d) => (
            <DatasetCard
              key={d.slug}
              dataset={d}
              onOpenChangeLog={setChangeLogFor}
            />
          ))}
        </div>
      )}

      {/* Footer caption — neutral UK-energy language */}
      <div style={{
        marginTop: 28,
        fontSize: 11,
        color: C.faint,
        fontStyle: "italic",
        maxWidth: 780,
        lineHeight: 1.6,
      }}>
        Modelled on the industry-standard docket-card pattern, tuned for UK
        energy. Every entry deep-links to the authoritative primary source
        so any analyst can verify in one click. "Wired" = Princeps ingests
        + caches + diffs; "Partial" = ingested for a subset of fields;
        "Source link" = open in the next tab.
      </div>

      {/* Change-log modal */}
      <DatasetChangeLogModal
        dataset={changeLogFor}
        onClose={() => setChangeLogFor(null)}
      />
    </div>
  );
}
