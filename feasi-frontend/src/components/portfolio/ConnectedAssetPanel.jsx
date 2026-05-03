import React, { useEffect, useState } from "react";
import useAssetExposure from "../../hooks/useAssetExposure";

/**
 * ConnectedAssetPanel — right-side drawer that opens when any map dispatches
 * `princeps-asset-click` with { id, name, voltage_kv, dno, type }.
 * Shows portfolio-wide financial exposure to that one grid asset.
 *
 * Mount once at App.jsx root. Subscribes to the window event + closes on Esc.
 */

const GOLD = "#F5B731";
const INK = "#0F1318";
const IVORY = "#FBF8F2";
const MUTED = "#6B7280";
const BORDER = "rgba(15, 19, 24, 0.08)";

const DIVERSIFICATION_COLOUR = {
  GREEN: "#198038",
  AMBER: "#E89A2A",
  RED: "#DA1E28",
};

function fmtMw(v) {
  if (v == null) return "—";
  if (v >= 1000) return `${(v / 1000).toFixed(1)} GW`;
  return `${Math.round(v)} MW`;
}
function fmtGbpM(v) {
  if (v == null) return "—";
  return `£${Number(v).toFixed(1)}m`;
}
function fmtPct(v) {
  if (v == null) return "—";
  return `${Number(v).toFixed(1)}%`;
}

