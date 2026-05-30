import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import ProvenanceFooter, { WarmingState, TileSkeleton } from "./ProvenanceFooter";

/**
 * PipelineFunnelTile — clickable per-stage drill into typed Project objects.
 *
 * Reads /api/portfolios/mission-control (existing) and bins active projects
 * by `stage`. Each stage row links to /v2/objects/Project?stage=<stage>; the
 * destination is a placeholder (TODO: typed ontology browser).
 */
const STAGE_ORDER = ["prospect", "discover", "screened", "design", "assess",
                     "grid_applied", "grid_offer", "planning", "fid",
                     "construction", "energised", "operate"];

function stageLabel(s) {
  return ({
    prospect: "Prospect", discover: "Discover", screened: "Screened",
    design: "Design", assess: "Assess",
    grid_applied: "Grid applied", grid_offer: "Grid offer",
    planning: "Planning", fid: "FID",
    construction: "Construction", energised: "Energised", operate: "Operate",
  })[s] || s;
}

export default function PipelineFunnelTile({ data, loading = false }) {
  const navigate = useNavigate();
  const [bins, setBins] = useState([]);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    if (!data) return;
    const projects = data.active_projects || [];
    const counts = {};
    for (const p of projects) {
      const s = (p.stage || "discover").toLowerCase();
      counts[s] = (counts[s] || 0) + 1;
    }
    // Pad with zero-count rows for the canonical stages so the funnel is stable.
    const ordered = STAGE_ORDER
      .map(s => ({ stage: s, count: counts[s] || 0 }))
      .filter(r => r.count > 0)
      .sort((a, b) => b.count - a.count);
    // If active_projects is empty (cold start) fall back to metrics.in_queue.
    const t = projects.length || (data.metrics && data.metrics.total_projects) || 0;
    setBins(ordered);
    setTotal(t);
  }, [data]);

  const max = Math.max(1, ...bins.map(b => b.count));

  return (
    <div className="mcv2-tile mcv2-area-kpi">
      <div className="mcv2-tile-head">
        <div className="mcv2-tile-title">Pipeline funnel</div>
        <div className="mcv2-tile-tag">Project · ontology</div>
      </div>
      <div className="mcv2-tile-body">
        {loading && !data ? (
          <TileSkeleton rows={5} />
        ) : !data ? (
          <WarmingState />
        ) : bins.length === 0 ? (
          <WarmingState label="No active projects yet — funnel will populate once projects are created." />
        ) : (
          <div className="mcv2-funnel">
            {bins.map(b => (
              <div
                key={b.stage}
                className="mcv2-funnel-row"
                onClick={() => navigate(`/v2/object/Project?stage=${b.stage}`)}
                title={`Drill into ${b.count} ${stageLabel(b.stage)} project(s)`}
              >
                <div className="mcv2-funnel-stage">{stageLabel(b.stage)}</div>
                <div className="mcv2-funnel-bar">
                  <div
                    className="mcv2-funnel-fill"
                    style={{ width: `${Math.round((b.count / max) * 100)}%` }}
                  />
                </div>
                <div className="mcv2-funnel-count">{b.count}</div>
              </div>
            ))}
          </div>
        )}
      </div>
      <ProvenanceFooter
        source={`Apache AGE · Postgres + PostGIS 3.3 · ${total} projects`}
        generatedAt={new Date().toISOString()}
      />
    </div>
  );
}
