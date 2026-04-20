import React, { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTrackerStats } from "../../hooks/useTracker";
import TrackerMap from "./TrackerMap";
import TrackerTable from "./TrackerTable";
import ReviewQueue from "./ReviewQueue";
import PublishControls from "./PublishControls";
import TrackerDetail from "./TrackerDetail";

/* ─────────────────────────────────────────────────────────────────
   TrackerDashboard — authenticated internal dashboard at
   /tracker-admin. Segmented control switches between Map · Table ·
   Review Queue. Gold-accented header carries the total count and
   the PublishControls strip.

   Auth: no guard is wired here — plug the app-level guard in from
   main.jsx via the routes file (routes/trackerRoutes.jsx).
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

const TABS = [
  { id: "map",     label: "Map" },
  { id: "table",   label: "Table" },
  { id: "review",  label: "Review queue" },
];

export default function TrackerDashboard({ admin = true }) {
  const [tab, setTab] = useState("map");
  const { stats } = useTrackerStats();
  const { id: deepLinkId } = useParams() || {};
  const navigate = useNavigate();
  const [detailId, setDetailId] = useState(deepLinkId || null);

  // React to route-level /tracker-admin/review/:id deep links.
  useEffect(() => {
    if (deepLinkId) setDetailId(deepLinkId);
  }, [deepLinkId]);

  return (
    <div
      style={{
        height: "100vh",
        minHeight: 0,
        display: "flex",
        flexDirection: "column",
        background: C.ivory,
        color: C.ink,
        fontFamily: "'DM Sans', sans-serif",
      }}
    >
      {/* Header */}
      <header
        style={{
          flexShrink: 0,
          padding: "16px 24px 14px",
          borderBottom: `1px solid ${C.border}`,
          background: C.bg,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 14, flexWrap: "wrap" }}>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 800, letterSpacing: "-0.02em" }}>
              Substation Tracker
            </h1>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 10,
                color: C.tertiary,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
              }}
            >
              admin · SME review · dataset ops
            </span>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                padding: "4px 12px",
                borderRadius: 999,
                background: C.goldSurface,
                border: `1px solid ${C.goldBorder}`,
                color: C.ink,
              }}
            >
              <span
                style={{ width: 6, height: 6, borderRadius: 3, background: C.gold, display: "inline-block" }}
                aria-hidden
              />
              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, fontWeight: 700 }}>
                {stats?.total ?? "—"}
              </span>
              <span style={{ fontSize: 11, color: C.secondary }}>substations tracked</span>
            </span>
          </div>

          <SegmentedControl tab={tab} onTab={setTab} />
        </div>

        <PublishControls admin={admin} />
      </header>

      {/* Body — swap panels based on tab */}
      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
        {tab === "map" && <TrackerMap admin={admin} />}
        {tab === "table" && <TrackerTable admin={admin} />}
        {tab === "review" && <ReviewQueue admin={admin} />}
      </div>

      {/* Deep-link detail drawer — separate from per-tab drawers so
          the URL stays driveable. */}
      {deepLinkId && detailId && (
        <TrackerDetail
          id={detailId}
          admin={admin}
          onClose={() => {
            setDetailId(null);
            navigate("/tracker-admin");
          }}
        />
      )}
    </div>
  );
}

// ── Segmented control ──────────────────────────────────────────
function SegmentedControl({ tab, onTab }) {
  return (
    <div
      role="tablist"
      aria-label="Tracker sections"
      style={{
        display: "inline-flex",
        padding: 4,
        borderRadius: 10,
        background: "#F7F8FA",
        border: `1px solid ${C.border}`,
        gap: 2,
      }}
    >
      {TABS.map((t) => {
        const active = tab === t.id;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onTab(t.id)}
            style={{
              padding: "6px 14px",
              borderRadius: 8,
              fontSize: 13,
              fontWeight: active ? 700 : 600,
              fontFamily: "'DM Sans', sans-serif",
              letterSpacing: "-0.01em",
              color: active ? C.ink : C.secondary,
              background: active ? "#FFFFFF" : "transparent",
              border: active ? `1px solid ${C.goldBorder}` : "1px solid transparent",
              boxShadow: active ? "0 1px 2px rgba(15,19,24,0.05)" : "none",
              transition: "all 120ms ease",
              cursor: "pointer",
            }}
          >
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              {active && (
                <span
                  aria-hidden
                  style={{
                    width: 6, height: 6, borderRadius: 3,
                    background: C.gold,
                    display: "inline-block",
                  }}
                />
              )}
              {t.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
