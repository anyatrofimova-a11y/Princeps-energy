import React from "react";
import { CASE_TYPE_CHIP, STATUS_PILL, COLOURS, MONO, SANS } from "./tokens";

// 96 px header strip.
export default function DocketHeader({
  docket,
  onWatch,
  onPin,
  onShare,
}) {
  if (!docket) return null;
  const chip = CASE_TYPE_CHIP[docket.case_type] || CASE_TYPE_CHIP.LPA_PLANNING;
  const status = STATUS_PILL[docket.status] || STATUS_PILL.open;

  return (
    <div
      style={{
        height: 96,
        padding: "16px 24px",
        background: "#FFFFFF",
        borderBottom: `1px solid ${COLOURS.border}`,
        display: "flex",
        alignItems: "center",
        gap: 20,
        fontFamily: SANS,
      }}
    >
      {/* Docket number (monospace, large) */}
      <div style={{ flexShrink: 0 }}>
        <div style={{ fontSize: 10.5, color: COLOURS.muted, textTransform: "uppercase", letterSpacing: 0.5 }}>
          Docket
        </div>
        <div style={{ fontFamily: MONO, fontSize: 18, fontWeight: 700, color: COLOURS.ink }}>
          {docket.docket_number}
        </div>
      </div>

      {/* Title + metadata row */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span
            style={{
              padding: "3px 8px",
              fontSize: 10.5,
              fontWeight: 600,
              color: chip.fg,
              background: chip.bg,
              border: `1px solid ${chip.border}`,
              borderRadius: 4,
              letterSpacing: 0.3,
              textTransform: "uppercase",
            }}
          >
            {chip.label}
          </span>
          <span
            style={{
              padding: "2px 8px",
              fontSize: 10.5,
              fontWeight: 600,
              color: status.fg,
              background: status.bg,
              borderRadius: 10,
              textTransform: "uppercase",
              letterSpacing: 0.4,
            }}
          >
            {status.label}
          </span>
          <span
            style={{
              padding: "2px 8px",
              fontSize: 10.5,
              fontWeight: 500,
              color: COLOURS.inkSoft,
              background: "rgba(0,0,0,.04)",
              borderRadius: 10,
              textTransform: "uppercase",
              letterSpacing: 0.4,
            }}
          >
            {docket.industry}
          </span>
          <span style={{ fontSize: 11.5, color: COLOURS.muted }}>
            Publisher: <strong style={{ color: COLOURS.ink, fontWeight: 600 }}>{docket.publisher}</strong>
          </span>
        </div>
        <div
          style={{
            fontSize: 20,
            fontWeight: 700,
            color: COLOURS.ink,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {docket.title}
        </div>
      </div>

      {/* Home URL + actions */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
        {docket.home_url && (
          <a
            href={docket.home_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              fontSize: 11.5,
              color: COLOURS.muted,
              textDecoration: "none",
              padding: "4px 8px",
              border: `1px solid ${COLOURS.border}`,
              borderRadius: 4,
            }}
            title={docket.home_url}
          >
            Home ↗
          </a>
        )}
        <HeaderAction
          label={docket.watched ? "Watching" : "Watch"}
          active={!!docket.watched}
          onClick={onWatch}
          icon={
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
              <path d="M1 8s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5z" />
              <circle cx="8" cy="8" r="2" />
            </svg>
          }
        />
        <HeaderAction
          label={docket.pinned ? "Pinned" : "Pin"}
          active={!!docket.pinned}
          onClick={onPin}
          icon={
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 2h6l-1 4 3 3h-5v4l-1 1-1-1v-4H3l3-3z" />
            </svg>
          }
        />
        <HeaderAction
          label="Share"
          onClick={onShare}
          icon={
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 8a2 2 0 104 0 2 2 0 00-4 0zM10 4a2 2 0 100 4 2 2 0 000-4zM10 8a2 2 0 100 4 2 2 0 000-4z" />
              <path d="M5.8 7l3-2M5.8 9l3 2" />
            </svg>
          }
        />
      </div>
    </div>
  );
}

function HeaderAction({ label, active, icon, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "5px 10px",
        fontSize: 11.5,
        fontWeight: 600,
        color: active ? COLOURS.ink : COLOURS.inkSoft,
        background: active ? "rgba(245,183,49,.14)" : "#FFFFFF",
        border: `1px solid ${active ? COLOURS.gold : COLOURS.border}`,
        borderRadius: 4,
        cursor: "pointer",
        fontFamily: SANS,
      }}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}
