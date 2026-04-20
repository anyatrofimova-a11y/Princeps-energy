import React, { useMemo, useState } from "react";

const C = {
  gold: "#F5B731",
  goldSoft: "#C9A64B",
  goldSurface: "rgba(245,183,49,0.10)",
  goldBorder: "rgba(245,183,49,0.30)",
  ink: "#0F1318",
  secondary: "#4B5563",
  tertiary: "#9C9590",
  border: "#E8EAED",
  bg: "#F7F8FA",
};

const CADENCE = {
  daily:       { bg: "rgba(34,160,107,0.12)", fg: "#22A06B",  label: "daily" },
  weekday:     { bg: "rgba(224,165,43,0.14)", fg: "#E0A52B",  label: "weekday" },
  weekly:      { bg: "rgba(46,111,239,0.12)", fg: "#2E6FEF",  label: "weekly" },
  "real-time": { bg: "transparent",           fg: "#E24A4A",  label: "real-time", outline: true },
};

const SOURCE_ORDER = ["Ofgem", "NESO", "PINS", "LPA", "DNO", "DESNZ"];

function CadencePill({ cadence }) {
  const spec = CADENCE[cadence] || CADENCE.weekly;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 10,
        fontSize: 10,
        fontWeight: 700,
        fontFamily: "'JetBrains Mono', monospace",
        letterSpacing: "0.04em",
        textTransform: "uppercase",
        color: spec.fg,
        background: spec.outline ? "transparent" : spec.bg,
        border: spec.outline ? `1px solid ${spec.fg}` : "1px solid transparent",
      }}
    >
      {spec.label}
    </span>
  );
}

function Toggle({ on, onChange, disabled }) {
  return (
    <button
      role="switch"
      aria-checked={on}
      disabled={disabled}
      onClick={(e) => { e.stopPropagation(); onChange(!on); }}
      style={{
        width: 28,
        height: 16,
        borderRadius: 10,
        border: "none",
        background: on ? C.gold : "#D8D5CE",
        position: "relative",
        cursor: disabled ? "not-allowed" : "pointer",
        flexShrink: 0,
        transition: "background 150ms ease",
        padding: 0,
      }}
      aria-label={on ? "Unsubscribe" : "Subscribe"}
    >
      <span
        style={{
          position: "absolute",
          top: 2,
          left: on ? 14 : 2,
          width: 12,
          height: 12,
          borderRadius: 6,
          background: "#FFFFFF",
          transition: "left 150ms ease",
          boxShadow: "0 1px 2px rgba(0,0,0,0.15)",
        }}
      />
    </button>
  );
}

function AlertRow({ alert, selected, onSelect, onToggleSubscribed }) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={() => onSelect(alert.id)}
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 8,
        padding: "8px 12px",
        borderLeft: selected ? `3px solid ${C.gold}` : "3px solid transparent",
        background: selected ? C.goldSurface : hovered ? "rgba(245,183,49,0.04)" : "transparent",
        cursor: "pointer",
        minHeight: 52,
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 12,
            fontWeight: selected ? 700 : 600,
            color: C.ink,
            lineHeight: 1.3,
            overflow: "hidden",
            textOverflow: "ellipsis",
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
          }}
        >
          {alert.name}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
          <CadencePill cadence={alert.cadence} />
          {alert.subscribed && alert.unread > 0 && (
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 9,
                fontWeight: 700,
                color: C.gold,
                letterSpacing: "0.04em",
              }}
            >
              {alert.unread} NEW
            </span>
          )}
        </div>
      </div>
      <Toggle
        on={!!alert.subscribed}
        onChange={(v) => onToggleSubscribed(alert.id, v)}
      />
    </div>
  );
}

export default function AlertLibrary({
  alerts,
  loading,
  selectedAlertId,
  onSelect,
  onToggleSubscribed,
}) {
  const [query, setQuery] = useState("");

  const grouped = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? alerts.filter(
          (a) =>
            a.name.toLowerCase().includes(q) ||
            (a.cluster || "").toLowerCase().includes(q) ||
            (a.description || "").toLowerCase().includes(q)
        )
      : alerts;
    const bySource = new Map();
    for (const a of filtered) {
      const k = a.source || "Other";
      if (!bySource.has(k)) bySource.set(k, []);
      bySource.get(k).push(a);
    }
    // Order according to SOURCE_ORDER, then anything else alphabetically.
    const known = SOURCE_ORDER.filter((s) => bySource.has(s)).map((s) => [s, bySource.get(s)]);
    const unknown = [...bySource.keys()]
      .filter((s) => !SOURCE_ORDER.includes(s))
      .sort()
      .map((s) => [s, bySource.get(s)]);
    return [...known, ...unknown];
  }, [alerts, query]);

  return (
    <>
      {/* Header + search */}
      <div
        style={{
          padding: "12px 12px 8px",
          borderBottom: `1px solid ${C.border}`,
          flexShrink: 0,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 8,
          }}
        >
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: C.secondary,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
            }}
          >
            Alert library
          </span>
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 10,
              color: C.tertiary,
            }}
          >
            {alerts.length}
          </span>
        </div>
        <div style={{ position: "relative" }}>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search alerts…"
            style={{
              width: "100%",
              padding: "6px 10px 6px 28px",
              fontSize: 12,
              fontFamily: "'DM Sans', sans-serif",
              border: `1px solid ${C.border}`,
              borderRadius: 6,
              background: C.bg,
              color: C.ink,
              outline: "none",
            }}
          />
          <svg
            width="14" height="14" viewBox="0 0 16 16" fill="none"
            stroke={C.tertiary} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"
            style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)" }}
          >
            <circle cx="7" cy="7" r="4.5" />
            <path d="M10.5 10.5L13.5 13.5" />
          </svg>
        </div>
      </div>

      {/* Group list */}
      <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
        {loading ? (
          <div style={{ padding: 16, fontSize: 12, color: C.tertiary }}>Loading…</div>
        ) : grouped.length === 0 ? (
          <div style={{ padding: 16, fontSize: 12, color: C.tertiary }}>
            No alerts match "{query}".
          </div>
        ) : (
          grouped.map(([source, items]) => (
            <div key={source}>
              <div
                style={{
                  padding: "8px 12px 4px",
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 9,
                  fontWeight: 700,
                  color: C.goldSoft,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  background: C.bg,
                  borderTop: `1px solid ${C.border}`,
                  borderBottom: `1px solid ${C.border}`,
                }}
              >
                {source}
                <span
                  style={{
                    marginLeft: 6,
                    fontFamily: "'JetBrains Mono', monospace",
                    color: C.tertiary,
                    fontWeight: 500,
                  }}
                >
                  · {items.length}
                </span>
              </div>
              {items.map((a) => (
                <AlertRow
                  key={a.id}
                  alert={a}
                  selected={a.id === selectedAlertId}
                  onSelect={onSelect}
                  onToggleSubscribed={onToggleSubscribed}
                />
              ))}
            </div>
          ))
        )}
      </div>
    </>
  );
}
