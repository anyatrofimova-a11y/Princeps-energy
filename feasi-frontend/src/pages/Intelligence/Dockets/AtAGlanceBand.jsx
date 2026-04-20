import React from "react";
import { COLOURS, MONO, SANS, countdownStyle, formatDate, daysFromNow } from "./tokens";

// 7-tile strip sitting under the sub-nav.
export default function AtAGlanceBand({ docket }) {
  if (!docket) return null;

  const dl = docket.next_deadline || {};
  const daysLeft = dl.days_left ?? daysFromNow(dl.date);
  const cdStyle = countdownStyle(daysLeft);

  const tiles = [
    { label: "Applicant", value: docket.applicant || "—" },
    { label: "Site", value: docket.site || "—" },
    {
      label: "Capacity",
      value: docket.capacity_mw != null ? (
        <span style={{ fontFamily: MONO, fontWeight: 700 }}>
          {docket.capacity_mw} <span style={{ fontSize: 11, fontWeight: 500, color: COLOURS.muted }}>MW</span>
        </span>
      ) : "—",
    },
    { label: "Stage", value: docket.stage || "—" },
    { label: "Opened", value: <span style={{ fontFamily: MONO }}>{formatDate(docket.date_opened)}</span> },
    {
      label: "Next deadline",
      value: dl.date ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: COLOURS.ink }}>{dl.label}</span>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              padding: "2px 8px",
              fontFamily: MONO,
              fontSize: 11,
              fontWeight: 700,
              color: cdStyle.fg,
              background: cdStyle.bg,
              border: `1.5px solid ${cdStyle.border}`,
              borderRadius: 10,
              boxShadow: cdStyle.boxShadow || "none",
              animation: cdStyle.animation || "none",
            }}
          >
            {daysLeft != null ? (daysLeft > 0 ? `${daysLeft}d` : daysLeft === 0 ? "today" : `${-daysLeft}d past`) : "TBC"}
          </span>
        </div>
      ) : "—",
    },
    {
      label: "Days in examination",
      value: (
        <span style={{ fontFamily: MONO, fontWeight: 700 }}>
          {docket.days_in_examination != null ? docket.days_in_examination : 0}
          <span style={{ fontSize: 11, fontWeight: 500, color: COLOURS.muted, marginLeft: 4 }}>days</span>
        </span>
      ),
    },
  ];

  return (
    <>
      <style>
        {`@keyframes princeps-pulse { 0%,100% { box-shadow: 0 0 0 2px rgba(184,74,74,.25); } 50% { box-shadow: 0 0 0 4px rgba(184,74,74,.08); } }`}
      </style>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(7, minmax(0, 1fr))",
          gap: 1,
          background: COLOURS.border,
          border: `1px solid ${COLOURS.border}`,
          borderRadius: 8,
          overflow: "hidden",
          fontFamily: SANS,
        }}
      >
        {tiles.map((t) => (
          <div
            key={t.label}
            style={{
              background: "#FFFFFF",
              padding: "12px 14px",
              minHeight: 72,
              display: "flex",
              flexDirection: "column",
              gap: 4,
              minWidth: 0,
            }}
          >
            <div
              style={{
                fontSize: 10.5,
                color: COLOURS.muted,
                textTransform: "uppercase",
                letterSpacing: 0.5,
                fontWeight: 600,
              }}
            >
              {t.label}
            </div>
            <div
              style={{
                fontSize: 13,
                color: COLOURS.ink,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={typeof t.value === "string" ? t.value : undefined}
            >
              {t.value}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
