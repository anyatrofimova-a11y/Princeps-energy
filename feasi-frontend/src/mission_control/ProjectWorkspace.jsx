import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import "./project-workspace.css";
import PlanningConstraintsPanel from "../components/PlanningConstraintsPanel.jsx";
// OpenInfraMap power overlay (BSD-3-Clause code, CC-BY 4.0 style — see footer).
import { attachOimOverlay, OIM_ATTRIBUTION } from "../lib/oimOverlay.js";

// ProjectWorkspace — landing surface after a user clicks a project tile in
// Mission Control. Layout:
//   left rail  — project metadata, verdict pill, blocker, grid bar
//   centre     — Mapbox map centred on lat/lon with a marker
//   right rail — "Run agentic analysis" cascade + chat TODO
//   bottom     — live headroom / queue / timeline strip
//
// Real endpoint: GET /api/v1/projects/:id (returns lat, lon, metadata jsonb).
// The agentic cascade is faked (4s) until the live agent endpoint lands.

const VERDICT_STYLE = {
  GO:      { bg: "#16A34A", fg: "#FFFFFF", label: "GO" },
  CAUTION: { bg: "#E8A012", fg: "#0F1318", label: "CAUTION" },
  "NO-GO": { bg: "#DC2626", fg: "#FFFFFF", label: "NO-GO" },
  NOGO:    { bg: "#DC2626", fg: "#FFFFFF", label: "NO-GO" },
};

const TECH_LABEL = {
  bess: "Battery Energy Storage",
  solar: "Solar PV",
  wind: "Onshore Wind",
  dc: "Data Centre",
  nuclear: "Nuclear",
  hybrid: "Hybrid Renewable",
  gas: "Gas Peaker",
};

function fmtMw(mw) {
  if (mw == null) return "—";
  if (mw >= 1000) return `${(mw / 1000).toFixed(1)} GW`;
  return `${Math.round(mw)} MW`;
}

