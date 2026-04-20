import React, { Suspense, lazy, useEffect, useState } from "react";
import { getDocument } from "../../../api/alerts";

const ChatRail = lazy(() => import("../../../components/shell/ChatRail"));

const C = {
  gold: "#F5B731",
  goldSoft: "#C9A64B",
  goldSurface: "rgba(245,183,49,0.08)",
  goldBorder: "rgba(245,183,49,0.30)",
  ink: "#0F1318",
  secondary: "#4B5563",
  tertiary: "#9C9590",
  border: "#E8EAED",
  bg: "#F7F8FA",
  ivory: "#FBF8F2",
};

function Segmented({ value, onChange }) {
  const OPTS = [
    { id: "docs", label: "Docs" },
    { id: "chat", label: "Chat" },
  ];
  return (
    <div
      role="tablist"
      style={{
        display: "inline-flex",
        padding: 3,
        borderRadius: 8,
        background: C.bg,
        border: `1px solid ${C.border}`,
        gap: 2,
      }}
    >
      {OPTS.map((o) => {
        const active = value === o.id;
        return (
          <button
            key={o.id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(o.id)}
            style={{
              padding: "4px 12px",
              fontSize: 11,
              fontWeight: active ? 700 : 600,
              fontFamily: "'DM Sans', sans-serif",
              border: active ? `1px solid ${C.goldBorder}` : "1px solid transparent",
              borderRadius: 6,
              color: active ? C.ink : C.secondary,
              background: active ? "#FFFFFF" : "transparent",
              cursor: "pointer",
              transition: "all 120ms ease",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Render an LLM extract with inline gold-numeral [n] citations.
 * Clicking a citation scrolls to it in the citation list below.
 */
function CitedText({ text, citations }) {
  if (!text) return null;
  // Split on [n] where n is 1-3 digits.
  const parts = text.split(/(\[\d{1,3}\])/g);
  return (
    <p style={{ margin: 0, fontSize: 13, lineHeight: 1.65, color: C.ink }}>
      {parts.map((p, i) => {
        const m = p.match(/^\[(\d{1,3})\]$/);
        if (!m) return <React.Fragment key={i}>{p}</React.Fragment>;
        const n = Number(m[1]);
        const has = citations?.some((c) => c.n === n);
        return (
          <a
            key={i}
            href={`#cite-${n}`}
            onClick={(e) => {
              e.preventDefault();
              document.getElementById(`cite-${n}`)?.scrollIntoView({
                behavior: "smooth",
                block: "center",
              });
            }}
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              minWidth: 16,
              height: 16,
              padding: "0 4px",
              margin: "0 2px",
              fontSize: 10,
              fontWeight: 800,
              fontFamily: "'JetBrains Mono', monospace",
              color: C.ink,
              background: C.gold,
              borderRadius: 4,
              textDecoration: "none",
              verticalAlign: "text-bottom",
              opacity: has ? 1 : 0.5,
              cursor: has ? "pointer" : "default",
            }}
          >
            {n}
          </a>
        );
      })}
    </p>
  );
}

function DocView({ docId }) {
  const [doc, setDoc] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!docId) { setDoc(null); return; }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getDocument(docId)
      .then((d) => { if (!cancelled) setDoc(d); })
      .catch((e) => { if (!cancelled) setError(e.message || String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [docId]);

  if (!docId) {
    return (
      <div style={{ padding: 24, color: C.tertiary, fontSize: 12, lineHeight: 1.6 }}>
        <div style={{
          fontSize: 9, fontWeight: 700, color: C.tertiary,
          letterSpacing: "0.08em", textTransform: "uppercase",
          fontFamily: "'JetBrains Mono', monospace", marginBottom: 8,
        }}>
          Document viewer
        </div>
        Select a document from the feed to read the extracted text and citations.
      </div>
    );
  }
  if (loading) return <div style={{ padding: 20, fontSize: 12, color: C.tertiary }}>Loading document…</div>;
  if (error) return <div style={{ padding: 20, fontSize: 12, color: "#E24A4A" }}>Error: {error}</div>;
  if (!doc) return null;

  return (
    <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "16px 20px" }}>
      <div style={{
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 10, color: C.tertiary, letterSpacing: "0.04em", marginBottom: 4,
      }}>
        {doc.id} · {doc.source} · {doc.filing_type}
      </div>
      <h2 style={{
        margin: "0 0 10px",
        fontSize: 16, fontWeight: 700, letterSpacing: "-0.01em", color: C.ink,
      }}>
        {doc.title}
      </h2>

      <div style={{
        padding: "10px 12px",
        background: C.ivory,
        border: `1px solid ${C.border}`,
        borderRadius: 8,
        marginBottom: 16,
      }}>
        <div style={{
          fontSize: 9, fontWeight: 700, color: C.goldSoft,
          letterSpacing: "0.08em", textTransform: "uppercase",
          fontFamily: "'JetBrains Mono', monospace", marginBottom: 6,
        }}>
          LLM extract
        </div>
        <CitedText text={doc.extract} citations={doc.citations} />
      </div>

      {doc.citations?.length > 0 && (
        <div>
          <div style={{
            fontSize: 9, fontWeight: 700, color: C.tertiary,
            letterSpacing: "0.08em", textTransform: "uppercase",
            fontFamily: "'JetBrains Mono', monospace", marginBottom: 6,
          }}>
            Citations
          </div>
          <ol style={{ margin: 0, padding: 0, listStyle: "none" }}>
            {doc.citations.map((c) => (
              <li
                key={c.n}
                id={`cite-${c.n}`}
                style={{
                  display: "flex", gap: 8, padding: "6px 0",
                  borderTop: `1px solid ${C.border}`,
                  fontSize: 12, lineHeight: 1.5,
                }}
              >
                <span style={{
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  minWidth: 18, height: 18, padding: "0 4px",
                  fontSize: 10, fontWeight: 800, fontFamily: "'JetBrains Mono', monospace",
                  color: C.ink, background: C.gold, borderRadius: 4, flexShrink: 0,
                }}>
                  {c.n}
                </span>
                <span style={{ color: C.secondary }}>{c.label}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {doc.topics?.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{
            fontSize: 9, fontWeight: 700, color: C.tertiary,
            letterSpacing: "0.08em", textTransform: "uppercase",
            fontFamily: "'JetBrains Mono', monospace", marginBottom: 6,
          }}>
            Topics
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {doc.topics.map((t) => (
              <span
                key={t}
                style={{
                  padding: "2px 8px", borderRadius: 10,
                  fontSize: 10, fontWeight: 600,
                  color: C.secondary, background: "#F2F3F5",
                  border: `1px solid ${C.border}`,
                }}
              >
                {t}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function DocRail({ docId, alertId, onPickQuestion }) {
  // Chat is the default tab on Intelligence routes — the popup that used to
  // float on top has been retired and the conversation now happens inside
  // this rail. Docs view is opened on demand when the user clicks a document
  // in the digest feed (see effect below).
  const [mode, setMode] = useState("chat");

  // Auto-switch to docs when the selected document changes.
  useEffect(() => {
    if (docId) setMode("docs");
  }, [docId]);

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div
        style={{
          padding: "12px 16px",
          borderBottom: `1px solid ${C.border}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexShrink: 0,
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
          {mode === "docs" ? "Document" : "Princeps chat"}
        </span>
        <Segmented value={mode} onChange={setMode} />
      </div>

      {mode === "docs" ? (
        <DocView docId={docId} />
      ) : (
        <div style={{ flex: 1, minHeight: 0, position: "relative", display: "flex" }}>
          <Suspense fallback={<div style={{ padding: 20, fontSize: 12, color: C.tertiary }}>Loading chat…</div>}>
            <ChatRail
              inline={true}
              defaultCollapsed={false}
              projectId={alertId || null}
            />
          </Suspense>
        </div>
      )}
    </div>
  );
}
