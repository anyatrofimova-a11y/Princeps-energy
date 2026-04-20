import React, { useEffect, useState } from "react";
import Dashboard from "./Dashboard";

/* ──────────────────────────────────────────────────────────────────────
   MissionControl — lender-grade portfolio landing surface.

   2026-04-19 redesign: the top area now renders the `Dashboard` component's
   3-card hero (Portfolio KPI · Stage funnel · Recent activity) followed by
   the active-projects table. The former empty-state workload picker is
   kept as a first-run experience for brand-new accounts.
   ────────────────────────────────────────────────────────────────────── */

const COLORS = {
  gold: "var(--gold, #F5B731)",
  helper: "var(--cds-text-helper, #6B7280)",
  body: "#0F1318",
  border: "#E5E7EB",
  surface: "#FFFFFF",
  shimmer: "#F2F3F5",
};

const FONT_BODY = "'DM Sans', -apple-system, sans-serif";
const FONT_MONO = "var(--mono, ui-monospace, 'SF Mono', Menlo, monospace)";

const WORKLOAD_PICKER = [
  { id: "solar",  icon: "\u2600",        label: "Solar",       desc: "Utility-scale PV" },
  { id: "bess",   icon: "\uD83D\uDD0B",  label: "BESS",        desc: "Battery storage" },
  { id: "dc",     icon: "\uD83C\uDFE2",  label: "Data Centre", desc: "Hyperscale / colo" },
  { id: "wind",   icon: "\uD83C\uDF2C",  label: "Wind",        desc: "Onshore turbines" },
  { id: "hybrid", icon: "\u26A1",        label: "Hybrid",      desc: "Co-located mix" },
];

function EmptyStatePicker({ onPick }) {
  const [hover, setHover] = useState(null);
  return (
    <div style={{
      minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
      background: COLORS.shimmer, fontFamily: FONT_BODY, padding: 32,
    }}>
      <div style={{
        background: COLORS.surface, borderRadius: 6, padding: 48,
        maxWidth: 880, width: "100%", boxShadow: "0 1px 3px rgba(15,19,24,0.06)",
        border: `1px solid ${COLORS.border}`,
      }}>
        <div style={{
          fontSize: 10, letterSpacing: 2, textTransform: "uppercase",
          color: COLORS.gold, fontWeight: 600, marginBottom: 10,
        }}>Welcome to Princeps</div>
        <h1 style={{
          fontSize: 28, fontWeight: 600, color: COLORS.body, margin: 0,
          letterSpacing: "-0.5px",
        }}>What are you developing?</h1>
        <div style={{ color: COLORS.helper, fontSize: 14, marginTop: 8, marginBottom: 32 }}>
          Pick your primary workload. You can change this per-project later.
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12 }}>
          {WORKLOAD_PICKER.map(w => (
            <button
              key={w.id}
              type="button"
              onClick={() => onPick(w.id)}
              onMouseEnter={() => setHover(w.id)}
              onMouseLeave={() => setHover(null)}
              style={{
                background: hover === w.id ? "#FFFBF0" : COLORS.surface,
                border: `1px solid ${hover === w.id ? COLORS.gold : COLORS.border}`,
                borderRadius: 4, padding: "20px 12px", cursor: "pointer",
                textAlign: "center", fontFamily: FONT_BODY,
                transition: "all 120ms ease",
              }}
            >
              <div style={{ fontSize: 26, marginBottom: 8 }}>{w.icon}</div>
              <div style={{ fontWeight: 600, fontSize: 13, color: COLORS.body }}>{w.label}</div>
              <div style={{ fontSize: 11, color: COLORS.helper, marginTop: 3 }}>{w.desc}</div>
            </button>
          ))}
        </div>

        <div style={{
          marginTop: 32, paddingTop: 20, borderTop: `1px solid ${COLORS.border}`,
          fontSize: 11, color: COLORS.helper, letterSpacing: 1, textTransform: "uppercase",
        }}>
          Or press <kbd style={{
            background: COLORS.shimmer, padding: "2px 6px", borderRadius: 3,
            fontFamily: FONT_MONO, fontSize: 10, marginLeft: 4,
          }}>&#8984;K</kbd> to search
        </div>
      </div>
    </div>
  );
}

export default function MissionControl({
  onSelectProject = () => {},
  onSelectEntity = null,
  onNewProject = () => {},
  onPickWorkload = () => {},
}) {
  // Lightweight probe — is the portfolio empty? If so, show the workload
  // picker. Dashboard itself also handles loading/error internally.
  const [totalProjects, setTotalProjects] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/portfolios/mission-control");
        if (!res.ok) return;
        const json = await res.json();
        if (!cancelled) setTotalProjects(json?.metrics?.total_projects ?? null);
      } catch {
        // Dashboard will render an error state on its own.
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (totalProjects === 0) {
    return <EmptyStatePicker onPick={onPickWorkload} />;
  }

  const handleOpenInbox = () => window.dispatchEvent(new CustomEvent("princeps-inbox-open"));

  return (
    <Dashboard
      onSelectProject={onSelectProject}
      onSelectEntity={onSelectEntity}
      onNewProject={onNewProject}
      onOpenInbox={handleOpenInbox}
    />
  );
}
