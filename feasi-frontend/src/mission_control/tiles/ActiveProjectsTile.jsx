import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import ProvenanceFooter, { WarmingState, TileSkeleton } from "./ProvenanceFooter";

/**
 * ActiveProjectsTile — clickable list of the most-recent active projects.
 * Each row routes to /v2/project/:id, where ProjectWorkspace renders the
 * map / verdict / cascade view. Pulls from /api/portfolios/mission-control
 * (existing) so we share the same dataset as PipelineFunnelTile.
 */

const VERDICT_STYLE = {
  GO:      { bg: "rgba(22, 163, 74, 0.14)", fg: "#16A34A" },
  CAUTION: { bg: "rgba(232, 160, 18, 0.16)", fg: "#E8A012" },
  "NO-GO": { bg: "rgba(220, 38, 38, 0.14)", fg: "#DC2626" },
  NOGO:    { bg: "rgba(220, 38, 38, 0.14)", fg: "#DC2626" },
};

const TECH_LABEL = {
  bess: "BESS", solar: "Solar", wind: "Wind",
  dc: "DC", nuclear: "Nuclear", hybrid: "Hybrid", gas: "Gas",
};

function fmtMw(mw) {
  if (mw == null) return "—";
  if (mw >= 1000) return `${(mw / 1000).toFixed(1)} GW`;
  return `${Math.round(mw)} MW`;
}

export default function ActiveProjectsTile() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [generatedAt, setGeneratedAt] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/portfolios/mission-control")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((j) => {
        if (cancelled) return;
        // Dedupe by id — backend occasionally returns duplicates.
        const seen = new Set();
        const out = [];
        for (const p of j?.active_projects || []) {
          if (!p.project_id || seen.has(p.project_id)) continue;
          seen.add(p.project_id);
          out.push(p);
        }
        setProjects(out.slice(0, 8));
        setGeneratedAt(new Date().toISOString());
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(String(e.message || e));
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  return (
    <section className="apt-section">
      <div className="apt-head">
        <div className="apt-title">Active projects</div>
        <div className="apt-tag">click to open workspace</div>
      </div>
      {loading && !projects ? (
        <TileSkeleton rows={5} />
      ) : error ? (
        <div className="apt-empty apt-empty-err">Couldn't load: {error}</div>
      ) : !projects ? (
        <WarmingState />
      ) : projects.length === 0 ? (
        <WarmingState label="No active projects yet — create one to see it here." />
      ) : (
        <div className="apt-list">
          {projects.map((p) => {
            const v = VERDICT_STYLE[(p.verdict || "").toUpperCase()] ||
              { bg: "#F5F1E8", fg: "#4A5057" };
            const tech = TECH_LABEL[(p.workload_type || "").toLowerCase()] || p.workload_type;
            return (
              <button
                key={p.project_id}
                className="apt-row"
                onClick={() => navigate(`/v2/project/${encodeURIComponent(p.project_id)}`)}
                title={`Open ${p.name} workspace`}
              >
                <span className="apt-row-name">{p.name}</span>
                <span className="apt-row-tech">{tech}</span>
                <span className="apt-row-mw">{fmtMw(p.capacity_mw)}</span>
                <span className="apt-row-verdict" style={{ background: v.bg, color: v.fg }}>
                  {(p.verdict || "—").toUpperCase()}
                </span>
                <span className="apt-row-arrow">→</span>
              </button>
            );
          })}
        </div>
      )}
      <ProvenanceFooter
        source="Apache AGE · Postgres + PostGIS 3.3 · projects table"
        generatedAt={generatedAt}
      />
      <style>{styles}</style>
    </section>
  );
}

const styles = `
  .apt-section {
    background: #FFFFFF;
    border: 1px solid #ECE7DA;
    border-radius: 14px;
    padding: 16px 20px 14px;
    box-shadow: 0 4px 24px rgba(15, 19, 24, 0.08);
    margin-top: 18px;
  }
  .apt-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
  }
  .apt-title {
    font-size: 13px;
    font-weight: 600;
    color: #0F1318;
  }
  .apt-tag {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: #F5B731;
    font-weight: 600;
    background: rgba(245, 183, 49, 0.18);
    padding: 3px 8px;
    border-radius: 999px;
  }
  .apt-empty {
    font-size: 12px;
    color: #8A9099;
    padding: 18px 8px;
  }
  .apt-empty-err { color: #DC2626; }
  .apt-list { display: flex; flex-direction: column; }
  .apt-row {
    appearance: none;
    background: transparent;
    border: none;
    border-bottom: 1px solid #ECE7DA;
    display: grid;
    grid-template-columns: 1fr 70px 80px 90px 16px;
    gap: 12px;
    align-items: center;
    padding: 10px 4px;
    font: inherit;
    text-align: left;
    cursor: pointer;
    transition: background 100ms ease;
    color: inherit;
  }
  .apt-row:last-child { border-bottom: none; }
  .apt-row:hover { background: #FFFBF0; }
  .apt-row-name {
    font-size: 13px;
    font-weight: 600;
    color: #0F1318;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .apt-row-tech {
    font-size: 11px;
    color: #8A9099;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  .apt-row-mw {
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 12px;
    font-weight: 600;
    color: #0F1318;
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
  .apt-row-verdict {
    font-family: 'DM Sans', sans-serif;
    font-weight: 700;
    font-size: 10px;
    letter-spacing: 0.08em;
    padding: 3px 8px;
    border-radius: 4px;
    text-align: center;
  }
  .apt-row-arrow {
    color: #8A9099;
    font-size: 14px;
    transition: color 120ms ease, transform 120ms ease;
  }
  .apt-row:hover .apt-row-arrow {
    color: #F5B731;
    transform: translateX(2px);
  }
`;
