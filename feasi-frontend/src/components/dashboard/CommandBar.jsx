import React, { useState, useCallback, useRef, useEffect } from "react";

const COMMANDS = [
  { id: "new_site", label: "New site assessment", shortcut: "⌘N", category: "command" },
  { id: "grid_study", label: "Run grid study", shortcut: "⌘G", category: "command" },
  { id: "financial", label: "Financial model", shortcut: "⌘F", category: "command" },
  { id: "report", label: "Generate PDF report", shortcut: "⌘R", category: "command" },
  { id: "parcel_search", label: "Search land parcels", shortcut: "⌘P", category: "command" },
  { id: "optimizer", label: "System optimizer", shortcut: "⌘O", category: "command" },
];

const QUICK_ACTIONS = [
  { id: "qa_demand", label: "Demand forecast", category: "quick" },
  { id: "qa_grid_twin", label: "Open Grid Twin", category: "quick" },
  { id: "qa_procurement", label: "Procurement search", category: "quick" },
  { id: "qa_compliance", label: "Compliance check", category: "quick" },
];

export default function CommandBar({ onSearchSelect, alertCount = 0 }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [showPalette, setShowPalette] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const inputRef = useRef(null);
  const timerRef = useRef(null);
  const dropdownRef = useRef(null);

  // Global "/" shortcut
  useEffect(() => {
    const handler = (e) => {
      if (e.key === "/" && !e.ctrlKey && !e.metaKey && document.activeElement !== inputRef.current) {
        e.preventDefault();
        inputRef.current?.focus();
        setShowPalette(true);
        setOpen(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const handleChange = useCallback((e) => {
    const q = e.target.value;
    setQuery(q);
    setActiveIndex(-1);

    if (q === "/") {
      setShowPalette(true);
      setOpen(true);
      setResults([...COMMANDS, ...QUICK_ACTIONS]);
      return;
    }

    if (!q.trim()) {
      setResults([]);
      setOpen(false);
      setShowPalette(false);
      return;
    }

    setShowPalette(false);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(async () => {
      const lq = q.toLowerCase().replace(/^\/\s*/, "");
      const matched = COMMANDS.filter(c => c.label.toLowerCase().includes(lq));
      const quickMatched = QUICK_ACTIONS.filter(c => c.label.toLowerCase().includes(lq));

      let apiResults = [];
      try {
        const r = await fetch("/api/regulatory/search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: lq, limit: 4 }),
        });
        if (r.ok) {
          const data = await r.json();
          if (Array.isArray(data)) apiResults = data.map(d => ({ ...d, category: "regulatory" }));
        }
      } catch {}

      const all = [...matched, ...quickMatched, ...apiResults];
      setResults(all);
      setOpen(all.length > 0);
    }, 250);
  }, []);

  const handleSelect = useCallback((item) => {
    setOpen(false);
    setShowPalette(false);
    setQuery("");
    setActiveIndex(-1);
    onSearchSelect?.(item);
  }, [onSearchSelect]);

  const handleKeyDown = useCallback((e) => {
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex(i => (i + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex(i => (i - 1 + results.length) % results.length);
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      handleSelect(results[activeIndex]);
    } else if (e.key === "Escape") {
      setOpen(false);
      setShowPalette(false);
      inputRef.current?.blur();
    }
  }, [open, results, activeIndex, handleSelect]);

  const dateStr = new Date().toLocaleDateString("en-GB", {
    weekday: "short", day: "numeric", month: "short", year: "numeric",
  });

  const grouped = {
    command: results.filter(r => r.category === "command"),
    quick: results.filter(r => r.category === "quick"),
    regulatory: results.filter(r => r.category === "regulatory"),
  };

  let flatIndex = -1;
  const getIndex = () => { flatIndex++; return flatIndex; };

  return (
    <>
      <style>{`
        .cb-bar {
          position: sticky;
          top: 0;
          z-index: 100;
          display: flex;
          align-items: center;
          gap: 16px;
          padding: 10px 24px;
          background: var(--cds-layer-01, #fff);
          border-bottom: 1px solid var(--border, #E8EAED);
          box-sizing: border-box;
        }
        .cb-logo-section {
          display: flex;
          align-items: center;
          gap: 10px;
          flex-shrink: 0;
        }
        .cb-live-badge {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 2px 7px;
          border-radius: 6px;
          background: rgba(34, 197, 94, 0.08);
          font-size: 10px;
          font-weight: 700;
          color: #16a34a;
          letter-spacing: 0.04em;
          text-transform: uppercase;
        }
        .cb-live-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: #22c55e;
          animation: cb-pulse 2s infinite;
        }
        @keyframes cb-pulse {
          0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(34,197,94,0.5); }
          50% { opacity: 0.7; box-shadow: 0 0 0 4px rgba(34,197,94,0); }
        }
        .cb-search-wrap {
          flex: 1;
          display: flex;
          justify-content: center;
          position: relative;
          max-width: 580px;
          margin: 0 auto;
        }
        .cb-search-input {
          width: 500px;
          max-width: 100%;
          height: 40px;
          padding: 0 16px 0 40px;
          border: 1px solid var(--border, #E8EAED);
          border-radius: var(--radius-md, 12px);
          background: var(--cds-layer-02, #F7F8FA);
          font-family: "DM Sans", sans-serif;
          font-size: 14px;
          color: var(--ink, #0F1318);
          outline: none;
          transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
        }
        .cb-search-input::placeholder {
          color: var(--muted-light, #9CA3AF);
          font-size: 13px;
        }
        .cb-search-input:focus {
          border-color: var(--gold, #F5B731);
          box-shadow: 0 0 0 3px var(--accent-glow, rgba(245,183,49,0.12));
          background: #fff;
        }
        .cb-search-icon {
          position: absolute;
          left: 13px;
          top: 50%;
          transform: translateY(-50%);
          color: var(--muted-light, #9CA3AF);
          pointer-events: none;
          font-size: 15px;
        }
        .cb-slash-hint {
          position: absolute;
          right: 12px;
          top: 50%;
          transform: translateY(-50%);
          padding: 2px 6px;
          border-radius: 4px;
          border: 1px solid var(--border, #E8EAED);
          font-family: var(--mono, "JetBrains Mono"), monospace;
          font-size: 11px;
          color: var(--muted-light, #9CA3AF);
          background: #fff;
          pointer-events: none;
        }
        .cb-dropdown {
          position: absolute;
          top: calc(100% + 6px);
          left: 50%;
          transform: translateX(-50%);
          width: 500px;
          max-width: 100%;
          max-height: 360px;
          overflow-y: auto;
          background: #fff;
          border: 1px solid var(--border, #E8EAED);
          border-radius: var(--radius-md, 12px);
          box-shadow: 0 12px 32px rgba(0,0,0,0.12);
          z-index: 200;
        }
        .cb-section-label {
          padding: 8px 14px 4px;
          font-size: 10px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.06em;
          color: var(--muted, #6B7280);
        }
        .cb-divider {
          height: 1px;
          background: var(--border, #E8EAED);
          margin: 4px 0;
        }
        .cb-item {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 8px 14px;
          cursor: pointer;
          font-size: 13px;
          color: var(--ink, #0F1318);
          transition: background 0.1s;
          border-radius: 6px;
          margin: 0 4px;
        }
        .cb-item:hover, .cb-item.cb-active {
          background: var(--accent-surface, rgba(245,183,49,0.06));
        }
        .cb-item-shortcut {
          font-family: var(--mono, "JetBrains Mono"), monospace;
          font-size: 11px;
          color: var(--muted-light, #9CA3AF);
        }
        .cb-item-tag {
          font-size: 10px;
          padding: 1px 6px;
          border-radius: 4px;
          background: var(--accent-surface, rgba(245,183,49,0.06));
          color: var(--gold-dark, #E8A012);
          font-weight: 600;
        }
        .cb-right {
          display: flex;
          align-items: center;
          gap: 14px;
          flex-shrink: 0;
        }
        .cb-alert-badge {
          position: relative;
          width: 32px;
          height: 32px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 8px;
          cursor: pointer;
          transition: background 0.15s;
        }
        .cb-alert-badge:hover {
          background: var(--cds-layer-02, #F7F8FA);
        }
        .cb-alert-count {
          position: absolute;
          top: 2px;
          right: 2px;
          min-width: 16px;
          height: 16px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 8px;
          background: #dc2626;
          color: #fff;
          font-size: 10px;
          font-weight: 700;
          padding: 0 4px;
        }
        .cb-date {
          font-size: 12px;
          color: var(--muted-light, #9CA3AF);
          white-space: nowrap;
        }
      `}</style>

      <div className="cb-bar">
        {/* Left: Logo + LIVE */}
        <div className="cb-logo-section">
          <img src="/logo-princeps.png" alt="Princeps" style={{ width: 28, height: 28, objectFit: "contain" }} />
          <span style={{ fontSize: 16, fontWeight: 800, color: "var(--ink)", letterSpacing: "-0.02em" }}>Princeps</span>
          <span className="cb-live-badge">
            <span className="cb-live-dot" />
            LIVE
          </span>
        </div>

        {/* Center: Command search */}
        <div className="cb-search-wrap">
          <svg className="cb-search-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <circle cx="7" cy="7" r="5" /><path d="M11 11l3.5 3.5" />
          </svg>
          <input
            ref={inputRef}
            className="cb-search-input"
            type="text"
            placeholder='Search sites, run analysis, simulate scenarios... or type "/"'
            value={query}
            onChange={handleChange}
            onFocus={() => { if (query) setOpen(true); }}
            onBlur={() => setTimeout(() => { setOpen(false); setShowPalette(false); }, 200)}
            onKeyDown={handleKeyDown}
          />
          {!query && <span className="cb-slash-hint">/</span>}

          {open && results.length > 0 && (
            <div className="cb-dropdown" ref={dropdownRef}>
              {grouped.command.length > 0 && (
                <>
                  <div className="cb-section-label">Commands</div>
                  {grouped.command.map(r => {
                    const idx = getIndex();
                    return (
                      <div key={r.id} className={`cb-item${idx === activeIndex ? " cb-active" : ""}`}
                        onMouseDown={() => handleSelect(r)}>
                        <span>{r.label}</span>
                        {r.shortcut && <span className="cb-item-shortcut">{r.shortcut}</span>}
                      </div>
                    );
                  })}
                </>
              )}

              {grouped.quick.length > 0 && (
                <>
                  {grouped.command.length > 0 && <div className="cb-divider" />}
                  <div className="cb-section-label">Quick Actions</div>
                  {grouped.quick.map(r => {
                    const idx = getIndex();
                    return (
                      <div key={r.id} className={`cb-item${idx === activeIndex ? " cb-active" : ""}`}
                        onMouseDown={() => handleSelect(r)}>
                        <span>{r.label}</span>
                      </div>
                    );
                  })}
                </>
              )}

              {grouped.regulatory.length > 0 && (
                <>
                  {(grouped.command.length > 0 || grouped.quick.length > 0) && <div className="cb-divider" />}
                  <div className="cb-section-label">Regulatory Docs</div>
                  {grouped.regulatory.map((r, i) => {
                    const idx = getIndex();
                    return (
                      <div key={`reg-${i}`} className={`cb-item${idx === activeIndex ? " cb-active" : ""}`}
                        onMouseDown={() => handleSelect(r)}>
                        <span>{r.title || r.chunk_text?.slice(0, 60) || "Document"}</span>
                        {r.source && <span className="cb-item-tag">{r.source}</span>}
                      </div>
                    );
                  })}
                </>
              )}
              <div style={{ height: 4 }} />
            </div>
          )}
        </div>

        {/* Right: Alerts + Date */}
        <div className="cb-right">
          <div className="cb-alert-badge" title="Alerts">
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="var(--muted, #6B7280)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M7.5 15.5a1.5 1.5 0 003 0M9 2a5 5 0 00-5 5c0 2.5-1 4-1.5 4.5h13c-.5-.5-1.5-2-1.5-4.5a5 5 0 00-5-5z" />
            </svg>
            {alertCount > 0 && <span className="cb-alert-count">{alertCount > 99 ? "99+" : alertCount}</span>}
          </div>
          <span className="cb-date">{dateStr}</span>
        </div>
      </div>
    </>
  );
}
