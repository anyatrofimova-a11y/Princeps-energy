import React from "react";

const TAB_LABELS = {
  overview: "Overview",
  sites: "Sites",
  grid: "Grid",
  demand: "Demand",
  planning: "Planning",
  financial: "Financial",
  reports: "Reports & Logs",
};

export default function Breadcrumb({ items = [], currentTab = null, onNavigate = () => {} }) {
  return (
    <nav className="bc-root" aria-label="Breadcrumb">
      <ol className="bc-list">
        {items.map((item, i) => {
          const isLast = i === items.length - 1 && !currentTab;
          return (
            <React.Fragment key={i}>
              <li className="bc-item">
                {item.href && !isLast ? (
                  <button className="bc-link" onClick={() => onNavigate(item.href, item)}>
                    {item.label}
                  </button>
                ) : (
                  <span className="bc-current">{item.label}</span>
                )}
              </li>
              {(i < items.length - 1 || currentTab) && (
                <li className="bc-sep" aria-hidden="true">›</li>
              )}
            </React.Fragment>
          );
        })}
        {currentTab && (
          <li className="bc-item bc-tab">
            <span className="bc-current">{TAB_LABELS[currentTab] || currentTab}</span>
          </li>
        )}
      </ol>
      <style>{`
        .bc-root {
          display: flex; align-items: center;
          height: 40px;
          padding: 0 20px;
          background: var(--cds-layer-01);
          border-bottom: 1px solid var(--cds-border-subtle);
          font-family: "DM Sans", -apple-system, sans-serif;
          font-size: 13px;
        }
        .bc-list {
          display: flex; align-items: center; gap: 8px;
          list-style: none; margin: 0; padding: 0;
        }
        .bc-item { display: flex; align-items: center; }
        .bc-link {
          background: none; border: none; padding: 0;
          color: var(--cds-text-secondary);
          cursor: pointer; font: inherit;
          transition: color 120ms;
        }
        .bc-link:hover { color: var(--gold-dark); }
        .bc-current {
          color: var(--cds-text-primary);
          font-weight: 600;
        }
        .bc-sep {
          color: var(--cds-text-helper);
          font-size: 14px;
          list-style: none;
        }
        .bc-tab .bc-current {
          color: var(--gold-dark);
        }
      `}</style>
    </nav>
  );
}
