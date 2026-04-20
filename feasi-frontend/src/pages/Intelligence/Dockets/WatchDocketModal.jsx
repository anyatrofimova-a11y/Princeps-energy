import React, { useState } from "react";
import { COLOURS, SANS } from "./tokens";
import api from "../../../api/dockets";

// Scope is fixed to "this docket". Cadence + filters + channels.
export default function WatchDocketModal({ open, docket, onClose }) {
  const [cadence, setCadence] = useState("daily");
  const [filters, setFilters] = useState({
    new_documents: true,
    status_change: true,
    new_stakeholder: true,
    deadline_7d: true,
  });
  const [channels, setChannels] = useState({ in_app: true, email: true, slack: false });
  const [saving, setSaving] = useState(false);

  if (!open || !docket) return null;

  const save = async () => {
    setSaving(true);
    await api.watchDocket(docket.id, { cadence, filters, channels });
    setSaving(false);
    onClose && onClose(true);
  };

  return (
    <Overlay onClose={onClose}>
      <ModalFrame onClose={onClose} title={`Watch: ${docket.docket_number}`} subtitle={docket.title}>
        <Group title="Cadence">
          <div style={{ display: "flex", gap: 6 }}>
            {[
              { v: "realtime", l: "Realtime" },
              { v: "daily",    l: "Daily" },
              { v: "weekly",   l: "Weekly" },
            ].map((o) => (
              <Pill key={o.v} active={cadence === o.v} onClick={() => setCadence(o.v)}>
                {o.l}
              </Pill>
            ))}
          </div>
        </Group>

        <Group title="Trigger filters">
          <Check label="New documents published" value={filters.new_documents}
            onChange={(v) => setFilters({ ...filters, new_documents: v })} />
          <Check label="Status / stage change" value={filters.status_change}
            onChange={(v) => setFilters({ ...filters, status_change: v })} />
          <Check label="New stakeholder joins" value={filters.new_stakeholder}
            onChange={(v) => setFilters({ ...filters, new_stakeholder: v })} />
          <Check label="Deadline within 7 days" value={filters.deadline_7d}
            onChange={(v) => setFilters({ ...filters, deadline_7d: v })} />
        </Group>

        <Group title="Channels">
          <Check label="In-app notifications" value={channels.in_app}
            onChange={(v) => setChannels({ ...channels, in_app: v })} />
          <Check label="Email" value={channels.email}
            onChange={(v) => setChannels({ ...channels, email: v })} />
          <Check label="Slack" value={channels.slack}
            onChange={(v) => setChannels({ ...channels, slack: v })} />
        </Group>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
          <button
            onClick={onClose}
            style={{
              padding: "7px 14px",
              fontSize: 12,
              fontWeight: 600,
              background: "#FFFFFF",
              color: COLOURS.ink,
              border: `1px solid ${COLOURS.border}`,
              borderRadius: 4,
              cursor: "pointer",
              fontFamily: SANS,
            }}
          >
            Cancel
          </button>
          <button
            onClick={save}
            disabled={saving}
            style={{
              padding: "7px 14px",
              fontSize: 12,
              fontWeight: 700,
              background: COLOURS.gold,
              color: COLOURS.ink,
              border: `1px solid ${COLOURS.gold}`,
              borderRadius: 4,
              cursor: saving ? "default" : "pointer",
              fontFamily: SANS,
            }}
          >
            {saving ? "Saving…" : "Save watch"}
          </button>
        </div>
      </ModalFrame>
    </Overlay>
  );
}

function Overlay({ children, onClose }) {
  return (
    <div
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose && onClose();
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,19,24,.45)",
        zIndex: 300,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        fontFamily: SANS,
      }}
    >
      {children}
    </div>
  );
}

function ModalFrame({ title, subtitle, children, onClose }) {
  return (
    <div
      style={{
        width: "100%",
        maxWidth: 540,
        background: "#FFFFFF",
        borderRadius: 10,
        boxShadow: "0 20px 60px rgba(0,0,0,.25)",
        display: "flex",
        flexDirection: "column",
        maxHeight: "85vh",
      }}
    >
      <div style={{ padding: "14px 20px", borderBottom: `1px solid ${COLOURS.border}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: COLOURS.ink }}>{title}</div>
          {subtitle && <div style={{ fontSize: 12, color: COLOURS.muted, marginTop: 2 }}>{subtitle}</div>}
        </div>
        <button
          onClick={onClose}
          style={{ width: 28, height: 28, background: "transparent", border: `1px solid ${COLOURS.border}`, borderRadius: 4, cursor: "pointer", color: COLOURS.muted, fontSize: 16, lineHeight: 1 }}
          aria-label="Close"
        >
          ×
        </button>
      </div>
      <div style={{ padding: 20, overflowY: "auto", flex: 1, display: "flex", flexDirection: "column", gap: 18 }}>
        {children}
      </div>
    </div>
  );
}

function Group({ title, children }) {
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 700, color: COLOURS.muted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
        {title}
      </div>
      {children}
    </div>
  );
}

function Pill({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "6px 12px",
        fontSize: 12,
        fontWeight: 600,
        background: active ? COLOURS.gold : "#FFFFFF",
        color: COLOURS.ink,
        border: `1px solid ${active ? COLOURS.gold : COLOURS.border}`,
        borderRadius: 20,
        cursor: "pointer",
        fontFamily: SANS,
      }}
    >
      {children}
    </button>
  );
}

function Check({ label, value, onChange }) {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0", cursor: "pointer", fontSize: 13, color: COLOURS.ink, fontFamily: SANS }}>
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
        style={{ width: 14, height: 14, accentColor: COLOURS.gold }}
      />
      {label}
    </label>
  );
}

export { Overlay, ModalFrame, Group, Pill, Check };
