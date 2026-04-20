import React from "react";
import styles from "../TrackerLanding.module.css";
import preview from "../../../data/tracker-preview.json";

/**
 * DataPreviewTable — 5 realistic UK sample rows rendered against a subset
 * of the 30-field SubstationProject schema. Horizontally scrollable on
 * narrow viewports.
 *
 * Columns are picked for marketing density — not all 30 fields — but every
 * value is a real projection of the canonical record in tracker-preview.json.
 */
const COLUMNS = [
  { key: "project_id", label: "Project ID", cell: (r) => <span className={styles.cellMono}>{r.project_id}</span> },
  { key: "substation_name", label: "Name" },
  { key: "developer", label: "Developer" },
  { key: "voltage", label: "Voltage", cell: (r) => r.voltage_description || fmtVoltage(r) },
  { key: "capacity_mva", label: "MVA", cell: (r) => <span className={styles.cellMono}>{r.equipment_capacity_mva?.toLocaleString("en-GB") ?? "—"}</span> },
  { key: "status", label: "Status", cell: (r) => <StatusPill status={r.construction_status} /> },
  { key: "op", label: "Op. date", cell: (r) => <span className={styles.cellMono}>{r.operation_date_detail || r.operation_year || "—"}</span> },
  {
    key: "capex",
    label: "Capex (£m)",
    cell: (r) =>
      <span className={styles.cellMono}>
        {r.capex_gbp_millions
          ? `£${r.capex_gbp_millions.toLocaleString("en-GB")} (${r.capex_price_base_year}/${String((r.capex_price_base_year ?? 0) + 1).padStart(2, "0")})`
          : "—"}
      </span>,
  },
  { key: "source", label: "Source", cell: (r) => <span className={styles.cellMono}>{r.source_type}</span> },
];

function fmtVoltage(r) {
  if (r.voltage_kv_primary && r.voltage_kv_secondary) return `${r.voltage_kv_primary}/${r.voltage_kv_secondary} kV`;
  if (r.voltage_kv_primary) return `${r.voltage_kv_primary} kV`;
  return "—";
}

function StatusPill({ status }) {
  const label = (status || "unknown").replace(/_/g, " ");
  const klass = `${styles.statusPill} ${styles[status] || ""}`;
  return <span className={klass}>{label}</span>;
}

export default function DataPreviewTable() {
  return (
    <div className={styles.tableWrap}>
      <div className={styles.tableScroll}>
        <table className={styles.table}>
          <thead>
            <tr>
              {COLUMNS.map((c) => <th key={c.key}>{c.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {preview.map((row) => (
              <tr key={row.project_id}>
                {COLUMNS.map((c) => (
                  <td key={c.key}>
                    {c.cell ? c.cell(row) : (row[c.key] ?? <span className={styles.cellMuted}>—</span>)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className={styles.tableFooter}>
        <span className={styles.tableFooterText}>
          Preview: <span className={styles.tableFooterStat}>5</span> of an estimated
          {" "}<span className={styles.tableFooterStat}>600–900</span> UK substation projects (TO + DNO).
        </span>
        <span className={styles.tableFooterText}>
          Schema parity: <span className={styles.tableFooterStat}>30</span> canonical fields · Refresh: monthly
        </span>
      </div>
    </div>
  );
}
