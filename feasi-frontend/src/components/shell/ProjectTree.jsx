import React, { useState, useMemo, useCallback, useRef, useEffect } from "react";

const STAGE_CODE = {
  prospect: "PROS", screened: "SCRN", grid_applied: "GAPP", grid_offer: "GOFF",
  planning: "PLAN", fid: "FID", construction: "CONS", energised: "ENRG",
};

const VERDICT_COLOR = {
  "GO": "var(--cds-support-success)",
  "CAUTION": "var(--cds-support-warning)",
  "NO-GO": "var(--cds-support-error)",
};

const TECH_GLYPH = { bess: "▮", dc: "▦", solar: "☀", wind: "⇌", hybrid: "◈" };

function VerdictDot({ verdict }) {
  if (!verdict) return null;
  return (
    <span
      className="pt-dot"
      style={{ background: VERDICT_COLOR[verdict] || "var(--cds-text-helper)" }}
      title={verdict}
    />
  );
}

function StageBadge({ stage }) {
  if (!stage) return null;
  return <span className="pt-stage">{STAGE_CODE[stage] || stage.slice(0, 4).toUpperCase()}</span>;
}

function hasBlockerInTree(project) {
  if (project.blocker || project.verdict === "NO-GO") return true;
  return (project.sites || []).some((s) => s.verdict === "NO-GO");
}

function matchesQuery(str, q) {
  if (!q) return true;
  return (str || "").toLowerCase().includes(q.toLowerCase());
}

// Stable DOM ids — let aria-activedescendant point at a row element.
function rowId(kind, id) { return `pt-row-${kind}-${id}`; }

