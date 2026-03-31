import React, { useState, useCallback, useEffect, useRef } from "react";
import api from "../services/api";

/* ── Constants ─────────────────────────────────────────────────────────────── */
const GOLD = "#D4A018";
const ENERGY_TERMS = [
  "solar farm", "wind farm", "battery storage", "substation",
  "planning application", "renewable energy", "grid connection",
  "environmental impact", "solar panels", "wind turbine",
  "energy storage", "power station", "national grid", "net zero",
];

/* ── Helpers ───────────────────────────────────────────────────────────────── */
function fmtDate(dt) {
  if (!dt) return "--";
  const d = new Date(dt);
  if (isNaN(d)) return dt.slice(0, 10);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

function SnippetText({ html }) {
  return <span dangerouslySetInnerHTML={{ __html: html || "" }} />;
}

/* ── Autocomplete dropdown ─────────────────────────────────────────────────── */
function TermSuggestions({ query, onSelect, visible }) {
  if (!visible || !query) return null;
  const q = query.toLowerCase();
  const matches = ENERGY_TERMS.filter(t => t.includes(q) && t !== q).slice(0, 6);
  if (!matches.length) return null;
  return (
    <div className="cs-suggestions">
      {matches.map(t => (
        <button key={t} className="cs-suggestion" onClick={() => onSelect(t)}>
          {t}
        </button>
      ))}
    </div>
  );
}

/* ── Energy Pulse summary strip ────────────────────────────────────────────── */
function EnergyPulse({ summary, loading }) {
  if (loading) return <div className="cs-pulse cs-loading">Loading energy pulse...</div>;
  if (!summary) return null;

  const topTerms = (summary.terms || []).slice(0, 5);
  return (
    <div className="cs-pulse">
      <div className="cs-pulse-header">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={GOLD} strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
        <span className="cs-pulse-title">Energy Pulse</span>
        <span className="cs-pulse-count">
          {summary.total_energy_mentions || 0} mentions across {summary.authorities_indexed || 0} authorities
        </span>
      </div>
      {topTerms.length > 0 && (
        <div className="cs-pulse-terms">
          {topTerms.map(t => (
            <span key={t.term} className="cs-term-badge">
              {t.term} <span className="cs-term-count">{t.count}</span>
            </span>
          ))}
        </div>
      )}
      {(summary.recent_discussions || []).length > 0 && (
        <div className="cs-pulse-recent">
          {summary.recent_discussions.slice(0, 3).map((r, i) => (
            <div key={i} className="cs-pulse-item">
              <span className="cs-pulse-auth">{(r.authority || "").replace(/_/g, " ")}</span>
              <span className="cs-pulse-date">{fmtDate(r.datetime)}</span>
              <span className="cs-pulse-snippet"><SnippetText html={r.snippet} /></span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════════
   CouncilSearchPanel -- right slide-in panel for council transcript search
   ═══════════════════════════════════════════════════════════════════════════════ */
export default function CouncilSearchPanel({ onClose, embedded }) {
  /* ── State ── */
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [authorities, setAuthorities] = useState([]);
  const [selectedAuths, setSelectedAuths] = useState([]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const [summary, setSummary] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  const [showSuggestions, setShowSuggestions] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 20;

  const inputRef = useRef(null);

  /* ── Load authorities and energy summary on mount ── */
  useEffect(() => {
    api.council.authorities().then(data => {
      if (data?.authorities) setAuthorities(data.authorities);
    });
    setSummaryLoading(true);
    api.council.energySummary().then(data => {
      if (data) setSummary(data);
      setSummaryLoading(false);
    }).catch(() => setSummaryLoading(false));
  }, []);

  /* ── Search ── */
  const doSearch = useCallback(async (searchQuery, pageNum = 0) => {
    const q = searchQuery || query;
    if (!q.trim()) return;
    setLoading(true);
    setError(null);
    setPage(pageNum);
    try {
      const authFilter = selectedAuths.length ? selectedAuths.join(",") : undefined;
      const data = await api.council.search(
        q, authFilter, dateFrom || undefined, dateTo || undefined,
        PAGE_SIZE, pageNum * PAGE_SIZE,
      );
      if (data) {
        setResults(data.results || []);
        setTotal(data.total || 0);
      }
    } catch (e) {
      setError(e.message || "Search failed");
    }
    setLoading(false);
  }, [query, selectedAuths, dateFrom, dateTo]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter") {
      setShowSuggestions(false);
      doSearch(query, 0);
    }
  };

  const selectTerm = (term) => {
    setQuery(term);
    setShowSuggestions(false);
    doSearch(term, 0);
  };

  const toggleAuth = (authId) => {
    setSelectedAuths(prev =>
      prev.includes(authId) ? prev.filter(a => a !== authId) : [...prev, authId]
    );
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className={`gc-panel cs-panel${embedded ? " embedded" : ""}`}>
      {/* ── Header ── */}
      <div className="gc-panel-header">
        <div className="gc-panel-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 21v-4a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4v4" />
            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
            <circle cx="9" cy="7" r="4" />
          </svg>
          Council Intelligence
        </div>
        <button className="gc-close" onClick={onClose} title="Close">&times;</button>
      </div>

      {/* ── Energy Pulse ── */}
      <EnergyPulse summary={summary} loading={summaryLoading} />

      {/* ── Search bar ── */}
      <div className="cs-search-bar">
        <div className="cs-input-wrap">
          <svg className="cs-search-icon" width="14" height="14" viewBox="0 0 24 24"
               fill="none" stroke="rgba(255,255,255,0.4)" strokeWidth="2">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            className="cs-input"
            placeholder="Search council transcripts..."
            value={query}
            onChange={e => { setQuery(e.target.value); setShowSuggestions(true); }}
            onKeyDown={handleKeyDown}
            onFocus={() => setShowSuggestions(true)}
            onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
          />
          <TermSuggestions query={query} onSelect={selectTerm} visible={showSuggestions} />
        </div>
        <button className="cs-search-btn" onClick={() => doSearch(query, 0)} disabled={loading}>
          {loading ? "..." : "Search"}
        </button>
        <button
          className={`cs-filter-toggle${showFilters ? " active" : ""}`}
          onClick={() => setShowFilters(f => !f)}
          title="Filters"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
          </svg>
        </button>
      </div>

      {/* ── Filters ── */}
      {showFilters && (
        <div className="cs-filters">
          <div className="cs-filter-section">
            <div className="cs-filter-label">Authorities</div>
            <div className="cs-auth-list">
              {authorities.map(a => (
                <button
                  key={a.id}
                  className={`cs-auth-chip${selectedAuths.includes(a.id) ? " selected" : ""}`}
                  onClick={() => toggleAuth(a.id)}
                >
                  {a.name}
                  {a.transcript_count > 0 && (
                    <span className="cs-auth-count">{a.transcript_count}</span>
                  )}
                </button>
              ))}
              {authorities.length === 0 && (
                <span className="cs-no-data">No authorities indexed yet. Run a refresh first.</span>
              )}
            </div>
          </div>
          <div className="cs-filter-row">
            <div className="cs-filter-field">
              <label className="cs-filter-label">From</label>
              <input type="date" className="cs-date-input" value={dateFrom}
                     onChange={e => setDateFrom(e.target.value)} />
            </div>
            <div className="cs-filter-field">
              <label className="cs-filter-label">To</label>
              <input type="date" className="cs-date-input" value={dateTo}
                     onChange={e => setDateTo(e.target.value)} />
            </div>
          </div>
        </div>
      )}

      {/* ── Quick terms ── */}
      <div className="cs-quick-terms">
        {ENERGY_TERMS.slice(0, 8).map(t => (
          <button key={t} className="cs-quick-term" onClick={() => selectTerm(t)}>
            {t}
          </button>
        ))}
      </div>

      {/* ── Results ── */}
      <div className="gc-panel-body cs-results">
        {error && <div className="gc-error">{error}</div>}

        {loading && <div className="gc-loading">Searching transcripts...</div>}

        {!loading && results && results.length === 0 && (
          <div className="cs-no-results">
            No council meeting mentions found for "{query}".
            {authorities.length === 0 && " Try refreshing the index first."}
          </div>
        )}

        {!loading && results && results.length > 0 && (
          <>
            <div className="cs-results-header">
              {total} result{total !== 1 ? "s" : ""} for "{query}"
            </div>
            <div className="cs-result-list">
              {results.map((r, i) => (
                <div key={`${r.uid}-${i}`} className="cs-result-item">
                  <div className="cs-result-meta">
                    <span className="cs-result-authority">
                      {(r.authority || "").replace(/_/g, " ")}
                    </span>
                    <span className="cs-result-date">{fmtDate(r.datetime)}</span>
                  </div>
                  <div className="cs-result-title">{r.title || "Untitled meeting"}</div>
                  <div className="cs-result-snippet">
                    <SnippetText html={r.snippet} />
                  </div>
                  {r.link && (
                    <a href={r.link} target="_blank" rel="noopener noreferrer"
                       className="cs-result-link">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                           stroke="currentColor" strokeWidth="2">
                        <polygon points="5 3 19 12 5 21 5 3" />
                      </svg>
                      Watch at {r.start_time || "start"}
                    </a>
                  )}
                </div>
              ))}
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="cs-pagination">
                <button className="cs-page-btn" disabled={page === 0}
                        onClick={() => doSearch(query, page - 1)}>
                  Prev
                </button>
                <span className="cs-page-info">
                  Page {page + 1} of {totalPages}
                </span>
                <button className="cs-page-btn" disabled={page >= totalPages - 1}
                        onClick={() => doSearch(query, page + 1)}>
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
