import React, { useCallback, useState } from "react";

/**
 * ReverseSearchBar — godmode direction #2.
 * One-line brief → ranked UK parcels via /api/v2/prospect/reverse-search.
 *
 * Positioned at the top of WorkspaceHome. The single most quotable feature
 * in a pitch meeting. Accepts briefs like:
 *   "80 MW, by Q3 2027, ≤150ms to London"
 *   "20 MW BESS, East Midlands, 2h duration"
 */
export default function ReverseSearchBar({ onResults = () => {} }) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastParsed, setLastParsed] = useState(null);

  const submit = useCallback(async () => {
    const q = query.trim();
    if (!q || loading) return;
    setLoading(true); setError(null);
    try {
      const r = await fetch("/api/v2/prospect/reverse-search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q, top_n: 40 }),
      });
      if (!r.ok) throw new Error(`${r.status}`);
      const data = await r.json();
      setLastParsed(data.parsed_params || null);
      onResults(data);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [query, loading, onResults]);

  return (
    <div className="rsb-root">
      <div className="rsb-label">Reverse-search</div>
      <div className="rsb-row">
        <input
          className="rsb-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
          placeholder='e.g. "80 MW, by Q3 2027, ≤150ms to London"'
          disabled={loading}
        />
        <button
          className="rsb-btn"
          onClick={submit}
          disabled={!query.trim() || loading}
        >
          {loading ? "Searching…" : "Find sites →"}
        </button>
      </div>
      {lastParsed && (
        <div className="rsb-parsed">
          Parsed:
          {Object.entries(lastParsed).map(([k, v]) =>
            <span key={k} className="rsb-chip"><b>{k}</b> {String(v)}</span>
          )}
        </div>
      )}
      {error && <div className="rsb-err">Search failed: {error}</div>}
      <style>{`
        .rsb-root {
          background: #FFFFFF;
          border: 1px solid #E8E5DF;
          border-radius: 12px;
          padding: 18px 20px;
          display: flex; flex-direction: column; gap: 10px;
          font-family: "DM Sans", sans-serif;
          box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }
        .rsb-label {
          font-size: 10px; font-weight: 700; letter-spacing: 0.06em;
          text-transform: uppercase; color: #6B6560;
        }
        .rsb-row { display: flex; gap: 10px; align-items: stretch; }
        .rsb-input {
          flex: 1;
          padding: 10px 14px;
          font-size: 14px;
          font-family: inherit;
          border: 1px solid #E8E5DF;
          border-radius: 8px;
          outline: none;
          color: #1A1714;
          background: #F7F8FA;
        }
        .rsb-input:focus {
          border-color: #F5B731;
          background: #fff;
          box-shadow: 0 0 0 3px rgba(245,183,49,0.12);
        }
        .rsb-btn {
          padding: 0 18px;
          background: #F5B731;
          color: #fff;
          border: none;
          border-radius: 8px;
          font-family: inherit;
          font-size: 13px; font-weight: 700;
          cursor: pointer;
          white-space: nowrap;
        }
        .rsb-btn:hover:not(:disabled) { background: #E8A012; }
        .rsb-btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .rsb-parsed {
          font-size: 11px;
          color: #6B6560;
          display: flex; flex-wrap: wrap; gap: 6px;
          align-items: center;
        }
        .rsb-chip {
          background: rgba(245,183,49,0.12);
          color: #B5432A;
          border-radius: 4px;
          padding: 2px 7px;
          font-family: var(--mono, "JetBrains Mono"), monospace;
          font-size: 10px;
        }
        .rsb-chip b { color: #1A1714; margin-right: 4px; font-weight: 700; }
        .rsb-err {
          font-size: 11px; color: #b91c1c;
        }
      `}</style>
    </div>
  );
}
