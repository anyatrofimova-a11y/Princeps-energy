import React, { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import "./mission-control-v2.css";

import PipelineFunnelTile from "./tiles/PipelineFunnelTile";
import GridPulseTile from "./tiles/GridPulseTile";
import ConnectorHealthTile from "./tiles/ConnectorHealthTile";
import CouncilActivityTile from "./tiles/CouncilActivityTile";
import TopOwnersTile from "./tiles/TopOwnersTile";
import WeeklyDeltaTile from "./tiles/WeeklyDeltaTile";
import ActionQueueTile from "./tiles/ActionQueueTile";
import ActiveProjectsTile from "./tiles/ActiveProjectsTile";
import ProvenanceFooter from "./tiles/ProvenanceFooter";

// Reuse the existing live BESS revenue widget — DO NOT rebuild.
const LiveBessRevenue = lazy(() => import("../components/bess/LiveBessRevenue.jsx"));

/**
 * MissionControlV2 — composed Workshop-pattern home screen for Princeps.
 *
 * Replaces the static 3-card Dashboard at /v2 with 8 typed tiles, each
 * with its own provenance footer. Polling: every tile consumes the
 * shared composite snapshot at /api/mission-control/v2/snapshot,
 * refreshed every 30s with stale-while-revalidate.
 *
 * Layout (CSS Grid named-areas):
 *   header header header
 *   kpi    kpi    activity
 *   pulse  health council
 *   owners delta  actions
 *   bess   bess   bess
 *
 * The "activity" slot here is the connector health tile rendered second so
 * the right column reads top-down: activity-style connectors → council →
 * actions. The exact area names match mission-control-v2.css.
 */

const REFRESH_MS = 30_000;

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString("en-GB", {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch {
    return "—";
  }
}

export default function MissionControlV2() {
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastFetchAt, setLastFetchAt] = useState(null);
  const intervalRef = useRef(null);

  const fetchSnapshot = useCallback(async () => {
    try {
      const r = await fetch("/api/mission-control/v2/snapshot");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      setSnapshot(j);
      setError(null);
      setLastFetchAt(new Date().toISOString());
    } catch (exc) {
      setError(String(exc.message || exc));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSnapshot();
    intervalRef.current = setInterval(fetchSnapshot, REFRESH_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchSnapshot]);

  return (
    <div className="mcv2-page">
      <div className="mcv2-header">
        <div>
          <div className="mcv2-eyebrow">Princeps · Mission Control v2</div>
          <h1 className="mcv2-title">Operational cockpit</h1>
          <div className="mcv2-subtitle">
            Typed objects · provenance · drill-downs · 30 s refresh
          </div>
        </div>
        <div className="mcv2-stamp">
          <div>{loading ? "loading…" : `last refresh ${fmtTime(lastFetchAt)}`}</div>
          {error && <div style={{ color: "#DC2626" }}>err: {error}</div>}
        </div>
      </div>

      <div className="mcv2-grid">
        {/* Row 1 — kpi (spans 2 cols) + activity (right column) */}
        <PipelineFunnelTile data={snapshot?.funnel} loading={loading} />
        <ConnectorHealthTile
          data={snapshot?.datasets}
          onRefresh={fetchSnapshot}
          loading={loading}
        />

        {/* Row 2 — pulse (spans 2 cols) + council */}
        <GridPulseTile data={snapshot?.grid_pulse} loading={loading} />
        <CouncilActivityTile data={snapshot?.council} loading={loading} />

        {/* Row 3 — owners / delta / actions */}
        <TopOwnersTile data={snapshot?.top_owners} loading={loading} />
        <WeeklyDeltaTile data={snapshot?.weekly_delta} loading={loading} />
        <ActionQueueTile data={snapshot?.actions} loading={loading} />

        {/* Row 4 — BESS live revenue (reused widget, full-width) */}
        <div className="mcv2-tile mcv2-area-bess" style={{ minHeight: 320 }}>
          <div className="mcv2-tile-head">
            <div className="mcv2-tile-title">BESS · live revenue</div>
            <div className="mcv2-tile-tag">last 30 days</div>
          </div>
          <div className="mcv2-tile-body" style={{ flex: 1 }}>
            <Suspense fallback={<div className="mcv2-skeleton" style={{ height: 220 }} />}>
              <LiveBessRevenue />
            </Suspense>
          </div>
          <ProvenanceFooter
            source="BMRS Insights API · NESO Balancing Mechanism · Modo Energy benchmark"
            generatedAt={lastFetchAt}
          />
        </div>
      </div>

      {/* Active projects — clickable rows route to /v2/project/:id workspace.
          Lives outside .mcv2-grid so it spans the full width without touching
          the named-areas template above. */}
      <ActiveProjectsTile />
    </div>
  );
}
