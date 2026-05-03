import React, { useEffect, useMemo, useState } from "react";
import useDocumentQuery from "../../../hooks/useDocumentQuery";
// Removed: rankMockDocs / MOCK_MODE — citations come from the live
// /api/alerts/query/stream protocol now.

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

const TABS = [
  { id: "analysis",  label: "Analysis" },
  { id: "figures",   label: "Figures" },
  { id: "documents", label: "Documents" },
];

function Segmented({ value, onChange }) {
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
      {TABS.map((t) => {
        const active = value === t.id;
        return (
          <button
            key={t.id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.id)}
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
            }}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

function CitedText({ text, citations, onCiteClick }) {
  if (!text) return null;
  const parts = text.split(/(\[\d{1,3}\])/g);
  return (
    <p style={{ margin: 0, fontSize: 13, lineHeight: 1.65, color: C.ink }}>
      {parts.map((p, i) => {
        const m = p.match(/^\[(\d{1,3})\]$/);
        if (!m) return <React.Fragment key={i}>{p}</React.Fragment>;
        const n = Number(m[1]);
        const c = citations?.find((x) => x.n === n);
        return (
          <button
            key={i}
            onClick={() => c && onCiteClick?.(c)}
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
              border: "none",
              borderRadius: 4,
              verticalAlign: "text-bottom",
              cursor: c ? "pointer" : "default",
            }}
            title={c?.label || c?.title}
          >
            {n}
          </button>
        );
      })}
    </p>
  );
}

