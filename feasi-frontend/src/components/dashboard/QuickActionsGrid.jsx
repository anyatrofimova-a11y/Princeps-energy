import React from "react";

const ACTIONS = [
  {
    id: "feasibility",
    title: "Site Assessment",
    desc: "Score a site for solar, wind, BESS, or DC feasibility",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--gold)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
        <circle cx="12" cy="10" r="3" />
      </svg>
    ),
  },
  {
    id: "grid_study",
    title: "Grid Study",
    desc: "Analyse network capacity and connection options",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--gold)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M13 2L3 14h9l-1 10 10-12h-9l1-10z" />
      </svg>
    ),
  },
  {
    id: "financial",
    title: "Financial Model",
    desc: "NPV, IRR, LCOE, PPA pricing analysis",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--gold)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 3v18h18" />
        <path d="M7 16l4-8 4 4 5-6" />
      </svg>
    ),
  },
  {
    id: "report_generation",
    title: "Generate Report",
    desc: "PDF feasibility or grid connection report",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--gold)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
        <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" />
      </svg>
    ),
  },
  {
    id: "site_prospecting",
    title: "Parcel Search",
    desc: "Find and score land parcels at scale",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--gold)" strokeWidth="1.5" strokeLinecap="round">
        <circle cx="11" cy="11" r="8" />
        <path d="M21 21l-4.35-4.35" />
      </svg>
    ),
  },
  {
    id: "dispatch_optimisation",
    title: "System Optimizer",
    desc: "Optimal solar/wind/BESS sizing with MILP",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--gold)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
      </svg>
    ),
  },
];

export default function QuickActionsGrid({ onAction }) {
  return (
    <div className="pd3-enter-5" style={{ padding: "0 24px", marginBottom: 24 }}>
      <div className="pd3-section-label">Quick Actions</div>
      <div
        className="pd3-quick-grid"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 12,
        }}
      >
        {ACTIONS.map((a, i) => (
          <div
            key={a.id}
            className="pd3-quick-card"
            onClick={() => onAction(a.id)}
            style={{
              animation: `pd-fade-up 0.35s ease both`,
              animationDelay: `${250 + i * 50}ms`,
            }}
          >
            <div className="pd3-quick-icon">{a.icon}</div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)" }}>
                {a.title}
              </div>
              <div style={{ fontSize: 11, color: "var(--muted)", lineHeight: 1.4, marginTop: 3 }}>
                {a.desc}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
