import React, { useEffect, useState } from "react";

/**
 * LPAPulse — numerical Local Planning Authority risk-and-receptivity score.
 *
 * Modelled on Paces' Permitting Predictor pattern: a single 0-100 chip on
 * every site card, expandable to a full breakdown card.
 *
 * Modes:
 *   <LPAPulse lpaName="…" workloadType="solar" mode="chip" />
 *   <LPAPulse lpaName="…" workloadType="solar" mode="card" />
 *
 * Backend: GET /api/lpa-pulse?lpa_name=…&workload_type=…
 * Today the backend is stubbed (deterministic-from-name); footer flags this.
 */

const TIER_COLOURS = {
  good: { fg: "#1E7B3A", bg: "#DEF7E5", dot: "#1E7B3A" },
  ok:   { fg: "#92660A", bg: "#FFF4D6", dot: "#92660A" },
  bad:  { fg: "#B23B3B", bg: "#FCE5E5", dot: "#B23B3B" },
};

const STANCE_LABELS = {
  supportive: "Supportive",
  neutral: "Neutral",
  resistant: "Resistant",
};

export default function LPAPulse({ lpaName, workloadType = "solar", mode = "chip" }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const [live, setLive] = useState(false);

  useEffect(() => {
    if (!lpaName) { setLoading(false); return; }
    let cancelled = false;
    setLoading(true);
    setError(null);
    const url = `/api/lpa-pulse?lpa_name=${encodeURIComponent(lpaName)}&workload_type=${encodeURIComponent(workloadType)}&live=${live ? "true" : "false"}`;
    fetch(url)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(d => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch(e => { if (!cancelled) { setError(e.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [lpaName, workloadType, live]);

  const styleBlock = (
    <style>{`
      .lpa-pulse { font-family: 'DM Sans', system-ui, sans-serif; color: var(--ink, #1a1a1a); }
      .lpa-pulse-chip {
        display: inline-flex; align-items: center; gap: 8px;
        padding: 6px 12px; border-radius: 999px;
        background: #F7F4EC; border: 1px solid #E6DFCF;
        font-size: 13px; cursor: pointer; user-select: none;
        transition: background 120ms ease;
      }
      .lpa-pulse-chip:hover { background: #F0EADA; }
      .lpa-pulse-chip-dot { width: 8px; height: 8px; border-radius: 50%; }
      .lpa-pulse-chip-eyebrow { color: var(--cds-text-helper, #6b6b6b); font-size: 11px; letter-spacing: 0.04em; text-transform: uppercase; }
      .lpa-pulse-chip-score { font-weight: 600; }
      .lpa-pulse-chip-label { font-weight: 500; }

      .lpa-pulse-popover {
        position: absolute; z-index: 50; margin-top: 8px;
        background: #fff; border: 1px solid #E6DFCF; border-radius: 12px;
        padding: 16px; width: 320px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.08);
      }

      .lpa-pulse-card {
        background: #fff; border: 1px solid #E6DFCF; border-radius: 16px;
        padding: 24px; max-width: 520px;
      }
      .lpa-pulse-eyebrow {
        font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;
        color: var(--cds-text-helper, #6b6b6b); font-weight: 500;
      }
      .lpa-pulse-name { font-size: 20px; font-weight: 600; margin: 4px 0 16px; }
      .lpa-pulse-score-big {
        font-size: 48px; line-height: 1; font-weight: 600; letter-spacing: -0.02em;
      }
      .lpa-pulse-score-label { margin-top: 4px; font-size: 14px; font-weight: 500; }
      .lpa-pulse-grid {
        display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
        margin: 20px 0; padding: 16px; background: #FAF8F2; border-radius: 8px;
      }
      .lpa-pulse-cell-label {
        font-size: 11px; letter-spacing: 0.04em; text-transform: uppercase;
        color: var(--cds-text-helper, #6b6b6b);
      }
      .lpa-pulse-cell-value {
        font-size: 16px; font-weight: 600; margin-top: 2px;
      }
      .lpa-pulse-narrative {
        font-size: 14px; line-height: 1.5; color: var(--ink, #1a1a1a);
        margin: 0 0 16px;
      }
      .lpa-pulse-footer {
        display: flex; justify-content: space-between; align-items: center;
        padding-top: 12px; border-top: 1px solid #EFE9D8;
        font-size: 11px; color: var(--cds-text-helper, #6b6b6b);
      }
      .lpa-pulse-shimmer {
        background: linear-gradient(90deg, #F0EADA 25%, #F7F4EC 50%, #F0EADA 75%);
        background-size: 200% 100%; animation: lpa-pulse-shimmer 1.4s infinite;
        border-radius: 6px;
      }
      @keyframes lpa-pulse-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
      .lpa-pulse-error { font-size: 12px; color: var(--cds-text-helper, #6b6b6b); font-style: italic; }
    `}</style>
  );

  // ── Loading / error states ────────────────────────────────────────────
  if (loading) {
    return (
      <div className="lpa-pulse">
        {styleBlock}
        {mode === "chip"
          ? <div className="lpa-pulse-shimmer" style={{ height: 28, width: 180 }} />
          : <div className="lpa-pulse-card">
              <div className="lpa-pulse-shimmer" style={{ height: 14, width: 80, marginBottom: 8 }} />
              <div className="lpa-pulse-shimmer" style={{ height: 22, width: 220, marginBottom: 16 }} />
              <div className="lpa-pulse-shimmer" style={{ height: 56, width: 120, marginBottom: 16 }} />
              <div className="lpa-pulse-shimmer" style={{ height: 88, width: "100%", marginBottom: 12 }} />
              <div className="lpa-pulse-shimmer" style={{ height: 40, width: "100%" }} />
            </div>}
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="lpa-pulse">
        {styleBlock}
        <span className="lpa-pulse-error">LPA Pulse unavailable</span>
      </div>
    );
  }

  const tier = TIER_COLOURS[data.tier] || TIER_COLOURS.ok;
  const b = data.breakdown || {};

  // ── Mode A: chip ──────────────────────────────────────────────────────
  if (mode === "chip") {
    return (
      <div className="lpa-pulse" style={{ position: "relative", display: "inline-block" }}>
        {styleBlock}
        <div
          className="lpa-pulse-chip"
          onClick={() => setExpanded(e => !e)}
          role="button"
          tabIndex={0}
        >
          <span className="lpa-pulse-chip-dot" style={{ background: tier.dot }} />
          <span className="lpa-pulse-chip-eyebrow">LPA Pulse</span>
          <span className="lpa-pulse-chip-score" style={{ color: tier.fg }}>{data.score}</span>
          <span className="lpa-pulse-chip-label" style={{ color: tier.fg }}>{data.score_label}</span>
        </div>
        {expanded && (
          <div className="lpa-pulse-popover">
            <div className="lpa-pulse-eyebrow">LPA Pulse</div>
            <div style={{ fontSize: 14, fontWeight: 600, margin: "4px 0 10px" }}>{data.lpa_name}</div>
            <div className="lpa-pulse-grid" style={{ margin: "0 0 12px" }}>
              <div>
                <div className="lpa-pulse-cell-label">Approval rate</div>
                <div className="lpa-pulse-cell-value">{b.approval_rate_pct}%</div>
              </div>
              <div>
                <div className="lpa-pulse-cell-label">Median decision</div>
                <div className="lpa-pulse-cell-value">{b.median_decision_days}d</div>
              </div>
              <div>
                <div className="lpa-pulse-cell-label">Decisions 12mo</div>
                <div className="lpa-pulse-cell-value">{b.recent_decisions_12mo}</div>
              </div>
              <div>
                <div className="lpa-pulse-cell-label">Stance</div>
                <div className="lpa-pulse-cell-value">{STANCE_LABELS[b.political_stance] || b.political_stance}</div>
              </div>
            </div>
            <div style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cds-text-helper, #6b6b6b)" }}>
              {data.narrative}
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── Mode B: full card ─────────────────────────────────────────────────
  const bigColour = data.tier === "good" ? "var(--gold, #D4A018)"
                    : data.tier === "bad" ? "#B23B3B"
                    : "var(--ink, #1a1a1a)";
  return (
    <div className="lpa-pulse">
      {styleBlock}
      <div className="lpa-pulse-card">
        <div className="lpa-pulse-eyebrow">LPA Pulse</div>
        <h3 className="lpa-pulse-name">{data.lpa_name}</h3>

        <div className="lpa-pulse-score-big" style={{ color: bigColour }}>{data.score}</div>
        <div className="lpa-pulse-score-label" style={{ color: tier.fg }}>{data.score_label}</div>

        <div className="lpa-pulse-grid">
          <div>
            <div className="lpa-pulse-cell-label">Approval rate</div>
            <div className="lpa-pulse-cell-value">{b.approval_rate_pct}%</div>
          </div>
          <div>
            <div className="lpa-pulse-cell-label">Median decision</div>
            <div className="lpa-pulse-cell-value">{b.median_decision_days} days</div>
          </div>
          <div>
            <div className="lpa-pulse-cell-label">Recent decisions</div>
            <div className="lpa-pulse-cell-value">{b.recent_decisions_12mo} (12mo)</div>
          </div>
          <div>
            <div className="lpa-pulse-cell-label">Political stance</div>
            <div className="lpa-pulse-cell-value">{STANCE_LABELS[b.political_stance] || b.political_stance}</div>
          </div>
        </div>

        <p className="lpa-pulse-narrative">{data.narrative}</p>

        {/* Live-scrape toggle (card mode only) */}
        <div style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          padding: "10px 0", borderTop: "1px solid #EFE9D8",
          fontSize: 12, color: "#6b6b6b",
        }}>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={live}
              onChange={e => setLive(e.target.checked)}
              style={{ accentColor: "#D4A018" }}
            />
            Use live scrape
          </label>
          {live && (
            <span style={{ fontSize: 11, color: "#92660A" }}>
              real council-portal data via firecrawl-lean
            </span>
          )}
        </div>

        <div className="lpa-pulse-footer">
          <span>{data.evidence_count} evidence items</span>
          <span>{_formatSourceFooter(data)}</span>
        </div>
      </div>
    </div>
  );
}

// Footer helper — small grey one-liner that explains where the data came from.
function _formatSourceFooter(data) {
  const src = data && data.source ? String(data.source) : "synthetic";
  // Format the fetched_at as HH:MM today (or just date if not today)
  let when = "";
  if (data && data.fetched_at) {
    try {
      const d = new Date(data.fetched_at);
      const now = new Date();
      const sameDay = d.toDateString() === now.toDateString();
      const hh = String(d.getHours()).padStart(2, "0");
      const mm = String(d.getMinutes()).padStart(2, "0");
      when = sameDay ? `${hh}:${mm} today` : d.toISOString().slice(0, 10);
    } catch { /* ignore */ }
  }
  if (src.startsWith("firecrawl") || src.includes("live")) {
    return `LPA Pulse · firecrawl live${when ? " · " + when : ""}`;
  }
  if (src.startsWith("direct httpx")) {
    return `LPA Pulse · live scrape (httpx fallback)${when ? " · " + when : ""}`;
  }
  if (src.startsWith("synthetic (firecrawl failed")) {
    // Show the reason but keep it short.
    const reason = src.replace(/^synthetic \(firecrawl failed:\s*/, "").replace(/\)$/, "");
    return `LPA Pulse · synthetic — live failed (${reason.slice(0, 48)})`;
  }
  return "LPA Pulse · synthetic — toggle live for real data";
}
