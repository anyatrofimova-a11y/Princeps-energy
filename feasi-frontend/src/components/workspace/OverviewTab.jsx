import React, { useEffect, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import ProjectKpiStrip from "../project/ProjectKpiStrip.jsx";
import SiteMemoCard from "../project/SiteMemoCard.jsx";

/**
 * SiteMapPin — tiny satellite map that drops a single gold pin on the
 * project's lat/lon. No SitePicker, no layer stack, no network overlays —
 * just "here is the project". Real estate-style mini-map.
 */
function SiteMapPin({ lat, lon, name }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current || lat == null || lon == null) return;
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/satellite-streets-v12",
      center: [lon, lat],
      zoom: 13.5,
      attributionControl: false,
      interactive: true,
    });
    mapRef.current = map;
    const el = document.createElement("div");
    el.style.cssText = `
      width: 28px; height: 28px; border-radius: 50% 50% 50% 0;
      background: var(--gold, #F5B731); border: 3px solid #fff;
      transform: rotate(-45deg); box-shadow: 0 4px 10px rgba(0,0,0,0.3);
      cursor: pointer;
    `;
    new mapboxgl.Marker({ element: el, anchor: "bottom" })
      .setLngLat([lon, lat])
      .setPopup(new mapboxgl.Popup({ offset: 18, closeButton: false })
        .setHTML(`<div style="font-family:'DM Sans',sans-serif;font-size:12px;font-weight:600;color:#0F1318">${name || "Project site"}</div>
                  <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#6B7280;margin-top:2px">${lat.toFixed(4)}°, ${lon.toFixed(4)}°</div>`))
      .addTo(map);
    return () => { try { map.remove(); } catch {} mapRef.current = null; };
  }, [lat, lon, name]);

  if (lat == null || lon == null) {
    return <div className="ov-map-placeholder">No coordinates for this site.</div>;
  }
  return <div ref={containerRef} className="ov-map-live" />;
}

const STAGES = [
  { key: "prospect",      label: "Prospect" },
  { key: "screened",      label: "Screened" },
  { key: "grid_applied",  label: "Grid app" },
  { key: "grid_offer",    label: "Grid offer" },
  { key: "planning",      label: "Planning" },
  { key: "fid",           label: "FID" },
  { key: "construction",  label: "Build" },
  { key: "energised",     label: "Energised" },
];

const MOCK_FILINGS = [
  { name: "G99 application (draft)",     stage: "grid_applied", status: "draft"    },
  { name: "Planning statement (outline)", stage: "planning",     status: "outline"  },
  { name: "EIA screening opinion",        stage: "screened",     status: "filed"    },
  { name: "Ecology survey (commissioned)",stage: "planning",     status: "pending"  },
  { name: "FRA — Flood risk assessment",  stage: "planning",     status: "drafting" },
];

