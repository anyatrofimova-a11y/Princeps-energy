/**
 * DCLiveOpsStrip — floating "LIVE" ribbon of ops metrics pinned to the
 * DCDesignTwin overlay. Ticks every 5 s via `subscribeDcOps()` which uses
 * the WebSocket /ws/dc-ops when it exists and falls back to 30s HTTP poll
 * or a deterministic client-side simulator (for demos without backend).
 *
 *   ┌──── Live · DC-Ops ──────────────────────────────────────┐
 *   │ PUE 1.22  ·  IT 74.3%  ·  Cooling 11.8 MW  ·  H2O 33 L/m │
 *   └─────────────────────────────────────────────────────────┘
 */
import React, { useEffect, useRef, useState } from "react";
import { subscribeDcOps } from "../../api/dcOps";

export default function DCLiveOpsStrip({ itLoadMw = 50, visible = true, onClose = null }) {
  const [tick, setTick] = useState(null);
  const [history, setHistory] = useState([]);
  const unsubRef = useRef(null);

  useEffect(() => {
    if (!visible) return undefined;
    unsubRef.current = subscribeDcOps({
      itLoadMw,
      onTick: (t) => {
        setTick(t);
        setHistory(h => {
          const next = [...h, t];
          return next.length > 60 ? next.slice(-60) : next;
        });
      },
    });
    return () => {
      try { unsubRef.current?.(); } catch { /* noop */ }
      unsubRef.current = null;
    };
  }, [visible, itLoadMw]);

  if (!visible) return null;

  const pueColor = tick?.pue <= 1.25 ? "#10b981" : tick?.pue <= 1.4 ? "#f5b731" : "#ef4444";

  return (
    <div style={{
      position: "absolute",
      bottom: 12,
      right: 12,
      minWidth: 360,
      background: "rgba(15,23,42,0.92)",
      color: "#f1f5f9",
      borderRadius: 10,
      padding: "10px 14px",
      fontFamily: '"DM Sans", sans-serif',
      fontSize: 12,
      boxShadow: "0 8px 24px rgba(0,0,0,0.45)",
      backdropFilter: "blur(8px)",
      zIndex: 6,
      border: "1px solid rgba(245,183,49,0.35)",
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{
            width: 8, height: 8, borderRadius: 4,
            background: "#ef4444",
            animation: "dcOpsPulse 1.6s ease-in-out infinite",
          }} />
          <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: 1, textTransform: "uppercase", color: "#fca5a5" }}>
            Live · DC-Ops
          </span>
          {tick && (
            <span style={{ fontSize: 9, color: "#94a3b8", fontFamily: '"JetBrains Mono", monospace' }}>
              {new Date(tick.ts).toLocaleTimeString()}
            </span>
          )}
        </div>
        {onClose && (
          <button onClick={onClose} style={{
            background: "none", border: "none", color: "#94a3b8",
            cursor: "pointer", padding: 0, fontSize: 16, lineHeight: 1,
          }}>×</button>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 10 }}>
        <Metric label="PUE" value={tick ? tick.pue.toFixed(3) : "—"} colour={pueColor} />
        <Metric label="IT Load" value={tick ? `${tick.it_load_pct.toFixed(1)}%` : "—"} colour="#60a5fa" />
        <Metric label="Cooling" value={tick ? `${tick.cooling_mw.toFixed(1)} MW` : "—"} colour="#22d3ee" />
        <Metric label="H₂O" value={tick ? `${tick.water_lpm.toFixed(0)} L/m` : "—"} colour="#a78bfa" />
      </div>

      {/* Spark bar for PUE trend — last 60 ticks (~5 min if WS, ~30 min if polling). */}
      {history.length > 1 && (
        <div style={{
          marginTop: 8, height: 16,
          display: "flex", alignItems: "flex-end", gap: 1,
          borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: 4,
        }}>
          {history.slice(-60).map((h, i) => {
            const pueNorm = Math.max(0, Math.min(1, (h.pue - 1.1) / 0.4));
            return (
              <div key={i} style={{
                flex: 1, height: `${4 + pueNorm * 10}px`,
                background: h.pue > 1.4 ? "#ef4444" : h.pue > 1.25 ? "#f5b731" : "#10b981",
                borderRadius: 1,
              }} />
            );
          })}
        </div>
      )}

      <style>{`
        @keyframes dcOpsPulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50%      { opacity: 0.35; transform: scale(1.3); }
        }
      `}</style>
    </div>
  );
}

function Metric({ label, value, colour }) {
  return (
    <div style={{ textAlign: "left" }}>
      <div style={{ fontSize: 8, color: "#94a3b8", letterSpacing: 0.6, textTransform: "uppercase", fontWeight: 700 }}>
        {label}
      </div>
      <div style={{
        fontSize: 15, fontWeight: 700, color: colour,
        fontFamily: '"JetBrains Mono", monospace',
        lineHeight: 1.25,
      }}>
        {value}
      </div>
    </div>
  );
}
