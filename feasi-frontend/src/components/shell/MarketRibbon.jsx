import React, { useEffect, useState } from "react";

/**
 * MarketRibbon — top-of-screen strip of live UK market signals.
 *
 * Polls /api/market/live every 45s (well below cache TTL on the backend).
 * Each cell fades to muted when the feed is stale / unreachable.
 *
 * Fields: wholesale imbalance · DC/DM/DR clearing · capacity market · CO₂
 */

const REFRESH_MS = 45_000;

const PANELS = [
  { key: "ws", label: "Wholesale", get: (d) => d?.wholesale?.imbalance_gbp_mwh ?? d?.wholesale?.day_ahead_gbp_mwh, unit: "£/MWh", hint: (d) => d?.wholesale?.source || "—" },
  { key: "dc", label: "DC clearing", get: (d) => d?.ancillary?.dc_gbp_mw_h, unit: "£/MW/h", hint: (d) => d?.ancillary?.source || "—" },
  { key: "dm", label: "DM", get: (d) => d?.ancillary?.dm_gbp_mw_h, unit: "£/MW/h" },
  { key: "dr", label: "DR", get: (d) => d?.ancillary?.dr_gbp_mw_h, unit: "£/MW/h" },
  { key: "t1", label: "CapMarket T-1", get: (d) => d?.capacity_market?.t1_2026_gbp_kw_yr, unit: "£/kW/yr" },
  { key: "t4", label: "CapMarket T-4", get: (d) => d?.capacity_market?.t4_2027_gbp_kw_yr, unit: "£/kW/yr" },
  { key: "co2", label: "Carbon", get: (d) => d?.carbon?.gco2_kwh, unit: "gCO₂", band: (d) => d?.carbon?.band },
];

function Panel({ p, data, ts }) {
  const v = p.get(data);
  const stale = ts && Date.now() - ts > REFRESH_MS * 3;
  const band = p.band?.(data);
  const colour = band === "low" ? "var(--cds-support-success)"
               : band === "high" ? "var(--cds-support-error)"
               : band === "moderate" ? "var(--cds-support-warning)"
               : null;
  return (
    <div className={"mr-cell" + (stale ? " mr-stale" : "")}>
      <div className="mr-lbl">{p.label}</div>
      <div className="mr-val" style={colour ? { color: colour } : undefined}>
        {v != null ? (typeof v === "number" ? v.toFixed(v < 10 ? 2 : 1) : v) : "—"}
        <span className="mr-u">{p.unit}</span>
      </div>
    </div>
  );
}

export default function MarketRibbon() {
  const [data, setData] = useState(null);
  const [ts, setTs] = useState(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await fetch("/api/market/live");
        if (!r.ok) throw new Error(String(r.status));
        const j = await r.json();
        if (!cancelled) { setData(j); setTs(Date.now()); setErr(false); }
      } catch {
        if (!cancelled) setErr(true);
      }
    };
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  return (
    <div className="mr-root">
      <div className="mr-pulse" title="Live feed">
        <span className="mr-dot" />
        <span className="mr-live">LIVE</span>
      </div>
      {PANELS.map((p) => <Panel key={p.key} p={p} data={data} ts={ts} />)}
      <div className="mr-spacer" />
      <div className="mr-ts">{ts ? new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : (err ? "offline" : "…")}</div>
      <style>{`
        .mr-root {
          display: flex; align-items: center; gap: 0;
          height: 34px; padding: 0 16px;
          background: var(--cds-layer-01);
          color: var(--cds-text-primary);
          font-family: "DM Sans", -apple-system, sans-serif;
          font-size: 11px; overflow-x: auto;
          border-bottom: 1px solid var(--cds-border-subtle);
        }
        .mr-pulse { display: flex; align-items: center; gap: 6px; margin-right: 14px; flex-shrink: 0; }
        .mr-dot {
          width: 7px; height: 7px; border-radius: 50%;
          background: var(--cds-support-success);
          box-shadow: 0 0 0 3px rgba(22,163,74,0.20);
          animation: mr-pulse 1.8s ease-in-out infinite;
        }
        @keyframes mr-pulse {
          0%, 100% { box-shadow: 0 0 0 3px rgba(22,163,74,0.20); }
          50%      { box-shadow: 0 0 0 6px rgba(22,163,74,0.04); }
        }
        .mr-live {
          font-family: var(--mono); font-size: 9px; font-weight: 700;
          letter-spacing: 0.12em; color: var(--cds-support-success);
        }
        .mr-cell {
          display: flex; flex-direction: column; justify-content: center;
          padding: 3px 12px; border-left: 1px solid var(--cds-border-subtle);
          min-width: 88px; flex-shrink: 0;
        }
        .mr-lbl {
          font-size: 8px; font-weight: 700; letter-spacing: 0.08em;
          text-transform: uppercase; color: var(--cds-text-helper);
        }
        .mr-val {
          font-family: var(--mono); font-size: 12px; font-weight: 700;
          color: var(--ink); margin-top: 1px;
        }
        .mr-u {
          margin-left: 3px; color: var(--cds-text-helper);
          font-weight: 500; font-size: 9px;
        }
        .mr-stale .mr-val { color: var(--cds-text-helper); }
        .mr-spacer { flex: 1; }
        .mr-ts {
          font-family: var(--mono); font-size: 9px;
          color: var(--cds-text-helper); letter-spacing: 0.04em;
        }
      `}</style>
    </div>
  );
}
