import React, { useEffect, useMemo, useState } from "react";
import useDigest from "../../../hooks/useDigest";
import { getDocumentsForAlert, getAllDocuments } from "../../../api/alerts";
import DocumentCard from "./DocumentCard";

const C = {
  gold: "#F5B731",
  goldSoft: "#C9A64B",
  ink: "#0F1318",
  secondary: "#4B5563",
  tertiary: "#9C9590",
  border: "#E8EAED",
  ivory: "#FBF8F2",
};

function DaySeparator({ date, count }) {
  const d = new Date(date + "T00:00:00Z");
  const today = new Date();
  const isToday = d.toDateString() === today.toDateString();
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
  const isYesterday = d.toDateString() === yesterday.toDateString();
  const label = isToday ? "Today" : isYesterday ? "Yesterday"
    : d.toLocaleDateString("en-GB", { weekday: "long", day: "2-digit", month: "short" });
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "18px 4px 10px",
        position: "sticky",
        top: 0,
        background: C.ivory,
        zIndex: 2,
      }}
    >
      <span
        style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 10,
          fontWeight: 700,
          color: C.goldSoft,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
        }}
      >
        {label}
      </span>
      <span
        style={{
          flex: 1,
          height: 1,
          background: `linear-gradient(to right, ${C.border}, transparent)`,
        }}
      />
      <span
        style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 10,
          color: C.tertiary,
        }}
      >
        {count} item{count === 1 ? "" : "s"}
      </span>
    </div>
  );
}

function QueryBar({ onAsk }) {
  const [q, setQ] = useState("");
  const submit = () => {
    const text = q.trim();
    if (!text) return;
    onAsk(text);
    setQ("");
  };
  return (
    <div
      style={{
        padding: "12px 20px",
        borderBottom: `1px solid ${C.border}`,
        background: "#FFFFFF",
        display: "flex",
        gap: 8,
        alignItems: "center",
        flexShrink: 0,
      }}
    >
      <svg
        width="14" height="14" viewBox="0 0 16 16" fill="none"
        stroke={C.goldSoft} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"
      >
        <circle cx="7" cy="7" r="4.5" />
        <path d="M10.5 10.5L13.5 13.5" />
      </svg>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
        placeholder="Ask across these documents — e.g. 'new BESS capacity accepted this week'"
        style={{
          flex: 1,
          border: "none",
          outline: "none",
          fontSize: 13,
          fontFamily: "'DM Sans', sans-serif",
          color: C.ink,
          background: "transparent",
        }}
      />
      <button
        onClick={submit}
        style={{
          padding: "5px 12px",
          fontSize: 11,
          fontWeight: 700,
          fontFamily: "'DM Sans', sans-serif",
          borderRadius: 6,
          border: "1px solid rgba(245,183,49,0.30)",
          background: "rgba(245,183,49,0.10)",
          color: C.ink,
          cursor: "pointer",
        }}
      >
        Ask
      </button>
    </div>
  );
}

export default function DigestFeed({ alertId, onSelectDoc, onAskAcross }) {
  const { digests, loading } = useDigest({ alertId });
  const [docs, setDocs] = useState([]);
  const [docsLoading, setDocsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setDocsLoading(true);
    (async () => {
      try {
        const data = alertId
          ? await getDocumentsForAlert(alertId)
          : await getAllDocuments();
        if (!cancelled) setDocs(data.documents || []);
      } catch (e) {
        if (!cancelled) setDocs([]);
      } finally {
        if (!cancelled) setDocsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [alertId]);

  // Group documents by ISO date (YYYY-MM-DD).
  const byDay = useMemo(() => {
    const m = new Map();
    for (const d of docs) {
      const day = (d.date || "").slice(0, 10);
      if (!m.has(day)) m.set(day, []);
      m.get(day).push(d);
    }
    // Sort days desc.
    return [...m.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1));
  }, [docs]);

  const totalToday = useMemo(() => {
    if (digests.length === 0) return 0;
    return digests[0].entries.length;
  }, [digests]);

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <QueryBar onAsk={onAskAcross} />

      {/* Summary strip */}
      <div
        style={{
          padding: "10px 20px",
          borderBottom: `1px solid ${C.border}`,
          background: "#FFFFFF",
          display: "flex",
          alignItems: "center",
          gap: 16,
          flexShrink: 0,
        }}
      >
        <div>
          <div style={{
            fontSize: 9, fontWeight: 700, color: C.tertiary,
            letterSpacing: "0.08em", textTransform: "uppercase",
            fontFamily: "'JetBrains Mono', monospace",
          }}>
            Today
          </div>
          <div style={{ fontSize: 18, fontWeight: 800, color: C.ink }}>
            {totalToday}
            <span style={{ fontSize: 11, color: C.tertiary, marginLeft: 6, fontWeight: 500 }}>
              digest items
            </span>
          </div>
        </div>
        <div style={{ width: 1, height: 26, background: C.border }} />
        <div>
          <div style={{
            fontSize: 9, fontWeight: 700, color: C.tertiary,
            letterSpacing: "0.08em", textTransform: "uppercase",
            fontFamily: "'JetBrains Mono', monospace",
          }}>
            Feed
          </div>
          <div style={{ fontSize: 13, fontWeight: 600, color: C.ink }}>
            {alertId ? "Filtered by selected alert" : "All subscribed alerts"}
          </div>
        </div>
      </div>

      {/* Scrollable body */}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          padding: "0 20px 20px",
          background: C.ivory,
        }}
      >
        {(loading || docsLoading) ? (
          <div style={{ padding: "40px 0", color: C.tertiary, fontSize: 13 }}>
            Loading digest…
          </div>
        ) : byDay.length === 0 ? (
          <div style={{ padding: "40px 0", color: C.tertiary, fontSize: 13 }}>
            No digest entries yet. New documents appear here as your alerts fire.
          </div>
        ) : (
          byDay.map(([day, items]) => (
            <React.Fragment key={day}>
              <DaySeparator date={day} count={items.length} />
              <div style={{ display: "grid", gap: 10 }}>
                {items.map((doc) => (
                  <DocumentCard
                    key={doc.id}
                    doc={doc}
                    onOpen={onSelectDoc}
                    onAskAcross={onAskAcross}
                  />
                ))}
              </div>
            </React.Fragment>
          ))
        )}
      </div>
    </div>
  );
}
