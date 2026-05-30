import React, { useCallback, useEffect, useMemo, useState } from "react";

/**
 * PlanningConstraintsPanel — Task #17.
 *
 * Mounts inside ProjectWorkspace, fetches GET /api/planning-data/constraints
 * for the project's lat/lon @ 500 m radius, and renders a tabular
 * verdict grouped CRITICAL → HIGH → MEDIUM. Each row links straight to
 * planning.data.gov.uk/entity/{id}.
 *
 * Map layer toggling lives in the parent: this component just emits an
 * `onLayerToggle(slug, enabled)` callback the parent wires into the
 * Mapbox `planning-designations` MVT source.
 */

const SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM"];

const SEVERITY_STYLE = {
  CRITICAL: { bg: "#FEE2E2", fg: "#7F1D1D", chip: "#DC2626" },
  HIGH:     { bg: "#FEF3C7", fg: "#78350F", chip: "#E8A012" },
  MEDIUM:   { bg: "#E0F2FE", fg: "#0C4A6E", chip: "#0284C7" },
};

const DATASET_LABELS = {
  "site-of-special-scientific-interest": "SSSI",
  "ancient-woodland": "Ancient Woodland",
  "flood-risk-zone": "Flood Risk Zone",
  "green-belt": "Green Belt",
  "agricultural-land-classification": "Agricultural Land Class.",
  "special-area-of-conservation": "SAC",
  "special-protection-area": "SPA",
  "ramsar": "Ramsar wetland",
  "listed-building": "Listed Building",
  "listed-building-outline": "Listed Building outline",
  "conservation-area": "Conservation Area",
  "scheduled-monument": "Scheduled Monument",
  "national-park": "National Park",
  "area-of-outstanding-natural-beauty": "AONB",
  "local-nature-reserve": "Local Nature Reserve",
  "national-nature-reserve": "National Nature Reserve",
  "nutrient-neutrality-catchment": "Nutrient Neutrality Catchment",
  "tree-preservation-zone": "TPO Zone",
  "article-4-direction-area": "Article 4 Direction",
  "brownfield-land": "Brownfield Land",
  "local-planning-authority": "LPA",
};

function labelFor(slug) { return DATASET_LABELS[slug] || slug; }
function fmtDist(m) {
  if (m == null) return "—";
  if (m < 1) return "0 m (overlap)";
  if (m < 1000) return `${Math.round(m)} m`;
  return `${(m / 1000).toFixed(2)} km`;
}

function SeverityChip({ severity }) {
  const s = SEVERITY_STYLE[severity] || SEVERITY_STYLE.MEDIUM;
  return (
    <span
      className="pcp-chip"
      style={{ background: s.chip, color: "#FFFFFF" }}
    >
      {severity}
    </span>
  );
}

function HitRow({ hit }) {
  return (
    <tr className="pcp-row">
      <td className="pcp-cell-sev">
        <SeverityChip severity={hit.severity} />
      </td>
      <td className="pcp-cell-name">
        <div className="pcp-name">
          {hit.name || hit.reference || `entity ${hit.entity_id}`}
        </div>
        <div className="pcp-dataset">{labelFor(hit.dataset)}</div>
      </td>
      <td className="pcp-cell-dist">{fmtDist(hit.distance_m)}</td>
      <td className="pcp-cell-link">
        {hit.source_url ? (
          <a href={hit.source_url} target="_blank" rel="noopener noreferrer">
            entity {hit.entity_id} ↗
          </a>
        ) : "—"}
      </td>
    </tr>
  );
}

function GroupSection({ severity, hits, datasetToggle, enabledSlugs }) {
  if (!hits.length) return null;
  const slugsInGroup = Array.from(new Set(hits.map(h => h.dataset))).sort();
  const style = SEVERITY_STYLE[severity];
  return (
    <section
      className="pcp-group"
      style={{ background: style.bg, borderLeft: `4px solid ${style.chip}` }}
    >
      <header className="pcp-group-head" style={{ color: style.fg }}>
        <strong>{severity}</strong>
        <span className="pcp-group-count">{hits.length} designation{hits.length === 1 ? "" : "s"}</span>
      </header>
      {slugsInGroup.length > 0 && (
        <div className="pcp-toggles">
          {slugsInGroup.map(slug => {
            const enabled = enabledSlugs?.has(slug);
            return (
              <button
                key={slug}
                type="button"
                className={"pcp-toggle" + (enabled ? " pcp-toggle-on" : "")}
                onClick={() => datasetToggle(slug, !enabled)}
                title={enabled ? `Hide ${labelFor(slug)} on map` : `Show ${labelFor(slug)} on map`}
              >
                {enabled ? "● " : "○ "}{labelFor(slug)}
              </button>
            );
          })}
        </div>
      )}
      <table className="pcp-table">
        <thead>
          <tr>
            <th></th>
            <th>Designation</th>
            <th>Distance</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {hits.map(h => (
            <HitRow key={`${h.dataset}-${h.entity_id}`} hit={h} />
          ))}
        </tbody>
      </table>
    </section>
  );
}

