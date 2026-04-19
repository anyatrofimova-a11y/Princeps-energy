import React from "react";

/**
 * COAMatrix — Courses-of-Action comparison matrix.
 *
 * A side-by-side decision matrix where each row is a scenario / site / option
 * and each column is a decision criterion. Cells are traffic-light coloured
 * based on a per-cell `score` ("good" | "ok" | "bad" | "neutral").
 *
 * Props:
 *   rows           — array of { id, label, subtitle, cells: { [colKey]: { value, score } } }
 *   columns        — array of { key, label }
 *   onRowClick     — fn(rowId) fired when a row is clicked
 *   selectedRowId  — id of currently-selected row (gets gold left accent)
 */
export default function COAMatrix({ rows = [], columns = [], onRowClick, selectedRowId = null }) {
  const handleRowClick = (rowId) => {
    if (typeof onRowClick === "function") onRowClick(rowId);
  };

  const handleKeyDown = (e, rowId) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handleRowClick(rowId);
    }
  };

  return (
    <div className="coa-wrap">
      <div className="coa-scroll">
        <table className="coa-table">
          <thead>
            <tr>
              <th className="coa-th coa-th-label coa-sticky">Option</th>
              {columns.map((col) => (
                <th key={col.key} className="coa-th">{col.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const isSelected = row.id === selectedRowId;
              return (
                <tr
                  key={row.id}
                  className={`coa-row ${isSelected ? "coa-row-selected" : ""}`}
                  onClick={() => handleRowClick(row.id)}
                  onKeyDown={(e) => handleKeyDown(e, row.id)}
                  tabIndex={0}
                  role="button"
                  aria-selected={isSelected}
                >
                  <td className="coa-td coa-td-label coa-sticky">
                    <div className="coa-row-name">{row.label}</div>
                    {row.subtitle && <div className="coa-row-subtitle">{row.subtitle}</div>}
                  </td>
                  {columns.map((col) => {
                    const cell = (row.cells && row.cells[col.key]) || {};
                    const score = cell.score || "neutral";
                    return (
                      <td key={col.key} className="coa-td">
                        <span className={`coa-cell coa-cell-${score}`}>
                          {cell.value != null && cell.value !== "" ? cell.value : "—"}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <style>{`
        .coa-wrap { width: 100%; }
        .coa-scroll { width: 100%; overflow-x: auto;
          border: 1px solid var(--cds-border-subtle); border-radius: 10px;
          background: var(--cds-layer-01); }
        .coa-table { width: 100%; border-collapse: separate; border-spacing: 0;
          font-family: inherit; }

        .coa-th { text-align: left; padding: 14px 18px;
          font-size: 11px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase;
          color: var(--cds-text-helper); background: var(--cds-layer-01);
          border-bottom: 1px solid #E5E7EB; white-space: nowrap; }
        .coa-th-label { min-width: 220px; }

        .coa-row { cursor: pointer; transition: background 120ms ease; outline: none; }
        .coa-row:hover { background: rgba(0, 0, 0, 0.025); }
        .coa-row:focus-visible { background: rgba(0, 0, 0, 0.04); }
        .coa-row-selected { background: rgba(212, 175, 55, 0.06); }
        .coa-row-selected:hover { background: rgba(212, 175, 55, 0.10); }

        .coa-td { padding: 14px 18px; border-bottom: 1px solid #E5E7EB;
          vertical-align: middle; font-size: 13px; color: var(--ink);
          background: inherit; }
        .coa-row:last-child .coa-td { border-bottom: none; }

        .coa-td-label { padding-left: 18px; position: relative; }
        .coa-row-selected .coa-td-label::before {
          content: ""; position: absolute; left: 0; top: 0; bottom: 0;
          width: 3px; background: var(--gold, #D4AF37);
        }
        .coa-row-name { font-size: 14px; font-weight: 600; color: var(--ink);
          line-height: 1.3; }
        .coa-row-subtitle { font-size: 12px; color: var(--cds-text-helper);
          margin-top: 3px; line-height: 1.3; }

        .coa-sticky { position: sticky; left: 0; z-index: 1;
          background: var(--cds-layer-01); }
        .coa-row:hover .coa-sticky { background: #F7F5F1; }
        .coa-row-selected .coa-sticky { background: #FBF7EC; }

        .coa-cell { display: inline-block; padding: 5px 10px; border-radius: 6px;
          font-size: 13px; font-weight: 500; line-height: 1.3;
          font-variant-numeric: tabular-nums; white-space: nowrap; }

        .coa-cell-good { background: #DEF7E5; color: #1E7B3A; }
        .coa-cell-ok { background: #FFF4D6; color: #92660A; }
        .coa-cell-bad { background: #FCE5E5; color: #B23B3B; }
        .coa-cell-neutral { background: transparent; color: var(--ink); padding-left: 0; padding-right: 0; }
      `}</style>
    </div>
  );
}
