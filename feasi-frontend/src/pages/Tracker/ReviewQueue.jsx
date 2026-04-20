import React, { useState } from "react";
import { useReviewQueue } from "../../hooks/useTracker";
import TrackerDetail from "./TrackerDetail";
import ReviewModal from "./ReviewModal";

/* ─────────────────────────────────────────────────────────────────
   ReviewQueue — SME review tab. Pulls low-confidence, unreviewed
   records; per-row Approve / Edit / Reject; batch approve via
   multi-select.
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
  ok: "#2FA84F",
  err: "#D64545",
};

function confPill(v) {
  if (v == null) return { bg: "#EEE", fg: "#666" };
  if (v >= 0.75) return { bg: "#D8F0DC", fg: "#1C6B3A" };
  if (v >= 0.5) return { bg: "#FDF2D1", fg: "#8B6A00" };
  return { bg: "#FBD8D5", fg: "#8E1E1E" };
}

export default function ReviewQueue({ admin = true }) {
  const [threshold, setThreshold] = useState(0.75);
  const { rows, total, loading, error, approveOne, rejectOne, approveMany } = useReviewQueue({ threshold });
  const [selected, setSelected] = useState(new Set());
  const [editing, setEditing] = useState(null);
  const [inspectId, setInspectId] = useState(null);
  const [busy, setBusy] = useState(false);

  const toggleOne = (id) => {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  };
  const toggleAll = () => {
    if (selected.size === rows.length) setSelected(new Set());
    else setSelected(new Set(rows.map((r) => r.project_id)));
  };

  const doApprove = async (id) => {
    setBusy(true);
    try { await approveOne(id); } finally { setBusy(false); }
  };
  const doReject = async (id) => {
    setBusy(true);
    try { await rejectOne(id); } finally { setBusy(false); }
  };
  const doBatch = async () => {
    if (!selected.size) return;
    setBusy(true);
    try {
      await approveMany(Array.from(selected));
      setSelected(new Set());
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", background: C.ivory }}>
      {/* Queue header */}
      <div
        style={{
          padding: "14px 22px",
          borderBottom: `1px solid ${C.border}`,
          background: C.bg,
          display: "flex",
          alignItems: "center",
          gap: 16,
          flexWrap: "wrap",
          fontFamily: "'DM Sans', sans-serif",
        }}
      >
        <div>
          <div style={{ fontSize: 10, color: C.tertiary, textTransform: "uppercase", letterSpacing: "0.08em" }}>
            Review queue
          </div>
          <div style={{ fontSize: 16, fontWeight: 800, color: C.ink, marginTop: 2 }}>
            {loading ? "…" : `${total} records awaiting review`}
          </div>
        </div>

        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: C.secondary }}>
          Threshold
          <input
            type="range"
            min={0.4}
            max={0.9}
            step={0.05}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            style={{ accentColor: C.gold }}
          />
          <span style={{ fontFamily: "'JetBrains Mono', monospace", color: C.ink, fontWeight: 700 }}>
            &lt; {threshold.toFixed(2)}
          </span>
        </label>

        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 11, color: C.tertiary, fontFamily: "'JetBrains Mono', monospace" }}>
            {selected.size} selected
          </span>
          <button
            type="button"
            onClick={doBatch}
            disabled={!selected.size || busy}
            style={{
              padding: "7px 14px",
              borderRadius: 6,
              border: `1px solid ${C.gold}`,
              background: selected.size && !busy ? C.gold : "#f3d98a",
              color: C.ink,
              fontWeight: 700,
              fontSize: 12,
              cursor: selected.size && !busy ? "pointer" : "not-allowed",
              fontFamily: "'DM Sans', sans-serif",
            }}
          >
            Approve selected
          </button>
        </div>
      </div>

      {/* Queue list */}
      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "12px 22px 40px" }}>
        {error && <div style={{ color: "#8E1E1E", fontSize: 12 }}>Failed to load queue: {error}</div>}

        {rows.length > 0 && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 2px 10px",
              fontSize: 10,
              color: C.tertiary,
              textTransform: "uppercase",
              letterSpacing: "0.1em",
            }}
          >
            <input
              type="checkbox"
              checked={selected.size === rows.length && rows.length > 0}
              onChange={toggleAll}
            />
            <span>Select all</span>
          </div>
        )}

        <div style={{ display: "grid", gap: 10 }}>
          {rows.map((r) => {
            const p = confPill(r.confidence);
            const isSelected = selected.has(r.project_id);
            return (
              <article
                key={r.project_id}
                style={{
                  background: C.bg,
                  borderRadius: 10,
                  border: `1px solid ${isSelected ? C.goldBorder : C.border}`,
                  boxShadow: isSelected ? "0 2px 12px rgba(245,183,49,0.15)" : "0 1px 2px rgba(15,19,24,0.03)",
                  padding: "14px 16px",
                  display: "grid",
                  gridTemplateColumns: "24px 1fr auto",
                  gap: 14,
                  alignItems: "flex-start",
                  fontFamily: "'DM Sans', sans-serif",
                }}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => toggleOne(r.project_id)}
                  style={{ marginTop: 4 }}
                />

                <div style={{ minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span
                      style={{
                        fontSize: 10,
                        padding: "2px 8px",
                        borderRadius: 10,
                        background: p.bg,
                        color: p.fg,
                        fontWeight: 700,
                        fontFamily: "'JetBrains Mono', monospace",
                      }}
                    >
                      {r.confidence?.toFixed(2)}
                    </span>
                    <h3
                      style={{
                        margin: 0,
                        fontSize: 14,
                        fontWeight: 700,
                        color: C.ink,
                        cursor: "pointer",
                      }}
                      onClick={() => setInspectId(r.project_id)}
                    >
                      {r.substation_name}
                    </h3>
                    <span style={{ fontSize: 11, color: C.tertiary, fontFamily: "'JetBrains Mono', monospace" }}>
                      {r.project_id}
                    </span>
                  </div>
                  <div style={{ marginTop: 4, fontSize: 12, color: C.secondary, display: "flex", gap: 10, flexWrap: "wrap" }}>
                    <span>{r.region}</span>
                    <span style={{ color: C.tertiary }}>·</span>
                    <span>{r.developer}</span>
                    <span style={{ color: C.tertiary }}>·</span>
                    <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>{r.voltage_kv_primary ?? "—"} kV</span>
                    <span style={{ color: C.tertiary }}>·</span>
                    <span>{r.construction_status?.replace(/_/g, " ")}</span>
                    <span style={{ color: C.tertiary }}>·</span>
                    <span>op {r.operation_year ?? "—"}</span>
                  </div>
                  <div style={{ marginTop: 6, fontSize: 12, color: C.ink, lineHeight: 1.45, maxWidth: 720 }}>
                    {r.project_description}
                  </div>
                  <div style={{ marginTop: 6, fontSize: 11, color: C.tertiary, fontFamily: "'JetBrains Mono', monospace" }}>
                    source: {r.source_type} / {r.source_docket_id} · last_updated {r.last_updated?.slice(0, 10)}
                  </div>
                </div>

                {admin && (
                  <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                    <button
                      type="button"
                      onClick={() => doApprove(r.project_id)}
                      disabled={busy}
                      style={btnApprove}
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditing(r)}
                      style={btnEdit}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => doReject(r.project_id)}
                      disabled={busy}
                      style={btnReject}
                    >
                      Reject
                    </button>
                  </div>
                )}
              </article>
            );
          })}

          {!loading && rows.length === 0 && (
            <div
              style={{
                textAlign: "center",
                padding: 40,
                color: C.tertiary,
                fontSize: 13,
                fontFamily: "'DM Sans', sans-serif",
              }}
            >
              Review queue is clear at this threshold.
            </div>
          )}
        </div>
      </div>

      <TrackerDetail id={inspectId} onClose={() => setInspectId(null)} admin={admin} />

      {editing && (
        <ReviewModal
          substation={editing}
          onClose={() => setEditing(null)}
          onSaved={() => setEditing(null)}
        />
      )}
    </div>
  );
}

const btnApprove = {
  padding: "6px 12px",
  borderRadius: 6,
  border: `1px solid ${C.ok}`,
  background: C.ok,
  color: "#fff",
  fontWeight: 700,
  fontSize: 11,
  cursor: "pointer",
  fontFamily: "'DM Sans', sans-serif",
};
const btnEdit = {
  padding: "6px 12px",
  borderRadius: 6,
  border: `1px solid ${C.gold}`,
  background: C.gold,
  color: C.ink,
  fontWeight: 700,
  fontSize: 11,
  cursor: "pointer",
  fontFamily: "'DM Sans', sans-serif",
};
const btnReject = {
  padding: "6px 12px",
  borderRadius: 6,
  border: `1px solid ${C.err}`,
  background: "transparent",
  color: C.err,
  fontWeight: 700,
  fontSize: 11,
  cursor: "pointer",
  fontFamily: "'DM Sans', sans-serif",
};