function fmtGbp(v) {
  if (v == null) return "—";
  if (v >= 1_000_000) return `£${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1000) return `£${(v / 1000).toFixed(0)}k`;
  return `£${v}`;
}

function parseMeta(raw) {
  if (!raw) return {};
  if (typeof raw === "object") return raw;
  try { return JSON.parse(raw); } catch { return {}; }
}

// 4-step cascade. Each step has a label, sub-detail, and a result line that
// appears once the step completes. The whole thing runs in ~4 seconds.
const ANALYSIS_STEPS = [
  {
    id: "tec",
    label: "Querying NESO TEC register",
    sub: "checking queue position and reserved capacity",
    duration: 900,
    resultFor: (project, meta) => {
      const dno = meta?.dno || "regional DNO";
      const queue = meta?.queue_depth ?? "—";
      return `${dno} queue depth ${queue} · TEC last-published ${new Date().getFullYear()}-Q2`;
    },
  },
  {
    id: "pandapower",
    label: "Running pandapower load flow",
    sub: "Newton-Raphson N-1 contingency against POC substation",
    duration: 1100,
    resultFor: (project, meta) => {
      const hr = meta?.firm_headroom_mw ?? project.capacity_mw ?? 0;
      const poc = meta?.poc || "primary 33kV";
      return `firm headroom ${Number(hr).toFixed(0)} MW at ${poc} · voltage envelope within ±6%`;
    },
  },
  {
    id: "repd",
    label: "Cross-referencing REPD precedent",
    sub: "matching planning outcomes for similar capacity within 10km",
    duration: 800,
    resultFor: (project, meta) => {
      const tech = (project.technology || "bess").toLowerCase();
      const approvals = tech === "solar" ? 7 : tech === "bess" ? 11 : 4;
      return `${approvals} comparable approvals within 10 km · median consent 14 months`;
    },
  },
  {
    id: "verdict",
    label: "Composing verdict",
    sub: "weighting grid, planning, commercial, environmental signals",
    duration: 1200,
    resultFor: (project, meta) => {
      const cost = meta?.cost_p50_gbp ? fmtGbp(meta.cost_p50_gbp) : "—";
      const months = meta?.timeline_months ?? 18;
      return `connection cost P50 ${cost} · time-to-energisation ~${months} months`;
    },
  },
];

function VerdictPill({ verdict, large }) {
  const v = VERDICT_STYLE[(verdict || "").toUpperCase()] ||
    { bg: "#8A9099", fg: "#FFFFFF", label: verdict || "—" };
  return (
    <span
      className={"pwx-verdict" + (large ? " pwx-verdict-lg" : "")}
      style={{ background: v.bg, color: v.fg }}
    >
      {v.label}
    </span>
  );
}

function MapPane({ project, mapRef }) {
  const containerRef = useRef(null);
  const oimRef = useRef(null);
  // OIM grid layer overlay (default ON per task #16).
  const [oimEnabled, setOimEnabled] = useState(true);

  useEffect(() => {
    mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN || "";
    if (!containerRef.current || mapRef.current) return;
    if (!mapboxgl.accessToken) return;

    const lon = Number(project.lon);
    const lat = Number(project.lat);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/light-v11",
      center: [lon, lat],
      zoom: 12.5,
      pitch: 30,
      bearing: 0,
      attributionControl: false,
    });
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new mapboxgl.AttributionControl({ compact: true, customAttribution: OIM_ATTRIBUTION }), "bottom-right");
    mapRef.current = map;

    // Attach OIM power overlay once the basemap is ready (default ON).
    map.on("load", () => {
      try {
        if (oimEnabled) {
          oimRef.current = attachOimOverlay(map);
        }
      } catch (e) {
        // eslint-disable-next-line no-console
        console.warn("[ProjectWorkspace] OIM overlay attach failed:", e);
      }
    });

    // Color the marker by verdict
    const verdict = (project.verdict || "").toUpperCase();
    const color = (VERDICT_STYLE[verdict] || {}).bg || "#F5B731";
    const el = document.createElement("div");
    el.style.cssText = `
      width: 22px; height: 22px; border-radius: 50%;
      background: ${color}; border: 3px solid #FFFFFF;
      box-shadow: 0 2px 12px rgba(15,19,24,0.35);
      cursor: pointer;
    `;

    const popup = new mapboxgl.Popup({ offset: 20, closeButton: false }).setHTML(
      `<div style="font-family: 'DM Sans', sans-serif; padding: 4px 2px;">
         <div style="font-size: 12px; font-weight: 600; color: #0F1318;">${project.name}</div>
         <div style="font-size: 10px; color: #4A5057; margin-top: 2px;">
           ${fmtMw(project.capacity_mw)} · ${TECH_LABEL[(project.technology || "").toLowerCase()] || project.technology}
         </div>
       </div>`
    );

    new mapboxgl.Marker({ element: el })
      .setLngLat([lon, lat])
      .setPopup(popup)
      .addTo(map);

    map.once("load", () => popup.addTo(map).setLngLat([lon, lat]));

    return () => {
      try { oimRef.current?.detach?.(); } catch {}
      oimRef.current = null;
      try { map.remove(); } catch {}
      mapRef.current = null;
    };
  }, [project.project_id]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Toggle the OIM overlay on/off without rebuilding the map.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    if (oimEnabled && !oimRef.current) {
      try { oimRef.current = attachOimOverlay(map); } catch {}
    } else if (!oimEnabled && oimRef.current) {
      try { oimRef.current.detach(); } catch {}
      oimRef.current = null;
    }
  }, [oimEnabled]);

  if (!import.meta.env.VITE_MAPBOX_TOKEN) {
    return (
      <div className="pwx-map-empty">
        Set <code>VITE_MAPBOX_TOKEN</code> in <code>feasi-frontend/.env</code> to render the site map.
      </div>
    );
  }
  return (
    <div className="pwx-map-wrap" style={{ position: "relative", width: "100%", height: "100%" }}>
      <div ref={containerRef} className="pwx-map" style={{ width: "100%", height: "100%" }} />
      {/* OIM grid layer toggle (task #16). */}
      <button
        type="button"
        onClick={() => setOimEnabled((v) => !v)}
        title="Toggle OpenInfraMap grid overlay"
        style={{
          position: "absolute", top: 12, left: 12, zIndex: 5,
          padding: "6px 10px", borderRadius: 6,
          background: oimEnabled ? "#D4A018" : "rgba(255,255,255,0.92)",
          color: oimEnabled ? "#0F1318" : "#0F1318",
          border: "1px solid rgba(15,19,24,0.18)",
          fontFamily: "'DM Sans', sans-serif", fontSize: 11, fontWeight: 600,
          letterSpacing: "0.03em", cursor: "pointer",
          boxShadow: "0 2px 8px rgba(15,19,24,0.16)",
        }}
      >
        Grid layer {oimEnabled ? "ON" : "OFF"}
      </button>
      {/* Footer attribution (CC-BY 4.0 mandatory). */}
      <div
        style={{
          position: "absolute", bottom: 4, left: 8, zIndex: 4,
          fontSize: 9, lineHeight: 1.3, color: "#4A5057",
          fontFamily: "'DM Sans', sans-serif",
          background: "rgba(255,255,255,0.78)", padding: "2px 6px", borderRadius: 4,
          pointerEvents: "auto",
        }}
      >
        © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer"
             style={{ color: "#8a6c1a", textDecoration: "none" }}>OpenStreetMap contributors</a>
        {" · "}
        OpenInfraMap style (<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener noreferrer"
             style={{ color: "#8a6c1a", textDecoration: "none" }}>CC-BY 4.0</a>)
      </div>
    </div>
  );
}

function AnalysisCascade({ project, meta }) {
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState([]);
  const [finishedAt, setFinishedAt] = useState(null);

  const start = useCallback(() => {
    if (running) return;
    setRunning(true);
    setFinishedAt(null);
    setSteps(ANALYSIS_STEPS.map((s) => ({ ...s, status: "pending", result: null })));

    let cumulative = 0;
    ANALYSIS_STEPS.forEach((step, idx) => {
      // mark step running at start of its slot
      setTimeout(() => {
        setSteps((curr) => curr.map((s, i) => i === idx ? { ...s, status: "running" } : s));
      }, cumulative);
      cumulative += step.duration;
      // complete it at the end of the slot
      setTimeout(() => {
        const result = step.resultFor(project, meta);
        setSteps((curr) => curr.map((s, i) => i === idx ? { ...s, status: "done", result } : s));
        if (idx === ANALYSIS_STEPS.length - 1) {
          setRunning(false);
          setFinishedAt(new Date());
        }
      }, cumulative);
    });
  }, [project, meta, running]);

  return (
    <div className="pwx-cascade">
      <div className="pwx-cascade-head">
        <div>
          <div className="pwx-cascade-title">Agentic analysis</div>
          <div className="pwx-cascade-sub">
            {running ? "Running…" :
             finishedAt ? `Completed ${finishedAt.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}` :
             "Live grid + planning + commercial pass · 4 steps · ~4s"}
          </div>
        </div>
        <button
          className="pwx-cascade-btn"
          disabled={running}
          onClick={start}
        >
          {running ? "Analysing…" : steps.length ? "Re-run" : "Run agentic analysis"}
        </button>
      </div>
      <div className="pwx-cascade-body">
        {steps.length === 0 ? (
          <div className="pwx-cascade-empty">
            Press <strong>Run agentic analysis</strong> to dispatch the GRID, PLANNING and COMMERCIAL pods.
          </div>
        ) : steps.map((s) => (
          <div key={s.id} className={`pwx-step pwx-step-${s.status}`}>
            <span className="pwx-step-glyph">
              {s.status === "done" ? "✓" : s.status === "running" ? <span className="pwx-spin" /> : "○"}
            </span>
            <div className="pwx-step-body">
              <div className="pwx-step-label">{s.label}</div>
              <div className="pwx-step-sub">{s.sub}</div>
              {s.result && <div className="pwx-step-result">{s.result}</div>}
            </div>
          </div>
        ))}
      </div>
      {/* Chat panel placeholder — wired by task #10. */}
      <div className="pwx-chat-stub">
        <span>Conversational analysis</span>
        <em>chat panel lands with task #10</em>
      </div>
    </div>
  );
}

// Mapbox layer-id for the planning.data.gov.uk vector tile layer.
const PCP_SRC_ID   = "princeps-planning-src";
const PCP_LYR_FILL = "princeps-planning-fill";
const PCP_LYR_LINE = "princeps-planning-line";

// Severity colour ramp keyed off slug — matches PlanningConstraintsPanel.
const PCP_SEV_BY_SLUG = {
  "site-of-special-scientific-interest": "CRITICAL",
  "ancient-woodland": "CRITICAL",
  "special-area-of-conservation": "CRITICAL",
  "special-protection-area": "CRITICAL",
  "ramsar": "CRITICAL",
  "scheduled-monument": "CRITICAL",
  "national-park": "CRITICAL",
  "national-nature-reserve": "CRITICAL",
  "flood-risk-zone": "HIGH",
  "green-belt": "HIGH",
  "area-of-outstanding-natural-beauty": "HIGH",
  "agricultural-land-classification": "HIGH",
  "listed-building": "HIGH",
  "listed-building-outline": "HIGH",
  "conservation-area": "HIGH",
  "nutrient-neutrality-catchment": "HIGH",
  "tree-preservation-zone": "HIGH",
  "article-4-direction-area": "HIGH",
  "local-nature-reserve": "MEDIUM",
  "brownfield-land": "MEDIUM",
  "local-planning-authority": "MEDIUM",
};

const PCP_SEV_COLOR = {
  CRITICAL: "#DC2626",
  HIGH:     "#E8A012",
  MEDIUM:   "#0284C7",
};

function syncPlanningLayer(map, enabledSlugs) {
  if (!map || !map.isStyleLoaded()) return;
  const slugs = Array.from(enabledSlugs || []);
  if (slugs.length === 0) {
    if (map.getLayer(PCP_LYR_LINE)) map.removeLayer(PCP_LYR_LINE);
    if (map.getLayer(PCP_LYR_FILL)) map.removeLayer(PCP_LYR_FILL);
    if (map.getSource(PCP_SRC_ID)) map.removeSource(PCP_SRC_ID);
    return;
  }
  const q = slugs.map(s => `datasets=${encodeURIComponent(s)}`).join("&");
  const tileUrl = `/api/planning-data/designations.mvt?z={z}&x={x}&y={y}&${q}`;

  if (!map.getSource(PCP_SRC_ID)) {
    map.addSource(PCP_SRC_ID, {
      type: "vector",
      tiles: [tileUrl],
      minzoom: 6, maxzoom: 18,
      attribution: "© Crown copyright · Open Government Licence v3.0",
    });
  } else {
    // Source.tiles update — refresh by removing/re-adding when the slug list changes.
    map.removeSource(PCP_SRC_ID);
    if (map.getLayer(PCP_LYR_LINE)) map.removeLayer(PCP_LYR_LINE);
    if (map.getLayer(PCP_LYR_FILL)) map.removeLayer(PCP_LYR_FILL);
    map.addSource(PCP_SRC_ID, {
      type: "vector",
      tiles: [tileUrl],
      minzoom: 6, maxzoom: 18,
      attribution: "© Crown copyright · Open Government Licence v3.0",
    });
  }

  const colorExpr = ["match", ["get", "dataset"]];
  Object.entries(PCP_SEV_BY_SLUG).forEach(([slug, sev]) => {
    colorExpr.push(slug, PCP_SEV_COLOR[sev]);
  });
  colorExpr.push("#6B7280");

  if (!map.getLayer(PCP_LYR_FILL)) {
    map.addLayer({
      id: PCP_LYR_FILL,
      type: "fill",
      source: PCP_SRC_ID,
      "source-layer": "planning_designations",
      paint: {
        "fill-color": colorExpr,
        "fill-opacity": 0.25,
        "fill-outline-color": colorExpr,
      },
    });
  }
  if (!map.getLayer(PCP_LYR_LINE)) {
    map.addLayer({
      id: PCP_LYR_LINE,
      type: "line",
      source: PCP_SRC_ID,
      "source-layer": "planning_designations",
      paint: {
        "line-color": colorExpr,
        "line-width": 1.2,
        "line-opacity": 0.85,
      },
    });
  }
}

export default function ProjectWorkspace() {
  const { id } = useParams();
  const navigate = useNavigate();
  const mapRef = useRef(null);
  const [project, setProject] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [enabledSlugs, setEnabledSlugs] = useState(() => new Set());

  // Re-sync the planning layer whenever the enabled slug set or the map changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (map.isStyleLoaded()) {
      syncPlanningLayer(map, enabledSlugs);
    } else {
      const onLoad = () => syncPlanningLayer(map, enabledSlugs);
      map.once("load", onLoad);
      return () => { try { map.off("load", onLoad); } catch {} };
    }
  }, [enabledSlugs, project?.project_id]);

  const handleLayerToggle = useCallback((slug, enabled) => {
    setEnabledSlugs(prev => {
      const next = new Set(prev);
      if (enabled) next.add(slug); else next.delete(slug);
      return next;
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetch(`/api/v1/projects/${encodeURIComponent(id)}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => { if (!cancelled) { setProject(data); setLoading(false); } })
      .catch((e) => { if (!cancelled) { setError(String(e.message || e)); setLoading(false); } });
    return () => { cancelled = true; };
  }, [id]);

  const meta = useMemo(() => parseMeta(project?.metadata), [project]);

  if (loading) {
    return <div className="pwx-page pwx-page-state">Loading project…</div>;
  }
  if (error || !project) {
    return (
      <div className="pwx-page pwx-page-state">
        <div className="pwx-error">Couldn't load project {id}: {error || "not found"}</div>
        <button className="pwx-back" onClick={() => navigate("/v2")}>← Mission Control</button>
      </div>
    );
  }

  const techLabel = TECH_LABEL[(project.technology || "").toLowerCase()] || project.technology || "—";

  return (
    <div className="pwx-page">
      <div className="pwx-topbar">
        <button className="pwx-back" onClick={() => navigate("/v2")}>← Mission Control</button>
        <div className="pwx-topbar-title">
          <span className="pwx-topbar-name">{project.name}</span>
          <span className="pwx-topbar-meta">
            {fmtMw(project.capacity_mw)} · {techLabel} · stage <strong>{project.stage || "discover"}</strong>
          </span>
        </div>
        <VerdictPill verdict={project.verdict} large />
      </div>

      <div className="pwx-body">
        <aside className="pwx-left">
          <section className="pwx-card">
            <div className="pwx-card-title">Site</div>
            <dl className="pwx-dl">
              <dt>Coordinates</dt>
              <dd>{project.lat?.toFixed(4)}, {project.lon?.toFixed(4)}</dd>
              <dt>Capacity</dt>
              <dd>{fmtMw(project.capacity_mw)}</dd>
              <dt>Technology</dt>
              <dd>{techLabel}</dd>
              <dt>Stage</dt>
              <dd>{project.stage || "discover"}</dd>
            </dl>
          </section>

          {project.blocker && (
            <section className="pwx-card pwx-card-blocker">
              <div className="pwx-card-title">Blocker</div>
              <div className="pwx-blocker-text">{project.blocker}</div>
            </section>
          )}

          <section className="pwx-card">
            <div className="pwx-card-title">Grid connection</div>
            <dl className="pwx-dl">
              <dt>POC</dt>
              <dd>{meta.poc || "—"}</dd>
              <dt>DNO</dt>
              <dd>{meta.dno || "—"}</dd>
              <dt>Firm headroom</dt>
              <dd>{meta.firm_headroom_mw != null ? `${meta.firm_headroom_mw} MW` : "—"}</dd>
              <dt>Queue depth</dt>
              <dd>{meta.queue_depth ?? "—"}</dd>
              <dt>Cost (P50)</dt>
              <dd>{fmtGbp(meta.cost_p50_gbp)}</dd>
              <dt>Timeline</dt>
              <dd>{meta.timeline_months != null ? `${meta.timeline_months} months` : "—"}</dd>
            </dl>
          </section>
        </aside>

        <main className="pwx-centre">
          <MapPane project={project} mapRef={mapRef} />
        </main>

        <aside className="pwx-right">
          <AnalysisCascade project={project} meta={meta} />
          {Number.isFinite(Number(project.lat)) && Number.isFinite(Number(project.lon)) && (
            <PlanningConstraintsPanel
              lat={Number(project.lat)}
              lon={Number(project.lon)}
              radiusM={500}
              onLayerToggle={handleLayerToggle}
            />
          )}
        </aside>
      </div>

      <footer className="pwx-bottom">
        <div className="pwx-bar">
          <span className="pwx-bar-label">Grid headroom</span>
          <div className="pwx-bar-track">
            <div
              className="pwx-bar-fill pwx-bar-headroom"
              style={{ width: `${Math.min(100, ((meta.firm_headroom_mw || 0) / Math.max(1, project.capacity_mw * 2)) * 100)}%` }}
            />
          </div>
          <span className="pwx-bar-value">{meta.firm_headroom_mw != null ? `${meta.firm_headroom_mw} MW` : "—"}</span>
        </div>
        <div className="pwx-bar">
          <span className="pwx-bar-label">Queue depth</span>
          <div className="pwx-bar-track">
            <div
              className="pwx-bar-fill pwx-bar-queue"
              style={{ width: `${Math.min(100, ((meta.queue_depth || 0) / 50) * 100)}%` }}
            />
          </div>
          <span className="pwx-bar-value">{meta.queue_depth ?? "—"}</span>
        </div>
        <div className="pwx-bar">
          <span className="pwx-bar-label">Timeline</span>
          <div className="pwx-bar-track">
            <div
              className="pwx-bar-fill pwx-bar-timeline"
              style={{ width: `${Math.min(100, ((meta.timeline_months || 0) / 48) * 100)}%` }}
            />
          </div>
          <span className="pwx-bar-value">{meta.timeline_months != null ? `${meta.timeline_months} mo` : "—"}</span>
        </div>
      </footer>
    </div>
  );
}
