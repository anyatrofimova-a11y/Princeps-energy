import React, { useState } from "react";
import ProvenanceFooter, { WarmingState, TileSkeleton } from "./ProvenanceFooter";

/**
 * ConnectorHealthTile — 5 dataset health pills with refresh buttons inline.
 *
 * Reads /api/datasets (just landed). Each pill: slug · row_count · health
 * dot · refresh button. The refresh button POSTs /api/datasets/{slug}/refresh
 * and animates the dot while the in-flight request resolves.
 */
function dotClass(health) {
  if (health === "green") return "mcv2-dot green";
  if (health === "yellow" || health === "warning") return "mcv2-dot yellow";
  if (health === "red" || health === "stale" || health === "error") return "mcv2-dot red";
  return "mcv2-dot";
}

function fmtRows(n) {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export default function ConnectorHealthTile({ data, onRefresh, loading = false }) {
  const [busy, setBusy] = useState({});
  const [errors, setErrors] = useState({});
  const datasets = (data && data.datasets) || [];

  async function handleRefresh(slug) {
    setBusy(b => ({ ...b, [slug]: true }));
    setErrors(e => ({ ...e, [slug]: null }));
    try {
      const r = await fetch(`/api/datasets/${encodeURIComponent(slug)}/refresh`, {
        method: "POST",
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      // Give the background task a beat then notify the parent so it re-fetches.
      setTimeout(() => {
        setBusy(b => ({ ...b, [slug]: false }));
        if (onRefresh) onRefresh();
      }, 1200);
    } catch (exc) {
      setBusy(b => ({ ...b, [slug]: false }));
      setErrors(e => ({ ...e, [slug]: String(exc.message || exc) }));
    }
  }

  return (
    <div className="mcv2-tile mcv2-area-activity">
      <div className="mcv2-tile-head">
        <div className="mcv2-tile-title">Connector health</div>
        <div className="mcv2-tile-tag">
          {data ? `${datasets.length} datasets` : "warming"}
        </div>
      </div>
      <div className="mcv2-tile-body">
        {loading && !data ? (
          <TileSkeleton rows={5} />
        ) : !data ? (
          <WarmingState />
        ) : datasets.length === 0 ? (
          <WarmingState label="No connectors registered yet — register one to begin." />
        ) : (
          <div className="mcv2-pill-list">
            {datasets.slice(0, 5).map(d => (
              <div className="mcv2-pill" key={d.slug} data-testid={`pill-${d.slug}`}>
                <span className={`${dotClass(d.health_status)} ${busy[d.slug] ? "spin" : ""}`} />
                <div>
                  <div className="mcv2-pill-slug">{d.slug}</div>
                  {errors[d.slug] && (
                    <div style={{ fontSize: 10, color: "#DC2626", marginTop: 2 }}>{errors[d.slug]}</div>
                  )}
                </div>
                <span className="mcv2-pill-rows">
                  {fmtRows(d.last_row_count)} rows
                </span>
                <button
                  className="mcv2-pill-btn"
                  disabled={busy[d.slug]}
                  onClick={() => handleRefresh(d.slug)}
                >
                  {busy[d.slug] ? "…" : "Refresh"}
                </button>
                <button
                  className="mcv2-pill-btn"
                  title="View lineage"
                  onClick={() => window.dispatchEvent(new CustomEvent("princeps:lineage", {detail: {root: d.slug}}))}
                >
                  Lineage
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
      <ProvenanceFooter
        source="princeps_datasets · dataset_refresh_log"
        generatedAt={data?.generated_at || new Date().toISOString()}
      />
    </div>
  );
}