function StagePipeline({ currentStage }) {
  const idx = Math.max(0, STAGES.findIndex((s) => s.key === currentStage));
  return (
    <div className="ov-pipeline">
      {STAGES.map((s, i) => {
        const state = i < idx ? "done" : i === idx ? "active" : "future";
        return (
          <React.Fragment key={s.key}>
            <div className={"ov-pstage ov-pstage-" + state}>
              <div className="ov-pstage-dot">{i + 1}</div>
              <div className="ov-pstage-lbl">{s.label}</div>
            </div>
            {i < STAGES.length - 1 && (
              <div className={"ov-pline " + (i < idx ? "ov-pline-done" : "")} />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

const MOCK_BLOCKERS = [
  { severity: "warn", text: "Grid headroom marginal at summer peak — needs reinforcement", age: "2d ago" },
  { severity: "warn", text: "Local planning authority requires ecology survey", age: "5d ago" },
  { severity: "info", text: "Noise assessment pending for DC cooling plant", age: "1w ago" },
];

const MOCK_ACTIVITY = [
  { icon: "⚡", text: "Grid study completed — Tier 2 power flow passed", ts: "3h ago" },
  { icon: "◈", text: "DNO G99 application drafted", ts: "1d ago" },
  { icon: "★", text: "New candidate site added (Rainham)", ts: "2d ago" },
  { icon: "⚙", text: "Planning ML score updated: 71 → 74", ts: "4d ago" },
  { icon: "✎", text: "Financial model recomputed — IRR 11.8%", ts: "6d ago" },
];

const MOCK_NEXT = [
  "Submit G99 connection form to DNO",
  "Commission ecology + noise surveys",
  "Schedule LPA pre-application meeting",
];

/**
 * GridConnectionCard — the developer's DNO-consultation board.
 *
 * Surfaces everything a UK energy developer is asked about in a DNO
 * capacity conversation: POC, TEC/MIC, queue position, G99/G100 route,
 * offer + acceptance + energisation dates, ANM constraint exposure,
 * reinforcement costs, and the financial ceiling the commercial team
 * needs (LCOE, IRR, lifetime revenue).
 *
 * Metrics are populated from project.metadata where available and fall
 * through to sensible workload-defaults. Replace the fallbacks once the
 * grid_queue + finance + connection_strategy routers are wired in.
 */
function GridConnectionCard({ project, isBess, isDC, onViewTab }) {
  const m = project?.metadata || {};
  const cap = Number(project?.capacity_mw) || 0;
  const dnoArea = m.dno_area || _inferDno(project);
  const pocName = m.poc_substation || _stubPoc(project);
  const pocVolt = m.poc_voltage_kv || (cap >= 50 ? 132 : cap >= 20 ? 33 : 11);
  const gridCode = cap > 50 ? "G100" : "G99";
  const queueDepth = m.queue_depth_mw ?? Math.round(cap * (isDC ? 1.8 : 1.2));
  const queueAhead = m.queue_ahead_of_us ?? (isBess ? 3 : 7);
  const tec = m.tec_mw ?? cap;
  const offered = m.offered_mw ?? (cap > 50 ? Math.round(cap * 0.85) : cap);
  const offerDate = m.offer_date || "awaited";
  const acceptanceDays = m.acceptance_deadline_days ?? 60;
  const energisationDate = m.scheduled_energisation || (isDC ? "Q3 2028" : "Q2 2027");
  const anmHoursYr = m.anm_curtail_hours_yr ?? (cap > 40 ? 320 : 120);
  const curtailPct = m.curtail_pct ?? (cap > 40 ? 4.6 : 2.1);
  const reinforcement = m.reinforcement_gbp_m ?? (cap > (m.headroom_mw ?? 50) ? 1.8 : 0);
  const firmness = m.firmness || (reinforcement > 0 ? "Non-firm" : "Firm");
  const lcoe = m.lcoe_gbp_per_mwh ?? (isBess ? 82 : isDC ? 72 : 55);
  const irr = m.irr_pct ?? (isBess ? 11.8 : isDC ? 14.2 : 8.4);
  const capexPerMw = m.capex_gbp_per_mw ?? (isBess ? 660_000 : isDC ? 9_500_000 : 900_000);
  const annualRev = m.annual_revenue_gbp_m ?? (isBess ? cap * 0.075 : isDC ? cap * 3.8 : cap * 11 * 87.6 * 55 / 1e6);
  const lifeRev = annualRev * (isDC ? 12 : 15);

  const risk = reinforcement > 2 ? "High" : queueAhead > 5 ? "Medium" : "Low";
  const riskTint = risk === "High" ? "var(--cds-support-error)"
                  : risk === "Medium" ? "var(--cds-support-warning)"
                  : "var(--cds-support-success)";

  // 15-year revenue curve — flat with degradation
  const degradation = isBess ? 0.985 : isDC ? 0.995 : 0.995;
  const revSeries = Array.from({ length: 15 }, (_, i) => annualRev * Math.pow(degradation, i));

  return (
    <div className="ov-card ov-gc-card">
      <div className="ov-card-header">
        <span>Grid connection &amp; energisation</span>
        <button className="ov-link" onClick={() => onViewTab("assess")}>Open Assess →</button>
      </div>

      {/* DNO + POC + grid code + firmness */}
      <div className="ov-gc-header-row">
        <div className="ov-gc-dno">
          <div className="ov-gc-dno-lbl">DNO</div>
          <div className="ov-gc-dno-val">{dnoArea}</div>
        </div>
        <div className="ov-gc-poc">
          <div className="ov-gc-poc-name">{pocName}</div>
          <div className="ov-gc-poc-meta">{pocVolt} kV · {gridCode} · {firmness}</div>
        </div>
        <div className="ov-gc-risk" style={{ color: riskTint }}>
          <div className="ov-gc-risk-lbl">Connection risk</div>
          <div className="ov-gc-risk-val">{risk}</div>
        </div>
      </div>

      {/* Key connection metrics */}
      <div className="ov-gc-metrics">
        <GcMetric label="TEC / contracted" value={`${tec} MW`} sub={offered < tec ? `Offer: ${offered} MW` : "Full award"} />
        <GcMetric label="Queue ahead" value={`${queueAhead}`} sub={`${queueDepth} MW stacked`} />
        <GcMetric label="ANM / curtailment" value={`${curtailPct.toFixed(1)}%`} sub={`${anmHoursYr} h/yr expected`} />
        <GcMetric label="Reinforcement" value={reinforcement > 0 ? `£${reinforcement.toFixed(1)}M` : "None"}
                  sub={reinforcement > 0 ? "Deep works" : "P&G only"}
                  tint={reinforcement > 0 ? "var(--cds-support-warning)" : null} />
      </div>

      {/* Key dates — offer → acceptance → energisation */}
      <div className="ov-gc-dates">
        <DateStep label="G99/G100 offer" value={offerDate} state={offerDate === "awaited" ? "pending" : "done"} />
        <div className="ov-gc-dates-arrow">→</div>
        <DateStep label="Acceptance due" value={`${acceptanceDays}d window`} state="pending" />
        <div className="ov-gc-dates-arrow">→</div>
        <DateStep label="Scheduled energisation" value={energisationDate} state="future" />
      </div>

      {/* Financials */}
      <div className="ov-gc-finance">
        <GcMetric label="LCOE" value={`£${lcoe}`} sub="/MWh" dense />
        <GcMetric label="IRR (project)" value={`${irr.toFixed(1)}%`} dense />
        <GcMetric label="CAPEX" value={`£${(capexPerMw / 1e6).toFixed(2)}M`} sub="/MW" dense />
        <GcMetric label="Life revenue" value={`£${lifeRev.toFixed(1)}M`} sub={`${isDC ? 12 : 15}y`} dense />
      </div>

      {/* Revenue curve */}
      <div className="ov-gc-chart">
        <div className="ov-gc-chart-lbl">Annual revenue £M (degradation-adjusted)</div>
        <RevenueCurve series={revSeries} />
      </div>
    </div>
  );
}

function GcMetric({ label, value, sub, tint, dense }) {
  return (
    <div className={"ov-gc-m" + (dense ? " ov-gc-m-dense" : "")}>
      <div className="ov-gc-m-lbl">{label}</div>
      <div className="ov-gc-m-val" style={tint ? { color: tint } : undefined}>{value}</div>
      {sub && <div className="ov-gc-m-sub">{sub}</div>}
    </div>
  );
}

function DateStep({ label, value, state }) {
  return (
    <div className={"ov-gc-d ov-gc-d-" + state}>
      <div className="ov-gc-d-lbl">{label}</div>
      <div className="ov-gc-d-val">{value}</div>
    </div>
  );
}

function RevenueCurve({ series, color = "var(--gold)" }) {
  const w = 420, h = 72, pad = { t: 6, r: 4, b: 16, l: 4 };
  const max = Math.max(...series, 0.01);
  const step = (w - pad.l - pad.r) / (series.length - 1);
  const y = (v) => pad.t + (h - pad.t - pad.b) * (1 - v / max);
  const path = series.map((v, i) => `${i === 0 ? "M" : "L"}${pad.l + i * step},${y(v).toFixed(1)}`).join(" ");
  const area = `${path} L${pad.l + (series.length - 1) * step},${h - pad.b} L${pad.l},${h - pad.b} Z`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="ov-gc-spark" preserveAspectRatio="none">
      <path d={area} fill="rgba(var(--accent-rgb), 0.18)" />
      <path d={path} stroke={color} strokeWidth="2" fill="none" strokeLinejoin="round" strokeLinecap="round" />
      <text x={pad.l} y={h - 2} fontSize="9" fill="#9CA3AF" fontFamily="monospace">Y1</text>
      <text x={w - pad.r - 20} y={h - 2} fontSize="9" fill="#9CA3AF" fontFamily="monospace" textAnchor="end">Y{series.length}</text>
    </svg>
  );
}

// Heuristic DNO inference from lat/lon (rough UK regions). Replace with
// proper dno_boundaries lookup once project rows have dno_area set.
function _inferDno(p) {
  if (!p?.lat || !p?.lon) return "Unknown DNO";
  const { lat, lon } = p;
  if (lat > 54.5) return "SSEN North";
  if (lat > 53.0 && lon < -1.5) return "ENWL";
  if (lat > 52.5 && lon < -1.5) return "NGED (WPD)";
  if (lat > 53.0) return "NPG";
  if (lon > 0) return "UKPN";
  if (lon > -1.0 && lat < 52) return "UKPN / SSEN South";
  return "NGED";
}

function _stubPoc(p) {
  const base = p?.name || "Nearest GSP";
  return `${base.split(" ")[0]} 132kV Primary`;
}

function Sparkline({ points = [12, 14, 13, 15, 17, 16, 18, 20, 19, 22], color = "var(--gold)" }) {
  const w = 260, h = 60, pad = 4;
  const max = Math.max(...points), min = Math.min(...points);
  const range = max - min || 1;
  const step = (w - pad * 2) / (points.length - 1);
  const d = points
    .map((p, i) => {
      const x = pad + i * step;
      const y = h - pad - ((p - min) / range) * (h - pad * 2);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={w} height={h} className="ov-spark">
      <path d={d} stroke={color} strokeWidth="2" fill="none" strokeLinecap="round" />
    </svg>
  );
}

export default function OverviewTab({
  project,
  mapSlot = null,
  onViewMap = () => {},
  onViewTab = () => {},
}) {
  const isBess = project?.technology === "bess";
  const isDC = project?.technology === "dc";

  const kpis = isBess
    ? [
        { label: "Projected IRR", value: "11.8%", trend: "+0.4" },
        { label: "LCOE", value: "£42/MWh", trend: "−£0.8" },
        { label: "CAPEX", value: "£52M", trend: "flat" },
      ]
    : isDC
    ? [
        { label: "PUE (modelled)", value: "1.24", trend: "−0.02" },
        { label: "$/MW/yr", value: "£3.8M", trend: "+£120k" },
        { label: "Grid risk", value: "Medium", trend: "watch" },
      ]
    : [
        { label: "IRR", value: "—", trend: "" },
        { label: "LCOE", value: "—", trend: "" },
        { label: "CAPEX", value: "—", trend: "" },
      ];

  const projectId = project?.project_id || project?.id;

  return (
    <div className="ov-root">
      {/* StageRibbon (above this tab) is the canonical pipeline — duplicate card removed 2026-04-19 */}

      {projectId && (
        <div style={{ marginBottom: 16 }}>
          <ProjectKpiStrip projectId={projectId} />
        </div>
      )}

      <div className="ov-row ov-row-top">
        <div className="ov-card ov-map-card">
          <div className="ov-card-header">
            <span>Site map</span>
            <button className="ov-link" onClick={onViewMap}>Full-screen ⇱</button>
          </div>
          <div className="ov-map-preview">
            <SiteMapPin
              lat={project?.lat}
              lon={project?.lon}
              name={project?.name}
            />
          </div>
        </div>

        <GridConnectionCard
          project={project}
          isBess={isBess}
          isDC={isDC}
          onViewTab={onViewTab}
        />
      </div>

      <div className="ov-row ov-row-bot">
        <div className="ov-card">
          <div className="ov-card-header">
            <span>Blockers</span>
            <span className="ov-count">{MOCK_BLOCKERS.length}</span>
          </div>
          <ul className="ov-list">
            {MOCK_BLOCKERS.map((b, i) => (
              <li key={i} className="ov-item">
                <span
                  className="ov-dot"
                  style={{
                    background:
                      b.severity === "warn"
                        ? "var(--cds-support-warning)"
                        : "var(--cds-text-helper)",
                  }}
                />
                <span className="ov-item-text">{b.text}</span>
                <span className="ov-item-age">{b.age}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="ov-card">
          <div className="ov-card-header"><span>Recent activity</span></div>
          <ul className="ov-list">
            {MOCK_ACTIVITY.map((a, i) => (
              <li key={i} className="ov-item">
                <span className="ov-activity-icon">{a.icon}</span>
                <span className="ov-item-text">{a.text}</span>
                <span className="ov-item-age">{a.ts}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="ov-card">
          <div className="ov-card-header"><span>Next steps</span></div>
          <ul className="ov-list ov-list-tasks">
            {MOCK_NEXT.map((t, i) => (
              <li key={i} className="ov-item">
                <input type="checkbox" className="ov-check" />
                <span className="ov-item-text">{t}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* AI Site Memo — investment-grade one-pager */}
      {projectId && (
        <div style={{ marginTop: 16 }}>
          <SiteMemoCard projectId={projectId} />
        </div>
      )}

      {/* Filings preview — link through to File tab */}
      <div className="ov-card">
        <div className="ov-card-header">
          <span>Filings & artefacts</span>
          <button className="ov-link" onClick={() => onViewTab("file")}>Open File tab →</button>
        </div>
        <ul className="ov-list">
          {MOCK_FILINGS.map((f, i) => (
            <li key={i} className="ov-item ov-filing">
              <span className={"ov-file-pill ov-file-" + f.status}>{f.status}</span>
              <span className="ov-item-text">{f.name}</span>
              <span className="ov-item-age">@ {STAGES.find((s) => s.key === f.stage)?.label || f.stage}</span>
            </li>
          ))}
        </ul>
      </div>

      <style>{`
        .ov-root {
          /* Tightened 2026-04-19 (BOT-TT) — was 24px / 16px gap.
             Cards now sit closer to the hero strip without competing. */
          padding: 16px 20px;
          font-family: "DM Sans", -apple-system, sans-serif;
          color: var(--cds-text-primary);
          display: flex; flex-direction: column; gap: 12px;
          overflow-y: auto;
        }
        .ov-row { display: flex; gap: 12px; }
        .ov-row-top > .ov-map-card { flex: 3; min-height: 380px; }
        .ov-row-top > .ov-perf-card { flex: 2; }
        .ov-row-bot > .ov-card { flex: 1; }
        .ov-card {
          background: var(--cds-layer-01);
          border: 1px solid var(--cds-border-subtle);
          border-radius: 10px;
          padding: 12px 14px;
          display: flex; flex-direction: column; min-width: 0;
        }
        .ov-card-header {
          display: flex; justify-content: space-between; align-items: center;
          margin-bottom: 10px;
          font-size: 13px; font-weight: 700;
          color: var(--ink);
        }
        .ov-link {
          background: none; border: none; padding: 0;
          color: var(--gold-dark);
          font-size: 12px; font-weight: 600;
          cursor: pointer;
        }
        .ov-link:hover { color: var(--gold); }
        .ov-count {
          background: var(--cds-layer-03);
          color: var(--cds-text-secondary);
          padding: 1px 8px; border-radius: 10px;
          font-size: 10px; font-family: var(--mono);
          font-weight: 700;
        }

        .ov-map-preview {
          flex: 1;
          position: relative;
          min-height: 320px;
          border-radius: 8px;
          overflow: hidden;
        }
        .ov-map-live {
          position: absolute; inset: 0;
        }
        .ov-map-placeholder {
          height: 100%; min-height: 240px;
          background: linear-gradient(135deg, #EEF0F3, #E3E6EB);
          border-radius: 8px;
          display: flex; flex-direction: column;
          align-items: center; justify-content: center;
          gap: 6px;
          color: var(--cds-text-helper);
          font-size: 13px;
        }
        .ov-map-coord {
          font-family: var(--mono); font-size: 11px;
        }

        .ov-kpi-row {
          display: flex; gap: 12px;
          margin-bottom: 12px;
        }
        .ov-kpi {
          flex: 1;
          padding: 10px 12px;
          background: var(--cds-layer-02);
          border-radius: 8px;
        }
        .ov-kpi-label {
          font-size: 10px; font-weight: 600;
          color: var(--cds-text-helper);
          letter-spacing: 0.04em;
          text-transform: uppercase;
          margin-bottom: 4px;
        }
        .ov-kpi-value {
          font-family: var(--mono);
          font-size: 18px; font-weight: 700;
          color: var(--ink);
        }
        .ov-kpi-trend {
          font-family: var(--mono);
          font-size: 10px;
          color: var(--cds-text-helper);
          margin-top: 2px;
        }
        .ov-spark {
          width: 100%; height: 60px;
        }

        .ov-list {
          list-style: none; margin: 0; padding: 0;
          display: flex; flex-direction: column; gap: 6px;
        }
        .ov-item {
          display: flex; align-items: center; gap: 10px;
          padding: 6px 0;
          font-size: 12px;
          color: var(--cds-text-secondary);
          border-bottom: 1px solid transparent;
        }
        .ov-item-text { flex: 1; }
        .ov-item-age {
          font-family: var(--mono); font-size: 10px;
          color: var(--cds-text-helper);
          flex-shrink: 0;
        }
        .ov-dot {
          width: 8px; height: 8px; border-radius: 50%;
          flex-shrink: 0;
        }
        .ov-activity-icon {
          font-size: 14px; width: 18px;
          color: var(--cds-text-helper);
          text-align: center;
        }
        .ov-list-tasks .ov-item { padding: 8px 0; }
        .ov-check { accent-color: var(--gold); cursor: pointer; }

        /* Pipeline stages strip */
        .ov-pipeline-card { padding: 14px 20px; }
        .ov-stage-sub { font-size: 11px; color: var(--cds-text-helper); font-weight: 500; }
        .ov-stage-sub b { color: var(--ink); }
        .ov-pipeline {
          display: flex; align-items: center; gap: 4px;
          margin-top: 8px; overflow-x: auto;
        }
        .ov-pstage { display: flex; flex-direction: column; align-items: center; gap: 4px; min-width: 72px; }
        .ov-pstage-dot {
          width: 26px; height: 26px; border-radius: 50%;
          display: flex; align-items: center; justify-content: center;
          font-family: var(--mono); font-size: 11px; font-weight: 700;
          background: var(--cds-layer-03); color: var(--cds-text-helper);
          border: 2px solid var(--cds-border-subtle);
        }
        .ov-pstage-done .ov-pstage-dot {
          background: var(--cds-support-success); color: #fff;
          border-color: var(--cds-support-success);
        }
        .ov-pstage-active .ov-pstage-dot {
          background: var(--gold); color: #fff; border-color: var(--gold);
          box-shadow: 0 0 0 4px rgba(var(--accent-rgb), 0.2);
        }
        .ov-pstage-lbl { font-size: 10px; color: var(--cds-text-helper); font-weight: 600; text-align: center; }
        .ov-pstage-done .ov-pstage-lbl { color: var(--cds-text-secondary); }
        .ov-pstage-active .ov-pstage-lbl { color: var(--ink); font-weight: 700; }
        .ov-pline { height: 2px; flex: 1; min-width: 14px; background: var(--cds-layer-03); margin-bottom: 16px; }
        .ov-pline-done { background: var(--cds-support-success); }

        /* Filings preview */
        .ov-filing { gap: 8px; }
        .ov-file-pill {
          font-family: var(--mono); font-size: 9px; font-weight: 700;
          padding: 2px 6px; border-radius: 4px; text-transform: uppercase;
          letter-spacing: 0.04em; flex-shrink: 0;
        }
        .ov-file-draft    { background: var(--cds-layer-03); color: var(--cds-text-secondary); }
        .ov-file-outline  { background: rgba(232,160,18,0.12); color: var(--cds-support-warning); }
        .ov-file-drafting { background: rgba(232,160,18,0.12); color: var(--cds-support-warning); }
        .ov-file-pending  { background: rgba(45,108,176,0.12); color: #2D6CB0; }
        .ov-file-filed    { background: rgba(22,163,74,0.12); color: var(--cds-support-success); }

        /* Grid connection card — developer-grade DNO board */
        .ov-gc-card { display: flex; flex-direction: column; gap: 14px; }
        .ov-gc-header-row {
          display: grid; grid-template-columns: auto 1fr auto; gap: 16px;
          align-items: center; padding: 10px 12px;
          background: var(--cds-layer-02); border-radius: 8px;
        }
        .ov-gc-dno-lbl, .ov-gc-risk-lbl {
          font-size: 9px; font-weight: 700; letter-spacing: 0.06em;
          text-transform: uppercase; color: var(--cds-text-helper);
        }
        .ov-gc-dno-val { font-size: 13px; font-weight: 700; color: var(--ink); margin-top: 2px; }
        .ov-gc-poc-name { font-size: 13px; font-weight: 700; color: var(--ink); }
        .ov-gc-poc-meta {
          font-family: var(--mono); font-size: 10px; color: var(--cds-text-secondary);
          margin-top: 2px; letter-spacing: 0.02em;
        }
        .ov-gc-risk { text-align: right; }
        .ov-gc-risk-val { font-size: 13px; font-weight: 700; margin-top: 2px; }

        .ov-gc-metrics {
          display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;
        }
        .ov-gc-m {
          padding: 10px 12px; background: var(--cds-layer-01);
          border: 1px solid var(--cds-border-subtle); border-radius: 8px;
        }
        .ov-gc-m-dense { padding: 8px 10px; }
        .ov-gc-m-lbl {
          font-size: 9px; font-weight: 700; letter-spacing: 0.05em;
          text-transform: uppercase; color: var(--cds-text-helper);
        }
        .ov-gc-m-val {
          font-family: var(--mono); font-size: 16px; font-weight: 700;
          color: var(--ink); margin-top: 4px;
        }
        .ov-gc-m-dense .ov-gc-m-val { font-size: 14px; margin-top: 2px; }
        .ov-gc-m-sub {
          font-family: var(--mono); font-size: 10px;
          color: var(--cds-text-helper); margin-top: 2px;
        }

        .ov-gc-dates {
          display: flex; align-items: stretch; gap: 6px;
          padding: 10px 12px;
          background: linear-gradient(180deg, rgba(var(--accent-rgb),0.05), transparent);
          border: 1px solid rgba(var(--accent-rgb),0.2);
          border-radius: 8px;
        }
        .ov-gc-d { flex: 1; padding: 4px 2px; }
        .ov-gc-d-lbl {
          font-size: 9px; font-weight: 700; letter-spacing: 0.05em;
          text-transform: uppercase; color: var(--cds-text-helper);
        }
        .ov-gc-d-val {
          font-family: var(--mono); font-size: 12px; font-weight: 700;
          color: var(--ink); margin-top: 3px;
        }
        .ov-gc-d-pending .ov-gc-d-val { color: var(--cds-support-warning); }
        .ov-gc-d-future .ov-gc-d-val { color: var(--cds-text-secondary); }
        .ov-gc-d-done .ov-gc-d-val { color: var(--cds-support-success); }
        .ov-gc-dates-arrow {
          display: flex; align-items: center; color: var(--cds-text-helper);
          font-size: 16px; padding: 0 4px;
        }

        .ov-gc-finance {
          display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;
          padding-top: 8px; border-top: 1px dashed var(--cds-border-subtle);
        }

        .ov-gc-chart { display: flex; flex-direction: column; gap: 4px; }
        .ov-gc-chart-lbl {
          font-size: 10px; font-weight: 600;
          color: var(--cds-text-helper); letter-spacing: 0.02em;
        }
        .ov-gc-spark { width: 100%; height: 72px; }
      `}</style>
    </div>
  );
}