function FigureCard({ figure }) {
  if (!figure) return null;
  const { kind, title, rows } = figure;
  return (
    <div style={{
      background: C.ivory,
      border: `1px solid ${C.border}`,
      borderRadius: 8,
      padding: 12,
    }}>
      <div style={{
        fontSize: 9, fontWeight: 700, color: C.goldSoft,
        letterSpacing: "0.08em", textTransform: "uppercase",
        fontFamily: "'JetBrains Mono', monospace", marginBottom: 6,
      }}>
        {kind || "Figure"}
      </div>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.ink, marginBottom: 8 }}>
        {title}
      </div>
      {Array.isArray(rows) && rows.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} style={{ borderTop: i === 0 ? "none" : `1px solid ${C.border}` }}>
                {Array.isArray(row) ? row.map((cell, j) => (
                  <td key={j} style={{
                    padding: "4px 6px",
                    color: j === 0 ? C.secondary : C.ink,
                    fontFamily: j === 0 ? "'DM Sans', sans-serif" : "'JetBrains Mono', monospace",
                    textAlign: j === 0 ? "left" : "right",
                  }}>
                    {typeof cell === "number" ? cell.toLocaleString() : String(cell)}
                  </td>
                )) : (
                  <td style={{ padding: "4px 6px", color: C.ink }}>{String(row)}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/**
 * QueryView — inline replacement for DigestFeed when the user asks
 * a question. Streams SSE text + citations. The right rail runs its
 * own Analysis / Figures / Documents segmented tabs.
 *
 * The parent is told about the first-cited doc via onSelectDoc so the
 * right rail auto-switches to the most-relevant document as soon as
 * citations arrive.
 */
export default function QueryView({ question, scope, onBack, onSelectDoc }) {
  const { answer, citations, streaming, error, ask, cancel, firstDocId } = useDocumentQuery();
  const [tab, setTab] = useState("analysis");

  useEffect(() => {
    if (!question) return;
    ask(question, scope || {});
    return () => cancel();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [question]);

  // Keep the right-rail doc in sync with the top citation.
  useEffect(() => {
    if (firstDocId) onSelectDoc?.(firstDocId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [firstDocId]);

  // Ranked doc list — kept empty; the live SSE protocol emits citations
  // directly which the Documents tab renders without re-ranking.
  const rankedForDocsTab = useMemo(() => [], []);

  const figures = useMemo(() => {
    const out = [];
    const docIdsInCitations = new Set((citations || []).map((c) => c.doc_id).filter(Boolean));
    for (const r of rankedForDocsTab) {
      const d = r.doc;
      if (Array.isArray(d.figures) && d.figures.length > 0) {
        d.figures.forEach((f) => out.push({ docId: d.id, title: d.title, figure: f, inCitations: docIdsInCitations.has(d.id) }));
      }
    }
    return out;
  }, [rankedForDocsTab, citations]);

  const docsList = useMemo(() => {
    // Prefer ranked list if available (mock), else distinct-doc citations.
    if (rankedForDocsTab.length > 0) {
      return rankedForDocsTab.map((r) => ({
        id: r.doc.id,
        title: r.doc.title,
        source: r.doc.source,
        date: (r.doc.published_at || r.doc.date || "").slice(0, 10),
        score: Math.round(r.score),
        snippet: (r.doc.body || r.doc.extract || "").slice(0, 180),
      }));
    }
    const map = new Map();
    for (const c of citations) {
      if (c.doc_id && !map.has(c.doc_id)) {
        map.set(c.doc_id, {
          id: c.doc_id,
          title: c.title || c.label || c.doc_id,
          source: c.source || "",
          date: c.date || "",
          score: c.score || null,
          snippet: "",
        });
      }
    }
    return [...map.values()];
  }, [rankedForDocsTab, citations]);

  const onCiteClick = (c) => {
    if (c?.doc_id) onSelectDoc?.(c.doc_id);
  };

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div
        style={{
          padding: "12px 20px",
          borderBottom: `1px solid ${C.border}`,
          background: "#FFFFFF",
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <button
          onClick={onBack}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            padding: "4px 10px",
            fontSize: 11,
            fontWeight: 600,
            color: C.secondary,
            background: C.bg,
            border: `1px solid ${C.border}`,
            borderRadius: 6,
            cursor: "pointer",
          }}
        >
          ← Feed
        </button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 9, fontWeight: 700, color: C.tertiary,
            letterSpacing: "0.08em", textTransform: "uppercase",
            fontFamily: "'JetBrains Mono', monospace",
          }}>
            Query
          </div>
          <div
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: C.ink,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
            title={question}
          >
            {question}
          </div>
        </div>
        <Segmented value={tab} onChange={setTab} />
      </div>

      {/* Body */}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          padding: "20px 24px",
          background: C.ivory,
        }}
      >
        {error && (
          <div style={{
            padding: "8px 12px", marginBottom: 12,
            background: "rgba(226,74,74,0.08)", color: "#B13030",
            border: "1px solid rgba(226,74,74,0.25)",
            borderRadius: 6, fontSize: 12,
          }}>
            {error}
          </div>
        )}

        {tab === "analysis" && (
          <div style={{
            background: "#FFFFFF",
            border: `1px solid ${C.border}`,
            borderRadius: 10,
            padding: "16px 18px",
          }}>
            <div style={{
              fontSize: 9, fontWeight: 700, color: C.goldSoft,
              letterSpacing: "0.08em", textTransform: "uppercase",
              fontFamily: "'JetBrains Mono', monospace", marginBottom: 8,
              display: "flex", alignItems: "center", gap: 8,
            }}>
              Analysis
              {streaming && (
                <span style={{
                  display: "inline-flex", alignItems: "center", gap: 4,
                  color: C.gold,
                }}>
                  <span style={{
                    width: 6, height: 6, borderRadius: 3, background: C.gold,
                    animation: "pulse 1.2s infinite",
                  }} />
                  streaming
                </span>
              )}
            </div>
            <CitedText text={answer} citations={citations} onCiteClick={onCiteClick} />
            {!streaming && !answer && !error && (
              <div style={{ fontSize: 12, color: C.tertiary }}>No response yet.</div>
            )}

            {/* Inline citation chips — numbered pills to let the user jump between sources. */}
            {citations.length > 0 && (
              <div style={{
                marginTop: 14, paddingTop: 10,
                borderTop: `1px solid ${C.border}`,
                display: "flex", flexWrap: "wrap", gap: 6,
              }}>
                {citations.map((c) => (
                  <button
                    key={c.n}
                    onClick={() => onCiteClick(c)}
                    style={{
                      display: "inline-flex", alignItems: "center", gap: 6,
                      padding: "4px 8px 4px 4px",
                      fontSize: 11, fontWeight: 600,
                      color: C.secondary, background: "#FFFFFF",
                      border: `1px solid ${C.border}`, borderRadius: 12,
                      cursor: "pointer",
                    }}
                    title={c.label || c.title}
                  >
                    <span style={{
                      display: "inline-flex", alignItems: "center", justifyContent: "center",
                      minWidth: 16, height: 16, padding: "0 4px",
                      fontSize: 10, fontWeight: 800, fontFamily: "'JetBrains Mono', monospace",
                      color: C.ink, background: C.gold, borderRadius: 4,
                    }}>
                      {c.n}
                    </span>
                    <span style={{
                      maxWidth: 260, overflow: "hidden",
                      textOverflow: "ellipsis", whiteSpace: "nowrap",
                    }}>
                      {c.title || c.label}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {tab === "figures" && (
          <div style={{
            background: "#FFFFFF",
            border: `1px solid ${C.border}`,
            borderRadius: 10,
            padding: figures.length > 0 ? 16 : 24,
          }}>
            <div style={{
              fontSize: 9, fontWeight: 700, color: C.goldSoft,
              letterSpacing: "0.08em", textTransform: "uppercase",
              fontFamily: "'JetBrains Mono', monospace", marginBottom: 10,
            }}>
              Figures
            </div>
            {figures.length === 0 ? (
              <div style={{ fontSize: 12, color: C.tertiary }}>
                No figures in the matched documents.
              </div>
            ) : (
              <div style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
                gap: 12,
              }}>
                {figures.map((f, i) => (
                  <div key={`${f.docId}-${i}`}
                    style={{ cursor: "pointer" }}
                    onClick={() => onSelectDoc?.(f.docId)}
                  >
                    <FigureCard figure={f.figure} />
                    <div style={{
                      fontSize: 10, color: C.tertiary, marginTop: 4,
                      fontFamily: "'JetBrains Mono', monospace",
                    }}>
                      from {f.docId} · {f.title}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {tab === "documents" && (
          <div style={{
            background: "#FFFFFF",
            border: `1px solid ${C.border}`,
            borderRadius: 10,
            padding: "12px 16px",
          }}>
            <div style={{
              fontSize: 9, fontWeight: 700, color: C.tertiary,
              letterSpacing: "0.08em", textTransform: "uppercase",
              fontFamily: "'JetBrains Mono', monospace", marginBottom: 8,
            }}>
              Matched documents ({docsList.length})
            </div>
            {docsList.length === 0 ? (
              <div style={{ fontSize: 12, color: C.tertiary }}>
                {streaming ? "Ranking documents…" : "No matches."}
              </div>
            ) : (
              <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
                {docsList.map((d) => (
                  <li key={d.id}
                    style={{
                      display: "flex", gap: 10, padding: "10px 0",
                      borderTop: `1px solid ${C.border}`,
                    }}>
                    <button
                      onClick={() => onSelectDoc?.(d.id)}
                      style={{
                        display: "inline-flex", alignItems: "center",
                        padding: "2px 8px", height: 20, flexShrink: 0,
                        fontSize: 10, fontWeight: 800, fontFamily: "'JetBrains Mono', monospace",
                        color: C.ink, background: C.gold, border: "none", borderRadius: 4,
                        cursor: "pointer",
                      }}
                    >
                      {d.id}
                    </button>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{
                        fontSize: 12, fontWeight: 600, color: C.ink,
                        cursor: "pointer",
                      }} onClick={() => onSelectDoc?.(d.id)}>
                        {d.title}
                      </div>
                      <div style={{
                        fontSize: 10, color: C.tertiary, marginTop: 2,
                        fontFamily: "'JetBrains Mono', monospace",
                      }}>
                        {d.source}{d.date ? ` · ${d.date}` : ""}{d.score != null ? ` · relevance ${d.score}` : ""}
                      </div>
                      {d.snippet && (
                        <div style={{
                          fontSize: 11, color: C.secondary, marginTop: 4, lineHeight: 1.4,
                        }}>
                          {d.snippet}{d.snippet.length >= 180 ? "…" : ""}
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.4; transform: scale(1.3); }
        }
      `}</style>
    </div>
  );
}
