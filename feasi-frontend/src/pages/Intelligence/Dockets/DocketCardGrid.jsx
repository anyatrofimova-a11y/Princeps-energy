import React from "react";
import {
  CASE_TYPE_CHIP,
  STATUS_PILL,
  COLOURS,
  MONO,
  SANS,
  formatDate,
} from "./tokens";

// Middle list — 72px rows. One card per docket.
export default function DocketCardGrid({
  dockets = [],
  loading,
  selectedId,
  onSelect,
  onTogglePin,
  onToggleWatch,
}) {
  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        overflowY: "auto",
        background: COLOURS.bg,
        fontFamily: SANS,
      }}
    >
      <div
        style={{
          position: "sticky",
          top: 0,
          zIndex: 2,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 20px",
          background: COLOURS.bg,
          borderBottom: `1px solid ${COLOURS.border}`,
        }}
      >
        <div style={{ fontSize: 13, color: COLOURS.inkSoft }}>
          <strong style={{ color: COLOURS.ink }}>{dockets.length}</strong> dockets
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: COLOURS.muted }}>
          <span>Sort by</span>
          <select
            style={{
              padding: "4px 6px",
              border: `1px solid ${COLOURS.border}`,
              borderRadius: 4,
              background: "#FFFFFF",
              fontSize: 12,
              fontFamily: SANS,
              color: COLOURS.ink,
            }}
            defaultValue="last_activity"
          >
            <option value="last_activity">Last activity</option>
            <option value="date_opened">Date opened</option>
            <option value="next_deadline">Next deadline</option>
            <option value="capacity_mw">Capacity MW</option>
          </select>
        </div>
      </div>

      {loading && (
        <div style={{ padding: 24, color: COLOURS.muted, fontSize: 13 }}>Loading dockets…</div>
      )}

      {!loading && dockets.length === 0 && (
        <div style={{ padding: 40, textAlign: "center", color: COLOURS.muted, fontSize: 13 }}>
          No dockets match your filters.
        </div>
      )}

      {dockets.map((d) => (
        <DocketRow
          key={d.id}
          docket={d}
          selected={d.id === selectedId}
          onSelect={() => onSelect && onSelect(d)}
          onTogglePin={(e) => {
            e.stopPropagation();
            onTogglePin && onTogglePin(d);
          }}
          onToggleWatch={(e) => {
            e.stopPropagation();
            onToggleWatch && onToggleWatch(d);
          }}
        />
      ))}
    </div>
  );
}

function DocketRow({ docket, selected, onSelect, onTogglePin, onToggleWatch }) {
  const chip = CASE_TYPE_CHIP[docket.case_type] || CASE_TYPE_CHIP.LPA_PLANNING;
  const status = STATUS_PILL[docket.status] || STATUS_PILL.open;
  return (
    <div
      onClick={onSelect}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 14,
        height: 72,
        padding: "0 20px",
        background: selected ? "rgba(245,183,49,.08)" : "#FFFFFF",
        borderBottom: `1px solid ${COLOURS.border}`,
        borderLeft: `3px solid ${selected ? COLOURS.gold : "transparent"}`,
        cursor: "pointer",
        fontFamily: SANS,
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = selected ? "rgba(245,183,49,.12)" : COLOURS.ivory)}
      onMouseLeave={(e) => (e.currentTarget.style.background = selected ? "rgba(245,183,49,.08)" : "#FFFFFF")}
    >
      {/* Case type chip */}
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          padding: "3px 8px",
          fontSize: 10.5,
          fontWeight: 600,
          color: chip.fg,
          background: chip.bg,
          border: `1px solid ${chip.border}`,
          borderRadius: 4,
          letterSpacing: 0.3,
          textTransform: "uppercase",
          whiteSpace: "nowrap",
          flexShrink: 0,
        }}
      >
        {chip.label}
      </span>

      {/* Docket number */}
      <span
        style={{
          fontFamily: MONO,
          fontSize: 12,
          fontWeight: 600,
          color: COLOURS.ink,
          minWidth: 100,
          flexShrink: 0,
        }}
      >
        {docket.docket_number}
      </span>

      {/* Publisher · title */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 13.5,
            fontWeight: 600,
            color: COLOURS.ink,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {docket.title}
        </div>
        <div style={{ fontSize: 11.5, color: COLOURS.muted, marginTop: 1 }}>
          {docket.publisher} · {docket.applicant || docket.stage}
        </div>
      </div>

      {/* Status pill */}
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          padding: "2px 8px",
          fontSize: 10.5,
          fontWeight: 600,
          color: status.fg,
          background: status.bg,
          borderRadius: 10,
          textTransform: "uppercase",
          letterSpacing: 0.4,
          flexShrink: 0,
        }}
      >
        {status.label}
      </span>

      {/* Counts */}
      <div style={{ display: "flex", gap: 12, fontFamily: MONO, fontSize: 11, color: COLOURS.muted, flexShrink: 0 }}>
        <span title="Stakeholders">{docket.n_stakeholders} sh</span>
        <span title="Documents">{docket.n_documents} doc</span>
        <span title="Last activity">{formatDate(docket.last_activity)}</span>
      </div>

      {/* Watch / Pin */}
      <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
        <IconButton
          active={!!docket.watched}
          onClick={onToggleWatch}
          title={docket.watched ? "Unwatch" : "Watch"}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill={docket.watched ? COLOURS.gold : "none"} stroke={docket.watched ? COLOURS.gold : COLOURS.muted} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
            <path d="M1 8s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5z" />
            <circle cx="8" cy="8" r="2" />
          </svg>
        </IconButton>
        <IconButton
          active={!!docket.pinned}
          onClick={onTogglePin}
          title={docket.pinned ? "Unpin" : "Pin"}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill={docket.pinned ? COLOURS.gold : "none"} stroke={docket.pinned ? COLOURS.gold : COLOURS.muted} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 2h6l-1 4 3 3h-5v4l-1 1-1-1v-4H3l3-3z" />
          </svg>
        </IconButton>
      </div>
    </div>
  );
}

function IconButton({ active, onClick, title, children }) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        width: 28,
        height: 28,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        background: active ? "rgba(245,183,49,.12)" : "transparent",
        border: `1px solid ${active ? COLOURS.gold : COLOURS.border}`,
        borderRadius: 4,
        cursor: "pointer",
        padding: 0,
      }}
    >
      {children}
    </button>
  );
}
