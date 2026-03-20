import React, { useState, useCallback } from "react";
import api from "../../services/api";

const ACCENT = "#3f51b5";

export default function RegulatoryRAGCard() {
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = useCallback(async () => {
    if (!query.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const data = await api.rag.query(query, source || undefined);
      setResult(data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [query, source]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="card" style={{ borderLeft: `3px solid ${ACCENT}` }}>
      <h3 style={{ margin: "0 0 8px", color: ACCENT }}>Regulatory Search</h3>

      <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about UK energy regulation..."
          style={{
            flex: 1, padding: "6px 8px", fontSize: 13,
            background: "#F7F8FA", border: `1px solid ${ACCENT}`,
            color: "#eee", borderRadius: 4,
          }}
        />
        <select
          value={source}
          onChange={(e) => setSource(e.target.value)}
          style={{
            padding: "4px 6px", fontSize: 12,
            background: "#F7F8FA", border: `1px solid ${ACCENT}`,
            color: "#eee", borderRadius: 4,
          }}
        >
          <option value="">All sources</option>
          <option value="ofgem">Ofgem</option>
          <option value="desnz">DESNZ</option>
        </select>
        <button
          className="tab-btn-sm"
          style={{ background: ACCENT, color: "#fff" }}
          onClick={handleSubmit}
          disabled={loading}
        >{loading ? "..." : "Ask"}</button>
      </div>

      {loading && <div className="spinner-sm" />}

      {result && (
        <div>
          <div style={{
            background: "#F7F8FA", borderRadius: 6, padding: 10,
            fontSize: 13, lineHeight: 1.5, marginBottom: 8,
            borderLeft: `3px solid ${ACCENT}`,
          }}>
            {result.answer}
          </div>

          {result.sources?.length > 0 && (
            <details style={{ fontSize: 12 }}>
              <summary style={{ cursor: "pointer", color: ACCENT, marginBottom: 4 }}>
                {result.sources.length} source{result.sources.length !== 1 ? "s" : ""}
              </summary>
              {result.sources.map((s, i) => (
                <div key={s.chunk_id || i} style={{ padding: "4px 0", borderBottom: "1px solid #333" }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <strong style={{ color: ACCENT }}>[{i + 1}] {s.doc_title}</strong>
                    <span style={{ color: "#888" }}>{s.source}</span>
                  </div>
                  <div style={{ color: "#999", fontSize: 11 }}>
                    {s.content?.substring(0, 150)}...
                  </div>
                  {s.doc_url && (
                    <a href={s.doc_url} target="_blank" rel="noopener noreferrer"
                       style={{ color: ACCENT, fontSize: 11 }}>
                      View document
                    </a>
                  )}
                </div>
              ))}
            </details>
          )}
        </div>
      )}

      {!result && !loading && (
        <div style={{ color: "#666", fontSize: 12 }}>
          Search Ofgem decisions, DESNZ consultations, and regulatory guidance.
        </div>
      )}
    </div>
  );
}
