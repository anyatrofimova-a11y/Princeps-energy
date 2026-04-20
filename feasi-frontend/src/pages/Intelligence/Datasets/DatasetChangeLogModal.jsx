/**
 * DatasetChangeLogModal — "Recent updates" modal for a dataset card.
 *
 * Renders a chronological changelog (added / updated / removed rows) with
 * timestamps. Data is a lightweight deterministic mock seeded off the
 * dataset slug, so every dataset has a plausible 12-entry history without
 * needing the backend diff tables wired up.
 *
 * Keyboard: ESC closes. Click on the backdrop closes. Click inside the
 * dialog does not.
 */
import React, { useEffect, useMemo } from "react";

const C = {
  ink: "#0F1318",
  body: "#3A3F46",
  muted: "#6B7280",
  faint: "#9CA3AF",
  border: "#E5E7EB",
  ivory: "#FBF8F2",
  gold: "#F5B731",
  goldBorder: "rgba(245,183,49,0.32)",
  added: "#3B8A5A",
  updated: "#C8951E",
  removed: "#C64545",
};

// Simple deterministic RNG so every slug renders the same fake history.
function seededRand(seed) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return () => {
    h ^= h << 13;
    h ^= h >>> 17;
    h ^= h << 5;
    return ((h >>> 0) % 100000) / 100000;
  };
}

function buildMockChangeLog(dataset) {
  const rand = seededRand(dataset.slug || "dataset");
  const kinds = ["added", "updated", "removed"];
  const sampleNotes = {
    added: [
      "New records ingested from upstream feed",
      "Publisher released scheduled update",
      "Monthly snapshot file posted",
      "Backfill from previous quarter completed",
    ],
    updated: [
      "Field values refreshed against source-of-truth",
      "Schema columns aligned with publisher spec",
      "Status transitions reconciled",
      "Geocoding pass improved coordinate accuracy",
    ],
    removed: [
      "Records withdrawn by publisher",
      "Duplicates collapsed during entity resolution",
      "Stale rows aged out of active window",
      "Records reclassified out of this dataset scope",
    ],
  };

  const now = Date.now();
  const entries = [];
  for (let i = 0; i < 12; i++) {
    const kind = kinds[Math.floor(rand() * kinds.length)];
    const rows = Math.max(1, Math.floor(rand() * 220));
    // Space entries out over ~90 days.
    const t = new Date(now - (i * (24 * 3600 * 1000) * (1 + rand() * 2.5)));
    const noteBank = sampleNotes[kind];
    const note = noteBank[Math.floor(rand() * noteBank.length)];
    entries.push({
      kind,
      rows,
      timestamp: t.toISOString(),
      note,
    });
  }
  return entries;
}

function formatDate(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function DatasetChangeLogModal({ dataset, onClose }) {
  const entries = useMemo(
    () => (dataset ? buildMockChangeLog(dataset) : []),
    [dataset]
  );

  useEffect(() => {
    if (!dataset) return undefined;
    const handleKey = (e) => {
      if (e.key === "Escape") onClose?.();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [dataset, onClose]);

  if (!dataset) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`${dataset.title} recent updates`}
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,19,24,0.48)",
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        fontFamily: "'DM Sans', sans-serif",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%",
          maxWidth: 640,
          maxHeight: "80vh",
          background: "#FFFFFF",
          border: `1px solid ${C.border}`,
          borderRadius: 14,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          boxShadow: "0 24px 60px rgba(15,19,24,0.22)",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "18px 22px 14px",
            borderBottom: `1px solid ${C.border}`,
            display: "flex",
            alignItems: "flex-start",
            gap: 12,
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontSize: 10,
                letterSpacing: 0.6,
                textTransform: "uppercase",
                fontWeight: 700,
                color: C.muted,
              }}
            >
              Recent updates
            </div>
            <div
              style={{
                fontSize: 16,
                fontWeight: 800,
                color: C.ink,
                marginTop: 2,
                letterSpacing: "-0.01em",
              }}
            >
              {dataset.title}
            </div>
            <div style={{ fontSize: 12, color: C.body, marginTop: 2 }}>
              {dataset.publisher} · {dataset.cadence}
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              border: `1px solid ${C.border}`,
              background: C.ivory,
              borderRadius: 8,
              padding: "6px 10px",
              fontSize: 12,
              fontWeight: 700,
              color: C.ink,
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            Close
          </button>
        </div>

        {/* Entries */}
        <div style={{ overflowY: "auto", padding: "4px 4px 10px" }}>
          {entries.map((e, i) => (
            <div
              key={i}
              style={{
                display: "grid",
                gridTemplateColumns: "82px 68px 1fr auto",
                gap: 12,
                alignItems: "baseline",
                padding: "10px 22px",
                borderBottom:
                  i === entries.length - 1 ? "none" : `1px solid ${C.border}`,
              }}
            >
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: 0.5,
                  textTransform: "uppercase",
                  color:
                    e.kind === "added"
                      ? C.added
                      : e.kind === "removed"
                      ? C.removed
                      : C.updated,
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                {e.kind}
              </span>
              <span
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  color: C.ink,
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                {e.rows.toLocaleString("en-GB")}
              </span>
              <span style={{ fontSize: 12, color: C.body }}>{e.note}</span>
              <span
                style={{
                  fontSize: 11,
                  color: C.muted,
                  fontFamily: "'JetBrains Mono', monospace",
                  whiteSpace: "nowrap",
                }}
              >
                {formatDate(e.timestamp)}
              </span>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: "10px 22px",
            borderTop: `1px solid ${C.border}`,
            fontSize: 11,
            color: C.muted,
            background: C.ivory,
          }}
        >
          Deterministic sample history. Wired dataset diffs ship with the
          backend change-feed tables.
        </div>
      </div>
    </div>
  );
}