export default function ConnectedAssetPanel() {
  const [asset, setAsset] = useState(null);
  const { loading, error, data } = useAssetExposure({ substation_id: asset?.id || null });

  useEffect(() => {
    const onClick = (e) => {
      const d = e.detail || {};
      if (!d.id) return;
      setAsset({
        id: String(d.id),
        name: d.name || `Asset ${d.id}`,
        voltage_kv: d.voltage_kv ?? null,
        dno: d.dno ?? null,
        type: d.type || "substation",
      });
    };
    const onKey = (e) => { if (e.key === "Escape") setAsset(null); };
    window.addEventListener("princeps-asset-click", onClick);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("princeps-asset-click", onClick);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  if (!asset) return null;

  const header = data?.asset_header || {};
  const ex = data?.portfolio_exposure || {};
  // Backend ships `concentration_index` (newer schema); older rev used
  // `concentration`. Accept either so the panel doesn't blank-render.
  const conc = data?.concentration_index || data?.concentration || {};
  const projects = data?.projects || [];
  const stress = data?.stress_cases || [];
  const divFlag = conc.diversification_flag || "GREEN";

  const close = () => setAsset(null);
  const askPrinceps = () => {
    try {
      window.dispatchEvent(new CustomEvent("princeps-chat-focus", {
        detail: {
          type: "substation",
          id: asset.id,
          label: header.name || asset.name,
          data: { ...asset, ...header, exposure: ex, concentration: conc },
        },
      }));
    } catch {}
  };

  return (
    <>
      <div className="cap-backdrop" onClick={close} />
      <aside className="cap-panel" role="complementary" aria-label="Connected asset financial exposure">
        <header className="cap-header">
          <div>
            <div className="cap-eyebrow">Connected asset</div>
            <div className="cap-title">{header.name || asset.name}</div>
            <div className="cap-sub">
              {header.voltage_kv ? `${header.voltage_kv} kV` : asset.voltage_kv ? `${asset.voltage_kv} kV` : "—"}
              {(header.dno || asset.dno) && ` · ${header.dno || asset.dno}`}
              {header.firm_headroom_mw != null && ` · ${header.firm_headroom_mw} MW firm`}
            </div>
          </div>
          <button className="cap-close" onClick={close} aria-label="Close">×</button>
        </header>

        {loading && <div className="cap-section cap-loading">Loading exposure…</div>}
        {error && <div className="cap-section cap-error">Failed to load: {error}</div>}

        {!loading && !error && data && (
          <>
            {/* Portfolio exposure */}
            <section className="cap-section">
              <div className="cap-section-title">Portfolio exposure</div>
              <div className="cap-metric-grid">
                <Metric label="MW exposed" value={fmtMw(ex.total_mw)} accent />
                <Metric label="Projects" value={ex.project_count ?? "—"} />
                <Metric label="NPV exposure" value={fmtGbpM(ex.total_npv_gbp_m)} />
                <Metric label="IRR (MW-wtd)" value={fmtPct(ex.mw_weighted_irr_pct)} />
              </div>
              <div className="cap-bar-wrap">
                <div className="cap-bar-label">
                  <span>Share of portfolio</span>
                  <span style={{ color: DIVERSIFICATION_COLOUR[divFlag], fontWeight: 700 }}>
                    {fmtPct(ex.portfolio_share_pct)} · {divFlag}
                  </span>
                </div>
                <div className="cap-bar-track">
                  <div
                    className="cap-bar-fill"
                    style={{
                      width: `${Math.min(100, Math.max(3, ex.portfolio_share_pct || 0))}%`,
                      background: DIVERSIFICATION_COLOUR[divFlag],
                    }}
                  />
                </div>
                <div className="cap-bar-sub">
                  HHI {conc.hhi ?? "—"} · {conc.band || "—"} · {fmtMw(ex.portfolio_total_mw)} total portfolio
                </div>
              </div>
            </section>

            {/* Projects list */}
            <section className="cap-section">
              <div className="cap-section-title">Projects on this asset ({projects.length})</div>
              {projects.length === 0 && (
                <div className="cap-empty">
                  No projects currently route through this asset in your pipeline.
                </div>
              )}
              {projects.length > 0 && (
                <ul className="cap-list">
                  {projects.slice(0, 8).map((p) => (
                    <li key={p.project_id} className="cap-list-item">
                      <div className="cap-list-main">
                        <span className="cap-list-name">{p.name || p.project_id.slice(0, 8)}</span>
                        <span className="cap-list-meta">
                          {p.tech?.toUpperCase()} · {fmtMw(p.capacity_mw)} · {p.stage || "—"}
                        </span>
                      </div>
                      <div className="cap-list-fin">
                        <span>{fmtPct(p.irr_pct)}</span>
                        <span className="cap-list-sub">{fmtGbpM(p.npv_gbp_m)}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* Stress cases */}
            <section className="cap-section">
              <div className="cap-section-title">Stress cases</div>
              <ul className="cap-stress">
                {stress.map((s) => (
                  <li key={s.name} className="cap-stress-row">
                    <div className="cap-stress-head">
                      <span className="cap-stress-name">{s.name}</span>
                      <span className={"cap-stress-delta" + (Number(s.npv_impact_gbp_m) < 0 ? " neg" : "")}>
                        {s.npv_impact_gbp_m != null ? `${s.npv_impact_gbp_m > 0 ? "+" : ""}£${s.npv_impact_gbp_m.toFixed(1)}m` : "—"}
                      </span>
                    </div>
                    <div className="cap-stress-desc">{s.description}</div>
                    {s.dscr_delta != null && (
                      <div className="cap-stress-sub">DSCR impact: {s.dscr_delta > 0 ? "+" : ""}{s.dscr_delta.toFixed(2)}</div>
                    )}
                  </li>
                ))}
              </ul>
            </section>

            {/* Actions */}
            <section className="cap-actions">
              <button className="cap-btn" onClick={askPrinceps}>Ask Princeps about this asset</button>
            </section>
          </>
        )}

        <style>{css}</style>
      </aside>
    </>
  );
}

function Metric({ label, value, accent }) {
  return (
    <div className="cap-metric">
      <div className="cap-metric-lbl">{label}</div>
      <div className={"cap-metric-val" + (accent ? " cap-metric-accent" : "")}>{value}</div>
    </div>
  );
}

const css = `
  .cap-backdrop {
    position: fixed; inset: 0;
    background: rgba(15, 19, 24, 0.35);
    z-index: 900;
    animation: cap-fade 140ms ease-out;
  }
  @keyframes cap-fade { from { opacity: 0; } to { opacity: 1; } }

  .cap-panel {
    position: fixed; right: 0; top: 0; bottom: 0;
    width: 420px; max-width: 92vw;
    background: ${IVORY};
    border-left: 3px solid ${GOLD};
    box-shadow: -12px 0 32px rgba(0,0,0,0.12);
    font-family: "DM Sans", -apple-system, sans-serif;
    color: ${INK};
    display: flex; flex-direction: column;
    overflow-y: auto;
    z-index: 901;
    animation: cap-slide 180ms ease-out;
  }
  @keyframes cap-slide {
    from { transform: translateX(20px); opacity: 0; }
    to   { transform: translateX(0);    opacity: 1; }
  }

  .cap-header {
    display: flex; align-items: flex-start; justify-content: space-between;
    gap: 12px;
    padding: 16px 18px 14px;
    border-bottom: 1px solid ${BORDER};
    position: sticky; top: 0;
    background: ${IVORY};
    z-index: 2;
  }
  .cap-eyebrow {
    font-size: 10px; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; color: ${GOLD};
  }
  .cap-title {
    font-size: 16px; font-weight: 700; margin-top: 3px;
    line-height: 1.2;
  }
  .cap-sub {
    font-size: 11.5px; color: ${MUTED}; margin-top: 3px;
    font-family: "JetBrains Mono", ui-monospace, monospace;
  }
  .cap-close {
    background: transparent; border: none; cursor: pointer;
    font-size: 22px; line-height: 1; color: ${MUTED};
    padding: 0 4px;
  }
  .cap-close:hover { color: ${INK}; }

  .cap-section {
    padding: 14px 18px;
    border-bottom: 1px solid ${BORDER};
  }
  .cap-section-title {
    font-size: 10px; font-weight: 700; letter-spacing: 0.08em;
    text-transform: uppercase; color: ${MUTED};
    margin-bottom: 10px;
  }
  .cap-loading, .cap-error {
    font-size: 13px; color: ${MUTED};
  }
  .cap-error { color: #DA1E28; }

  .cap-metric-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
    margin-bottom: 14px;
  }
  .cap-metric {
    padding: 10px 12px;
    background: white;
    border: 1px solid ${BORDER};
    border-radius: 6px;
  }
  .cap-metric-lbl {
    font-size: 9.5px; font-weight: 700; letter-spacing: 0.06em;
    text-transform: uppercase; color: ${MUTED};
  }
  .cap-metric-val {
    font-family: "JetBrains Mono", ui-monospace, monospace;
    font-size: 17px; font-weight: 700; margin-top: 3px;
    font-variant-numeric: tabular-nums;
  }
  .cap-metric-accent { color: ${GOLD}; }

  .cap-bar-wrap { margin-top: 4px; }
  .cap-bar-label {
    display: flex; justify-content: space-between; align-items: center;
    font-size: 11px; margin-bottom: 4px;
  }
  .cap-bar-track {
    height: 6px; background: rgba(15,19,24,0.08);
    border-radius: 3px; overflow: hidden;
  }
  .cap-bar-fill { height: 100%; transition: width 180ms ease; }
  .cap-bar-sub {
    font-size: 10px; color: ${MUTED};
    font-family: "JetBrains Mono", ui-monospace, monospace;
    margin-top: 5px;
  }

  .cap-empty {
    font-size: 12px; color: ${MUTED};
    padding: 14px 12px; background: white;
    border: 1px dashed ${BORDER}; border-radius: 6px; text-align: center;
  }

  .cap-list { list-style: none; margin: 0; padding: 0; }
  .cap-list-item {
    display: flex; justify-content: space-between; align-items: flex-start; gap: 12px;
    padding: 9px 0;
    border-bottom: 1px dashed ${BORDER};
    font-size: 12.5px;
  }
  .cap-list-item:last-child { border-bottom: none; }
  .cap-list-main { min-width: 0; flex: 1; }
  .cap-list-name {
    font-weight: 600; display: block;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .cap-list-meta {
    font-size: 10.5px; color: ${MUTED}; margin-top: 2px;
    font-family: "JetBrains Mono", ui-monospace, monospace;
  }
  .cap-list-fin {
    text-align: right; flex-shrink: 0;
    font-family: "JetBrains Mono", ui-monospace, monospace;
    font-size: 13px; font-weight: 700;
  }
  .cap-list-sub {
    display: block; font-size: 10.5px; color: ${MUTED}; font-weight: 500;
  }

  .cap-stress { list-style: none; margin: 0; padding: 0; }
  .cap-stress-row {
    padding: 10px 12px;
    background: white;
    border: 1px solid ${BORDER}; border-radius: 6px;
    margin-bottom: 8px;
  }
  .cap-stress-row:last-child { margin-bottom: 0; }
  .cap-stress-head {
    display: flex; justify-content: space-between; align-items: baseline;
    font-size: 12.5px;
  }
  .cap-stress-name { font-weight: 600; }
  .cap-stress-delta {
    font-family: "JetBrains Mono", ui-monospace, monospace;
    font-weight: 700;
  }
  .cap-stress-delta.neg { color: #DA1E28; }
  .cap-stress-desc {
    font-size: 11.5px; color: ${MUTED}; line-height: 1.45;
    margin-top: 3px;
  }
  .cap-stress-sub {
    font-size: 10.5px; color: ${MUTED}; margin-top: 4px;
    font-family: "JetBrains Mono", ui-monospace, monospace;
  }

  .cap-actions {
    padding: 14px 18px 20px;
  }
  .cap-btn {
    width: 100%;
    padding: 10px 14px;
    background: ${INK}; color: ${IVORY};
    border: none; border-radius: 8px;
    font: inherit; font-weight: 600; font-size: 13px;
    cursor: pointer;
    transition: transform 100ms ease, box-shadow 100ms ease;
  }
  .cap-btn:hover {
    background: #24282F;
    transform: translateY(-1px);
    box-shadow: 0 3px 8px rgba(0,0,0,0.14);
  }
`;
