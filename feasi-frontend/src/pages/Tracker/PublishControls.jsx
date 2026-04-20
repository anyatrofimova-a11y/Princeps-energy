import React, { useState } from "react";
import { useTrackerStats, useRefreshTracker } from "../../hooks/useTracker";
import { downloadCSV, downloadGeoJSON, downloadParquet } from "../../api/tracker";

/* ─────────────────────────────────────────────────────────────────
   PublishControls — admin strip for the Tracker dashboard header.
   Shows total count · last refresh · Trigger refresh · downloads.
   ──────────────────────────────────────────────────────────────── */

const C = {
  gold: "#F5B731",
  goldSoft: "#C9A64B",
  goldSurface: "rgba(245,183,49,0.10)",
  goldBorder: "rgba(245,183,49,0.32)",
  ivory: "#FBF8F2",
  ink: "#0F1318",
  secondary: "#4B5563",
  tertiary: "#9C9590",
  border: "#E8EAED",
  bg: "#FFFFFF",
};

function formatRelative(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const diffMin = Math.round((Date.now() - d.getTime()) / 60000);
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffMin < 1440) return `${Math.round(diffMin / 60)}h ago`;
    return `${Math.round(diffMin / 1440)}d ago`;
  } catch { return iso; }
}

export default function PublishControls({ admin = true }) {
  const { stats, reload } = useTrackerStats();
  const { run, running } = useRefreshTracker(() => reload());
  const [downloading, setDownloading] = useState(null);
  const [flash, setFlash] = useState(null);

  const doDownload = async (kind, fn) => {
    setDownloading(kind);
    try {
      await fn();
      setFlash({ kind: "ok", msg: `${kind} ready` });
    } catch (e) {
      setFlash({ kind: "err", msg: e.message || String(e) });
    } finally {
      setDownloading(null);
      setTimeout(() => setFlash(null), 1800);
    }
  };

  const doRefresh = async () => {
    try {
      await run();
      setFlash({ kind: "ok", msg: "Refresh job queued" });
    } catch (e) {
      setFlash({ kind: "err", msg: e.message || String(e) });
    } finally {
      setTimeout(() => setFlash(null), 1800);
    }
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        flexWrap: "wrap",
        padding: "10px 14px",
        background: C.goldSurface,
        border: `1px solid ${C.goldBorder}`,
        borderRadius: 10,
        fontFamily: "'DM Sans', sans-serif",
        color: C.ink,
      }}
    >
      <Stat label="Total" value={stats?.total ?? "—"} />
      <Stat label="Planned" value={stats?.by_status?.planned ?? "—"} />
      <Stat label="Under constr." value={stats?.by_status?.under_construction ?? "—"} />
      <Stat label="Avg confidence" value={stats?.avg_confidence != null ? stats.avg_confidence.toFixed(2) : "—"} />
      <Stat label="Capex Σ £m" value={stats?.capex_total_gbp_m != null ? stats.capex_total_gbp_m.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "—"} />
      <div style={{ fontSize: 11, color: C.tertiary, fontFamily: "'JetBrains Mono', monospace" }}>
        last refresh · {formatRelative(stats?.last_refresh)}
      </div>

      <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        {admin && (
          <button
            type="button"
            onClick={doRefresh}
            disabled={running}
            style={{
              padding: "7px 14px",
              borderRadius: 6,
              border: `1px solid ${C.gold}`,
              background: running ? "#f3d98a" : C.gold,
              color: C.ink,
              fontWeight: 700,
              fontSize: 12,
              cursor: running ? "wait" : "pointer",
            }}
          >
            {running ? "Refreshing…" : "Trigger refresh"}
          </button>
        )}

        <button
          type="button"
          onClick={() => doDownload("CSV", downloadCSV)}
          disabled={downloading === "CSV"}
          style={btnGhost}
        >
          {downloading === "CSV" ? "…" : "CSV"}
        </button>
        <button
          type="button"
          onClick={() => doDownload("GeoJSON", downloadGeoJSON)}
          disabled={downloading === "GeoJSON"}
          style={btnGhost}
        >
          {downloading === "GeoJSON" ? "…" : "GeoJSON"}
        </button>
        <button
          type="button"
          onClick={() => doDownload("Parquet", downloadParquet)}
          disabled={downloading === "Parquet"}
          style={btnGhost}
        >
          {downloading === "Parquet" ? "…" : "Parquet"}
        </button>

        {flash && (
          <span
            style={{
              fontSize: 11,
              color: flash.kind === "ok" ? "#1C6B3A" : "#8E1E1E",
              background: flash.kind === "ok" ? "#D8F0DC" : "#FBD8D5",
              padding: "3px 10px",
              borderRadius: 6,
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            {flash.msg}
          </span>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.1 }}>
      <span style={{ fontSize: 10, color: C.tertiary, textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 600 }}>
        {label}
      </span>
      <span style={{ fontSize: 16, color: C.ink, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>
        {value}
      </span>
    </div>
  );
}

const btnGhost = {
  padding: "6px 10px",
  borderRadius: 6,
  border: `1px solid ${C.border}`,
  background: C.bg,
  color: C.ink,
  fontWeight: 600,
  fontSize: 11,
  cursor: "pointer",
  fontFamily: "'JetBrains Mono', monospace",
};