export default function ProjectTree({
  portfolios = [],
  selectedPortfolioId = null,
  selectedProjectId = null,
  selectedSiteId = null,
  onSelectPortfolio = () => {},
  onSelectProject = () => {},
  onSelectSite = () => {},
  onNewProject = () => {},
  onNewPortfolio = () => {},
}) {
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState(() => new Set());
  const searchRef = useRef(null);
  const listRef = useRef(null);
  // Index of the active (keyboard-focused) row in the flattened visible list.
  const [activeIdx, setActiveIdx] = useState(0);

  const toggle = useCallback((key) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const filtered = useMemo(() => {
    if (!query) return portfolios;
    return portfolios
      .map((pf) => ({
        ...pf,
        projects: (pf.projects || []).filter(
          (p) =>
            matchesQuery(p.name, query) ||
            matchesQuery(pf.name, query) ||
            (p.sites || []).some((s) => matchesQuery(s.name, query))
        ),
      }))
      .filter((pf) => matchesQuery(pf.name, query) || pf.projects.length > 0);
  }, [portfolios, query]);

  // Flatten the visible rows for keyboard navigation. Respects collapse state.
  const visibleRows = useMemo(() => {
    const rows = [];
    for (const pf of filtered) {
      const pfKey = `pf-${pf.portfolio_id}`;
      rows.push({
        kind: "portfolio",
        id: pf.portfolio_id,
        portfolioId: pf.portfolio_id,
        hasChildren: (pf.projects || []).length > 0,
        collapsed: collapsed.has(pfKey),
        data: pf,
      });
      if (collapsed.has(pfKey)) continue;
      for (const p of (pf.projects || [])) {
        const pKey = `p-${p.project_id}`;
        rows.push({
          kind: "project",
          id: p.project_id,
          portfolioId: pf.portfolio_id,
          projectId: p.project_id,
          hasChildren: (p.sites || []).length > 0,
          collapsed: collapsed.has(pKey),
          data: p,
        });
        if (collapsed.has(pKey)) continue;
        for (const s of (p.sites || [])) {
          rows.push({
            kind: "site",
            id: s.candidate_id,
            portfolioId: pf.portfolio_id,
            projectId: p.project_id,
            siteId: s.candidate_id,
            hasChildren: false,
            data: s,
          });
        }
      }
    }
    return rows;
  }, [filtered, collapsed]);

  // Keep active index in bounds when the visible list shrinks.
  useEffect(() => {
    if (activeIdx >= visibleRows.length) {
      setActiveIdx(Math.max(0, visibleRows.length - 1));
    }
  }, [visibleRows.length, activeIdx]);

  // Sync active index to whatever the parent says is selected (e.g. when
  // another component navigates projects).
  useEffect(() => {
    const target = selectedSiteId
      ? visibleRows.findIndex((r) => r.kind === "site" && r.id === selectedSiteId)
      : selectedProjectId
        ? visibleRows.findIndex((r) => r.kind === "project" && r.id === selectedProjectId)
        : selectedPortfolioId
          ? visibleRows.findIndex((r) => r.kind === "portfolio" && r.id === selectedPortfolioId)
          : -1;
    if (target >= 0) setActiveIdx(target);
    // intentionally not depending on visibleRows — only syncs on prop change
  }, [selectedPortfolioId, selectedProjectId, selectedSiteId]); // eslint-disable-line react-hooks/exhaustive-deps

  const openRow = useCallback((row) => {
    if (!row) return;
    if (row.kind === "portfolio") onSelectPortfolio(row.id);
    else if (row.kind === "project") onSelectProject(row.id, row.portfolioId);
    else if (row.kind === "site") onSelectSite(row.id, row.projectId, row.portfolioId);
  }, [onSelectPortfolio, onSelectProject, onSelectSite]);

  const toggleRow = useCallback((row) => {
    if (!row || !row.hasChildren) return;
    if (row.kind === "portfolio") toggle(`pf-${row.id}`);
    else if (row.kind === "project") toggle(`p-${row.id}`);
  }, [toggle]);

  // Key handling on the tree root.
  const onKeyDown = useCallback((e) => {
    // "/" focuses search input (even when the root already has focus).
    if (e.key === "/" && !e.metaKey && !e.ctrlKey && !e.altKey) {
      e.preventDefault();
      searchRef.current?.focus();
      searchRef.current?.select();
      return;
    }
    // Only handle arrow/enter/space when the tree list (not the search box)
    // is the active target.
    if (document.activeElement === searchRef.current) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(visibleRows.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(0, i - 1));
    } else if (e.key === "Home") {
      e.preventDefault();
      setActiveIdx(0);
    } else if (e.key === "End") {
      e.preventDefault();
      setActiveIdx(visibleRows.length - 1);
    } else if (e.key === "ArrowRight") {
      const row = visibleRows[activeIdx];
      if (row?.hasChildren && row.collapsed) {
        e.preventDefault();
        toggleRow(row);
      } else if (row?.hasChildren && !row.collapsed && activeIdx < visibleRows.length - 1) {
        e.preventDefault();
        setActiveIdx(activeIdx + 1);
      }
    } else if (e.key === "ArrowLeft") {
      const row = visibleRows[activeIdx];
      if (row?.hasChildren && !row.collapsed) {
        e.preventDefault();
        toggleRow(row);
      } else {
        // Jump to parent row if any.
        e.preventDefault();
        if (row?.kind === "site") {
          const parentIdx = visibleRows.findIndex((r) => r.kind === "project" && r.id === row.projectId);
          if (parentIdx >= 0) setActiveIdx(parentIdx);
        } else if (row?.kind === "project") {
          const parentIdx = visibleRows.findIndex((r) => r.kind === "portfolio" && r.id === row.portfolioId);
          if (parentIdx >= 0) setActiveIdx(parentIdx);
        }
      }
    } else if (e.key === "Enter") {
      e.preventDefault();
      openRow(visibleRows[activeIdx]);
    } else if (e.key === " " || e.key === "Spacebar") {
      e.preventDefault();
      toggleRow(visibleRows[activeIdx]);
    }
  }, [visibleRows, activeIdx, openRow, toggleRow]);

  // Scroll the active row into view.
  useEffect(() => {
    const row = visibleRows[activeIdx];
    if (!row) return;
    const el = document.getElementById(rowId(row.kind, row.id));
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ block: "nearest" });
    }
  }, [activeIdx, visibleRows]);

  const activeRow = visibleRows[activeIdx];
  const activeDescId = activeRow ? rowId(activeRow.kind, activeRow.id) : undefined;

  return (
    <div
      className="pt-root"
      onKeyDown={onKeyDown}
      tabIndex={0}
      role="tree"
      aria-activedescendant={activeDescId}
      aria-label="Project tree"
    >
      <div className="pt-searchbar">
        <input
          ref={searchRef}
          type="search"
          placeholder="Search projects…  ( / )"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="pt-search"
          aria-label="Search projects"
        />
      </div>
      <div className="pt-scroll" ref={listRef}>
        {filtered.length === 0 && (
          <div className="pt-empty">No portfolios. <button className="pt-link" onClick={onNewPortfolio}>Create one</button></div>
        )}
        {filtered.map((pf) => {
          const pfKey = `pf-${pf.portfolio_id}`;
          const isCollapsed = collapsed.has(pfKey);
          const projects = pf.projects || [];
          const pfRowId = rowId("portfolio", pf.portfolio_id);
          const pfSelected = selectedPortfolioId === pf.portfolio_id && !selectedProjectId;
          const pfActive = activeDescId === pfRowId;
          return (
            <div key={pf.portfolio_id} className="pt-group">
              <div
                id={pfRowId}
                role="treeitem"
                aria-expanded={!isCollapsed}
                aria-selected={pfSelected}
                className={
                  "pt-row pt-row-portfolio"
                  + (pfSelected ? " pt-selected" : "")
                  + (pfActive ? " pt-active" : "")
                }
                onClick={() => onSelectPortfolio(pf.portfolio_id)}
              >
                <button
                  className="pt-caret"
                  onClick={(e) => { e.stopPropagation(); toggle(pfKey); }}
                  aria-label={isCollapsed ? "Expand" : "Collapse"}
                  tabIndex={-1}
                >
                  {isCollapsed ? "▸" : "▾"}
                </button>
                <span className="pt-pf-name">{pf.name}</span>
                <span className="pt-count">{projects.length}</span>
                <button
                  className="pt-add"
                  onClick={(e) => { e.stopPropagation(); onNewProject(pf.portfolio_id); }}
                  title="New project"
                  aria-label="New project"
                  tabIndex={-1}
                >+</button>
              </div>
              {!isCollapsed && projects.map((p) => {
                const pKey = `p-${p.project_id}`;
                const pCollapsed = collapsed.has(pKey);
                const sites = p.sites || [];
                const blocked = hasBlockerInTree(p);
                const pSelected = selectedProjectId === p.project_id && !selectedSiteId;
                const prRowId = rowId("project", p.project_id);
                const prActive = activeDescId === prRowId;
                return (
                  <div key={p.project_id}>
                    <div
                      id={prRowId}
                      role="treeitem"
                      aria-expanded={sites.length ? !pCollapsed : undefined}
                      aria-selected={pSelected}
                      className={
                        "pt-row pt-row-project"
                        + (pSelected ? " pt-selected" : "")
                        + (prActive ? " pt-active" : "")
                      }
                      onClick={() => onSelectProject(p.project_id, pf.portfolio_id)}
                    >
                      <button
                        className="pt-caret"
                        onClick={(e) => { e.stopPropagation(); toggle(pKey); }}
                        aria-label={pCollapsed ? "Expand" : "Collapse"}
                        style={{ visibility: sites.length ? "visible" : "hidden" }}
                        tabIndex={-1}
                      >
                        {pCollapsed ? "▸" : "▾"}
                      </button>
                      <span className="pt-tech" aria-label={p.technology}>{TECH_GLYPH[p.technology] || "•"}</span>
                      <span className="pt-name">{p.name}</span>
                      <StageBadge stage={p.stage} />
                      <VerdictDot verdict={p.verdict} />
                      {blocked && <span className="pt-warn" title={p.blocker || "Blocker in this project"}>⚠</span>}
                    </div>
                    {!pCollapsed && sites.map((s) => {
                      const sSelected = selectedSiteId === s.candidate_id;
                      const sRowId = rowId("site", s.candidate_id);
                      const sActive = activeDescId === sRowId;
                      return (
                        <div
                          key={s.candidate_id}
                          id={sRowId}
                          role="treeitem"
                          aria-selected={sSelected}
                          className={
                            "pt-row pt-row-site"
                            + (sSelected ? " pt-selected" : "")
                            + (sActive ? " pt-active" : "")
                          }
                          onClick={() => onSelectSite(s.candidate_id, p.project_id, pf.portfolio_id)}
                        >
                          <span className="pt-indent" />
                          <span className="pt-name pt-name-site">
                            {s.is_preferred && <span className="pt-star" title="Preferred">★</span>}
                            {s.name || "(unnamed site)"}
                          </span>
                          <VerdictDot verdict={s.verdict} />
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
      <style>{`
        .pt-root {
          display: flex; flex-direction: column;
          width: 280px; height: 100%;
          background: var(--cds-layer-01);
          border-right: 1px solid var(--cds-border-subtle);
          font-family: "DM Sans", -apple-system, sans-serif;
          font-size: 13px;
          color: var(--cds-text-primary);
          outline: none;
        }
        .pt-root:focus-visible {
          box-shadow: inset 0 0 0 2px rgba(201,166,75,0.35);
        }
        .pt-searchbar {
          padding: 12px;
          border-bottom: 1px solid var(--cds-border-subtle);
          flex-shrink: 0;
        }
        .pt-search {
          width: 100%;
          padding: 8px 10px;
          border: 1px solid var(--cds-border-subtle);
          border-radius: 8px;
          background: var(--cds-layer-02);
          font-family: inherit; font-size: 13px;
          color: var(--cds-text-primary);
          outline: none;
          transition: border-color 120ms;
        }
        .pt-search:focus {
          border-color: #C9A64B;
          box-shadow: 0 0 0 3px rgba(201,166,75,0.18);
        }
        .pt-scroll {
          flex: 1; overflow-y: auto;
          padding: 4px 0;
        }
        .pt-empty {
          padding: 24px; text-align: center;
          color: var(--cds-text-helper); font-size: 13px;
        }
        .pt-link {
          background: none; border: none;
          color: #B5912F;
          font-weight: 600; cursor: pointer;
          padding: 0; font: inherit;
        }
        .pt-group { padding: 2px 0; }
        .pt-row {
          display: flex; align-items: center; gap: 6px;
          padding: 6px 10px;
          cursor: pointer;
          position: relative;
          border-left: 3px solid transparent;
          user-select: none;
        }
        .pt-row:hover { background: rgba(201,166,75,0.06); }
        .pt-selected {
          background: rgba(201,166,75,0.10);
          border-left-color: #C9A64B;
        }
        /* Keyboard cursor — a more visible gold rule than the plain
           selection, so "focused but not yet chosen" reads clearly. */
        .pt-active {
          outline: none;
          background: rgba(201,166,75,0.14);
          border-left: 3px solid #C9A64B;
          box-shadow: inset 0 0 0 1px rgba(201,166,75,0.25);
        }
        .pt-row-portfolio { font-weight: 600; }
        .pt-row-project { padding-left: 20px; }
        .pt-row-site { padding-left: 44px; color: var(--cds-text-secondary); }
        .pt-caret {
          background: none; border: none; padding: 0;
          width: 14px; height: 14px; flex-shrink: 0;
          color: var(--cds-text-helper); font-size: 10px;
          cursor: pointer; display: flex;
          align-items: center; justify-content: center;
        }
        .pt-pf-name { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .pt-name { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .pt-name-site { font-size: 12px; display: flex; align-items: center; gap: 4px; }
        .pt-tech {
          width: 14px; color: var(--cds-text-helper);
          font-size: 11px; text-align: center;
        }
        .pt-count {
          background: var(--cds-layer-03);
          color: var(--cds-text-secondary);
          padding: 1px 6px; border-radius: 10px;
          font-size: 10px; font-family: var(--mono);
          font-weight: 600;
        }
        .pt-add {
          background: none; border: 1px solid transparent;
          color: var(--cds-text-helper); font-size: 14px;
          width: 20px; height: 20px; border-radius: 6px;
          cursor: pointer; line-height: 1;
          display: flex; align-items: center; justify-content: center;
          transition: all 120ms;
        }
        .pt-add:hover {
          background: #C9A64B;
          color: #fff;
          border-color: #C9A64B;
        }
        .pt-stage {
          background: var(--cds-layer-03);
          color: var(--cds-text-secondary);
          padding: 1px 6px; border-radius: 4px;
          font-size: 9px; font-family: var(--mono);
          font-weight: 700; letter-spacing: 0.04em;
        }
        .pt-dot {
          width: 8px; height: 8px; border-radius: 50%;
          flex-shrink: 0;
        }
        .pt-warn {
          color: var(--cds-support-warning);
          font-size: 12px;
        }
        .pt-star {
          color: #C9A64B;
          font-size: 11px;
        }
        .pt-indent { width: 14px; flex-shrink: 0; }
      `}</style>
    </div>
  );
}
