import React, { useState } from "react";
import { pinDocument } from "../../../api/alerts";

const C = {
  gold: "#F5B731",
  goldDark: "#B5912F",
  goldSurface: "rgba(245,183,49,0.08)",
  goldBorder: "rgba(245,183,49,0.30)",
  ink: "#0F1318",
  secondary: "#4B5563",
  tertiary: "#9C9590",
  border: "#E8EAED",
  ivory: "#FBF8F2",
};

const SOURCE_COLOR = {
  Ofgem:  "#2E6FEF",
  NESO:   "#7C3AED",
  PINS:   "#22A06B",
  LPA:    "#E0A52B",
  DNO:    "#B5912F",
  DESNZ:  "#E24A4A",
};

function SourcePill({ source }) {
  const color = SOURCE_COLOR[source] || C.secondary;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 8px",
        borderRadius: 4,
        fontSize: 9,
        fontWeight: 800,
        fontFamily: "'JetBrains Mono', monospace",
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color,
        background: "#FFFFFF",
        border: `1px solid ${color}40`,
      }}
    >
      {source}
    </span>
  );
}

function TopicPill({ topic }) {
  return (
    <span
      style={{
        display: "inline-flex",
        padding: "2px 8px",
        borderRadius: 10,
        fontSize: 10,
        fontWeight: 600,
        color: C.secondary,
        background: "#F2F3F5",
        border: `1px solid ${C.border}`,
      }}
    >
      {topic}
    </span>
  );
}

function formatRelDate(iso) {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now - d;
    const m = Math.round(diffMs / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.round(m / 60);
    if (h < 24) return `${h}h ago`;
    const days = Math.round(h / 24);
    if (days < 7) return `${days}d ago`;
    return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
  } catch {
    return iso;
  }
}

function Button({ children, onClick, primary, icon, title }) {
  const [hover, setHover] = useState(false);
  return (
    <button
      type="button"
      title={title}
      onClick={(e) => { e.stopPropagation(); onClick?.(); }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "4px 10px",
        fontSize: 11,
        fontWeight: 600,
        fontFamily: "'DM Sans', sans-serif",
        borderRadius: 6,
        cursor: "pointer",
        transition: "all 120ms ease",
        color: primary ? C.ink : C.secondary,
        background: primary
          ? (hover ? C.gold : C.goldSurface)
          : (hover ? "#F2F3F5" : "transparent"),
        border: `1px solid ${primary ? C.goldBorder : C.border}`,
      }}
    >
      {icon}
      {children}
    </button>
  );
}

const IconPin = (
  <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 1.5v4l2 2v1H4v-1l2-2v-4z" />
    <path d="M6 8.5V11" />
  </svg>
);

const IconAsk = (
  <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
    <path d="M2 3h8a1 1 0 011 1v4a1 1 0 01-1 1H5l-2 2V9H2a1 1 0 01-1-1V4a1 1 0 011-1z" />
  </svg>
);

export default function DocumentCard({ doc, onOpen, onAskAcross }) {
  const [pinned, setPinned] = useState(false);
  const [pinning, setPinning] = useState(false);

  const onPin = async () => {
    if (pinning || pinned) return;
    setPinning(true);
    try {
      await pinDocument({ docId: doc.id });
      setPinned(true);
    } catch (e) {
      console.warn("pin failed:", e);
    } finally {
      setPinning(false);
    }
  };

  const structured = doc.structured || {};
  const hasStructured =
    structured.counterparty || structured.capacity_mw || structured.poc;

  return (
    <article
      onClick={() => onOpen?.(doc.id)}
      style={{
        background: C.ivory,
        border: `1px solid ${C.border}`,
        borderRadius: 10,
        padding: "12px 16px",
        cursor: "pointer",
        transition: "border-color 120ms ease, transform 120ms ease",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = C.goldBorder; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = C.border; }}
    >
      {/* Header row: source pill · date · filing type */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <SourcePill source={doc.source} />
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10,
            color: C.tertiary,
          }}
        >
          {formatRelDate(doc.date)}
        </span>
        <span style={{ fontSize: 11, color: C.tertiary }}>·</span>
        <span
          style={{
            fontSize: 11,
            color: C.secondary,
            fontWeight: 600,
          }}
        >
          {doc.filing_type}
        </span>
        <span style={{ flex: 1 }} />
        <span
          style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 9,
            color: C.tertiary,
            letterSpacing: "0.04em",
          }}
          title="Document ID"
        >
          {doc.id}
        </span>
      </div>

      {/* Title */}
      <h3
        style={{
          margin: "0 0 6px",
          fontSize: 14,
          fontWeight: 700,
          color: C.ink,
          lineHeight: 1.3,
          letterSpacing: "-0.01em",
        }}
      >
        {doc.title}
      </h3>

      {/* Topic pills */}
      {doc.topics?.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 8 }}>
          {doc.topics.map((t) => <TopicPill key={t} topic={t} />)}
        </div>
      )}

      {/* LLM extract (2-line clamp) */}
      {doc.extract && (
        <p
          style={{
            margin: 0,
            fontSize: 12,
            lineHeight: 1.5,
            color: C.secondary,
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          {doc.extract}
        </p>
      )}

      {/* Structured fields */}
      {hasStructured && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
            gap: 8,
            marginTop: 10,
            padding: "8px 10px",
            background: "#FFFFFF",
            border: `1px solid ${C.border}`,
            borderRadius: 6,
          }}
        >
          {structured.counterparty && (
            <Field label="Counterparty" value={structured.counterparty} />
          )}
          {structured.capacity_mw != null && (
            <Field label="Capacity" value={`${structured.capacity_mw.toLocaleString()} MW`} mono />
          )}
          {structured.poc && (
            <Field label="POC" value={structured.poc} />
          )}
        </div>
      )}

      {/* Footer actions */}
      <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
        <Button
          primary
          icon={IconPin}
          onClick={onPin}
          title={pinned ? "Pinned" : "Pin to project"}
        >
          {pinned ? "Pinned" : pinning ? "Pinning…" : "Pin to project"}
        </Button>
        <Button
          icon={IconAsk}
          onClick={() =>
            onAskAcross?.(`Summarise "${doc.title}" and show what it changes for my projects.`)
          }
          title="Ask across documents"
        >
          Ask across
        </Button>
      </div>
    </article>
  );
}

function Field({ label, value, mono }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div
        style={{
          fontSize: 9,
          fontWeight: 700,
          color: C.tertiary,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          fontFamily: "'JetBrains Mono', monospace",
          marginBottom: 2,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: C.ink,
          fontFamily: mono ? "'JetBrains Mono', monospace" : "'DM Sans', sans-serif",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
        title={String(value)}
      >
        {value}
      </div>
    </div>
  );
}
