import React, { useState, useMemo, useCallback } from "react";

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

  return (
    <div className="pt-root">
      <div className="pt-searchbar">
        <input
          type="search"
          placeholder="Search projects…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="pt-search"
          aria-label="Search projects"
        />
      </div>
      <div className="pt-scroll">
        {filtered.length === 0 && (
          <div className="pt-empty">No portfolios. <button className="pt-link" onClick={onNewPortfolio}>Create one</button></div>
        )}
        {filtered.map((pf) => {
          const pfKey = `pf-${pf.portfolio_id}`;
          const isCollapsed = collapsed.has(pfKey);
          const projects = pf.projects || [];
          const isSelected = selectedPortfolioId === pf.portfolio_id && !selectedProjectId;
          return (
            <div key={pf.portfolio_id} className="pt-group">
              <div
                className={"pt-row pt-row-portfolio" + (isSelected ? " pt-selected" : "")}
                onClick={() => onSelectPortfolio(pf.portfolio_id)}
              >
                <button
                  className="pt-caret"
                  onClick={(e) => { e.stopPropagation(); toggle(pfKey); }}
                  aria-label={isCollapsed ? "Expand" : "Collapse"}
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
                >+</button>
              </div>
              {!isCollapsed && projects.map((p) => {
                const pKey = `p-${p.project_id}`;
                const pCollapsed = collapsed.has(pKey);
                const sites = p.sites || [];
                const blocked = hasBlockerInTree(p);
                const pSelected = selectedProjectId === p.project_id && !selectedSiteId;
                return (
                  <div key={p.project_id}>
                    <div
                      className={"pt-row pt-row-project" + (pSelected ? " pt-selected" : "")}
                      onClick={() => onSelectProject(p.project_id, pf.portfolio_id)}
                    >
                      <button
                        className="pt-caret"
                        onClick={(e) => { e.stopPropagation(); toggle(pKey); }}
                        aria-label={pCollapsed ? "Expand" : "Collapse"}
                        style={{ visibility: sites.length ? "visible" : "hidden" }}
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
                      return (
                        <div
                          key={s.candidate_id}
                          className={"pt-row pt-row-site" + (sSelected ? " pt-selected" : "")}
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
          border-color: var(--gold);
          box-shadow: 0 0 0 3px rgba(var(--accent-rgb), 0.12);
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
          color: var(--gold-dark);
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
        .pt-row:hover { background: rgba(var(--accent-rgb), 0.06); }
        .pt-selected {
          background: rgba(var(--accent-rgb), 0.08);
          border-left-color: var(--gold);
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
        .pt-pf-name { flex: 1; }
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
          background: var(--gold);
          color: #fff;
          border-color: var(--gold);
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
          color: var(--gold);
          font-size: 11px;
        }
        .pt-indent { width: 14px; flex-shrink: 0; }
      `}</style>
    </div>
  );
}