export default function PlanningConstraintsPanel({
  lat,
  lon,
  radiusM = 500,
  onLayerToggle = () => {},
  initialEnabledSlugs = [],
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);
  const [enabledSlugs, setEnabledSlugs] = useState(() => new Set(initialEnabledSlugs));

  const fetchHits = useCallback(async () => {
    if (lat == null || lon == null) return;
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(
        `/api/planning-data/constraints?lat=${lat}&lon=${lon}&radius_m=${radiusM}`
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const json = await r.json();
      setData(json);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [lat, lon, radiusM]);

  useEffect(() => { fetchHits(); }, [fetchHits]);

  const handleToggle = useCallback((slug, enabled) => {
    setEnabledSlugs(prev => {
      const next = new Set(prev);
      if (enabled) next.add(slug); else next.delete(slug);
      return next;
    });
    onLayerToggle(slug, enabled);
  }, [onLayerToggle]);

  const grouped = useMemo(() => {
    if (!data?.by_severity) return null;
    return SEVERITY_ORDER.map(sev => ({
      sev,
      hits: data.by_severity[sev] || [],
    }));
  }, [data]);

  const totalCount = data?.count ?? 0;
  const critCount = data?.by_severity?.CRITICAL?.length ?? 0;
  const highCount = data?.by_severity?.HIGH?.length ?? 0;

  let bannerVerdict = "GO";
  let bannerColor = "#16A34A";
  if (critCount > 0) { bannerVerdict = "NO-GO"; bannerColor = "#DC2626"; }
  else if (highCount > 0) { bannerVerdict = "CAUTION"; bannerColor = "#E8A012"; }

  return (
    <div className="pcp-panel">
      <header className="pcp-head">
        <div>
          <div className="pcp-title">Planning Constraints</div>
          <div className="pcp-sub">
            planning.data.gov.uk · {radiusM} m radius · {totalCount} designation{totalCount === 1 ? "" : "s"}
          </div>
        </div>
        <div
          className="pcp-banner"
          style={{ background: bannerColor }}
          title={`${critCount} CRITICAL · ${highCount} HIGH`}
        >
          {bannerVerdict}
        </div>
      </header>

      {loading && (
        <div className="pcp-state">Loading planning designations…</div>
      )}
      {error && (
        <div className="pcp-state pcp-state-err">
          Couldn't load planning designations: {error}
          <button className="pcp-retry" onClick={fetchHits}>Retry</button>
        </div>
      )}
      {!loading && !error && grouped && totalCount === 0 && (
        <div className="pcp-state">
          No planning.data.gov.uk designations within {radiusM} m of this site.
        </div>
      )}
      {!loading && !error && grouped && totalCount > 0 && (
        <div className="pcp-body">
          {grouped.map(g => (
            <GroupSection
              key={g.sev}
              severity={g.sev}
              hits={g.hits}
              datasetToggle={handleToggle}
              enabledSlugs={enabledSlugs}
            />
          ))}
        </div>
      )}

      <footer className="pcp-footer">
        {data?.attribution || "© Crown copyright · Open Government Licence v3.0"}
      </footer>

      <style>{`
        .pcp-panel{display:flex;flex-direction:column;gap:12px;background:#fff;border-radius:10px;padding:16px;box-shadow:0 1px 3px rgba(15,19,24,.04);font-family:'DM Sans',system-ui,sans-serif;color:#0F1318}
        .pcp-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
        .pcp-title{font-size:14px;font-weight:700;letter-spacing:.2px}
        .pcp-sub{font-size:11px;color:#4A5057;margin-top:2px}
        .pcp-banner{padding:4px 12px;border-radius:999px;color:#fff;font-weight:700;font-size:11px;letter-spacing:.4px;text-transform:uppercase}
        .pcp-state{padding:18px;text-align:center;color:#4A5057;font-size:12px;border:1px dashed #E5E7EB;border-radius:8px}
        .pcp-state-err{color:#7F1D1D}
        .pcp-retry{margin-left:8px;padding:2px 8px;border-radius:4px;background:#fff;border:1px solid #DC2626;color:#DC2626;font-size:11px;cursor:pointer}
        .pcp-body{display:flex;flex-direction:column;gap:10px}
        .pcp-group{padding:10px 12px;border-radius:6px}
        .pcp-group-head{display:flex;align-items:center;gap:8px;font-size:11px;text-transform:uppercase;letter-spacing:.6px}
        .pcp-group-count{font-weight:500;opacity:.75}
        .pcp-toggles{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
        .pcp-toggle{font-family:inherit;font-size:10px;padding:3px 8px;background:rgba(255,255,255,.6);border:1px solid rgba(15,19,24,.15);border-radius:999px;cursor:pointer;color:#0F1318}
        .pcp-toggle-on{background:#0F1318;color:#fff;border-color:#0F1318}
        .pcp-table{width:100%;border-collapse:collapse;font-size:12px;background:#fff;border-radius:4px;overflow:hidden}
        .pcp-table thead th{text-align:left;font-size:10px;color:#4A5057;font-weight:600;text-transform:uppercase;letter-spacing:.4px;padding:6px 8px;border-bottom:1px solid #E5E7EB}
        .pcp-row td{padding:6px 8px;vertical-align:top;border-bottom:1px solid #F3F4F6}
        .pcp-row:last-child td{border-bottom:none}
        .pcp-cell-sev{width:70px}
        .pcp-cell-dist{width:80px;font-variant-numeric:tabular-nums;color:#4A5057}
        .pcp-cell-link{width:110px;font-size:11px}
        .pcp-cell-link a{color:#2563EB;text-decoration:none}
        .pcp-cell-link a:hover{text-decoration:underline}
        .pcp-name{font-weight:600}
        .pcp-dataset{font-size:10px;color:#4A5057;margin-top:1px}
        .pcp-chip{display:inline-block;padding:2px 6px;border-radius:999px;font-size:9px;font-weight:700;letter-spacing:.4px}
        .pcp-footer{font-size:10px;color:#6B7280;text-align:right;padding-top:6px;border-top:1px solid #F3F4F6}
      `}</style>
    </div>
  );
}
