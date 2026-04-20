import React, { useMemo, useState } from "react";
import { useTrackerList } from "../../hooks/useTracker";
import TrackerDetail from "./TrackerDetail";

/* ─────────────────────────────────────────────────────────────────
   TrackerTable — dense sortable table with filter toolbar.
   Columns: name · region · voltage · status · developer ·
            construction_year · operation_year · capex · source_type ·
            confidence
   Pagination is server-side via the list hook (cursor + limit).
   ──────────────────────────────────────────────────────────────── */

const C = {
  gold: "#F5B731",
  goldSoft: "#C9A64B",
  goldSurface: "rgba(245,183,49,0.10)",
  goldBorder: "rgba(245,183,49,0.32)",
  ivory: "#FBF8F2",
  ink: "#0F1318",
  secondary: "#4B5563",
  tertiary: "#9C9590",
  border: "#E8EAED",
  bg: "#FFFFFF",
  rowHover: "#FAF4E3",
};

const STATUS_PILL = {
  planned:            { bg: "#FDF2D1", fg: "#8B6A00" },
  under_construction: { bg: "#FCEAB8", fg: "#7A5A00" },
  complete:           { bg: "#D8F0DC", fg: "#1C6B3A" },
  cancelled:          { bg: "#FBD8D5", fg: "#8E1E1E" },
};

const VOLTAGE_BANDS = [
  { id: "",        label: "All voltages" },
  { id: "ehv_400", label: "400 kV" },
  { id: "hv_275",  label: "275 kV" },
  { id: "hv_132",  label: "132 kV" },
  { id: "mv_33",   label: "33 kV" },
  { id: "lv_11",   label: "11 kV" },
];

const COLUMNS = [
  { key: "substation_name",      label: "Name",         sortable: true, minWidth: 220 },
  { key: "region",               label: "Region",       sortable: true, minWidth: 120 },
  { key: "voltage_kv_primary",   label: "kV",           sortable: true, align: "right", minWidth: 56, mono: true },
  { key: "construction_status",  label: "Status",       sortable: true, minWidth: 140, render: "status" },
  { key: "developer",            label: "Developer",    sortable: true, minWidth: 100 },
  { key: "construction_year",    label: "Constr.",      sortable: true, align: "right", minWidth: 72, mono: true },
  { key: "operation_year",       label: "Op.",          sortable: true, align: "right", minWidth: 72, mono: true },
  { key: "capex_gbp_millions",   label: "Capex £m",     sortable: true, align: "right", minWidth: 84, mono: true },
  { key: "source_type",          label: "Source",       sortable: true, minWidth: 90 },
  { key: "confidence",           label: "Conf.",        sortable: true, align: "right", minWidth: 70, render: "confidence" },
];

function confidencePill(v) {
  if (v == null) return { bg: "#EEE", fg: "#666", label: "—" };
  if (v >= 0.75) return { bg: "#D8F0DC", fg: "#1C6B3A", label: v.toFixed(2) };
  if (v >= 0.5)  return { bg: "#FDF2D1", fg: "#8B6A00", label: v.toFixed(2) };
  return { bg: "#FBD8D5", fg: "#8E1E1E", label: v.toFixed(2) };
}

const PAGE_SIZE = 50;

export default function TrackerTable({ admin = false }) {
  const [filters, setFilters] = useState({
    q: "", region: "", status: "", developer: "", voltage_band: "",
    year_min: "", year_max: "",
  });
  const [sort, setSort] = useState("operation_year:asc");
  const [cursor, setCursor] = useState(0);
  const [selectedId, setSelectedId] = useState(null);

  const queryFilters = useMemo(() => {
    const out = { sort, cursor, limit: PAGE_SIZE };
    Object.entries(filters).forEach(([k, v]) => {
      if (v === "" || v == null) return;
      if (k === "year_min" || k === "year_max") out[k] = Number(v);
      else out[k] = v;
    });
    return out;
  }, [filters, sort, cursor]);

  const { rows, total, next_cursor, loading, error } = useTrackerList(queryFilters);

  // Sort handler
  const onHeaderClick = (key) => {
    const [curKey, curDir] = sort.split(":");
    const nextDir = curKey === key && curDir === "asc" ? "desc" : "asc";
    setSort(`${key}:${nextDir}`);
    setCursor(0);
  };
  const sortArrow = (key) => {
    const [curKey, curDir] = sort.split(":");
    if (curKey !== key) return <span style={{ opacity: 0.25 }}> ↕</span>;
    return <span style={{ color: C.goldSoft }}> {curDir === "asc" ? "↑" : "↓"}</span>;
  };

  const setF = (k) => (v) => { setFilters((f) => ({ ...f, [k]: v })); setCursor(0); };

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", background: C.ivory }}>
      {/* Filter toolbar */}
      <div
        style={{
          padding: "12px 20px",
          borderBottom: `1px solid ${C.border}`,
          background: C.bg,
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
          alignItems: "center",
          fontFamily: "'DM Sans', sans-serif",
        }}
      >
        <input
          type="text"
          placeholder="Search name, developer, county…"
          value={filters.q}
          onChange={(e) => setF("q")(e.target.value)}
          style={{ ...inputStyle, flex: 1, minWidth: 220 }}
        />
        <select value={filters.region} onChange={(e) => setF("region")(e.target.value)} style={inputStyle}>
          <option value="">All regions</option>
          {UK_REGIONS.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <select value={filters.voltage_band} onChange={(e) => setF("voltage_band")(e.target.value)} style={inputStyle}>
          {VOLTAGE_BANDS.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
        </select>
        <select value={filters.status} onChange={(e) => setF("status")(e.target.value)} style={inputStyle}>
          <option value="">All statuses</option>
          <option value="planned">Planned</option>
          <option value="under_construction">Under construction</option>
          <option value="complete">Complete</option>
          <option value="cancelled">Cancelled</option>
        </select>
        <select value={filters.developer} onChange={(e) => setF("developer")(e.target.value)} style={inputStyle}>
          <option value="">All developers</option>
          {DEVELOPERS.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <input
          type="number"
          placeholder="Year from"
          value={filters.year_min}
          onChange={(e) => setF("year_min")(e.target.value)}
          style={{ ...inputStyle, width: 100 }}
        />
        <input
          type="number"
          placeholder="Year to"
          value={filters.year_max}
          onChange={(e) => setF("year_max")(e.target.value)}
          style={{ ...inputStyle, width: 100 }}
        />
        <div style={{ marginLeft: "auto", fontSize: 11, color: C.tertiary, fontFamily: "'JetBrains Mono', monospace" }}>
          {loading ? "…" : `${rows.length} of ${total}`}
        </div>
      </div>

      {/* Table */}
      <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
        {error && (
          <div style={{ padding: 16, color: "#8E1E1E", fontSize: 12 }}>Failed to load: {error}</div>
        )}
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontFamily: "'DM Sans', sans-serif",
            fontSize: 12,
            background: C.bg,
          }}
        >
          <thead style={{ position: "sticky", top: 0, background: C.bg, zIndex: 2 }}>
            <tr>
              {COLUMNS.map((c) => (
                <th
                  key={c.key}
                  onClick={() => c.sortable && onHeaderClick(c.key)}
                  style={{
                    textAlign: c.align || "left",
                    padding: "10px 12px",
                    fontSize: 10,
                    textTransform: "uppercase",
                    letterSpacing: "0.06em",
                    color: C.tertiary,
                    fontWeight: 700,
                    borderBottom: `1px solid ${C.goldBorder}`,
                    background: C.bg,
                    cursor: c.sortable ? "pointer" : "default",
                    minWidth: c.minWidth,
                    userSelect: "none",
                    whiteSpace: "nowrap",
                  }}
                >
                  {c.label}{c.sortable && sortArrow(c.key)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.project_id}
                onClick={() => setSelectedId(r.project_id)}
                style={{
                  cursor: "pointer",
                  borderBottom: `1px solid ${C.border}`,
                  background: selectedId === r.project_id ? C.rowHover : "transparent",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = selectedId === r.project_id ? C.rowHover : "#FAFAFA"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = selectedId === r.project_id ? C.rowHover : "transparent"; }}
              >
                {COLUMNS.map((c) => {
                  const v = r[c.key];
                  const td = {
                    padding: "10px 12px",
                    color: C.ink,
                    textAlign: c.align || "left",
                    fontFamily: c.mono ? "'JetBrains Mono', monospace" : undefined,
                    whiteSpace: c.key === "substation_name" ? "nowrap" : "nowrap",
                    maxWidth: c.key === "substation_name" ? 280 : undefined,
                    overflow: c.key === "substation_name" ? "hidden" : undefined,
                    textOverflow: c.key === "substation_name" ? "ellipsis" : undefined,
                  };
                  if (c.render === "status") {
                    const s = STATUS_PILL[v] || { bg: "#EEE", fg: "#333" };
                    return (
                      <td key={c.key} style={td}>
                        <span
                          style={{
                            padding: "2px 8px",
                            borderRadius: 10,
                            background: s.bg,
                            color: s.fg,
                            fontSize: 10,
                            fontWeight: 700,
                            textTransform: "uppercase",
                            letterSpacing: "0.04em",
                          }}
                        >
                          {String(v || "").replace(/_/g, " ")}
                        </span>
                      </td>
                    );
                  }
                  if (c.render === "confidence") {
                    const p = confidencePill(v);
                    return (
                      <td key={c.key} style={td}>
                        <span
                          style={{
                            padding: "2px 8px",
                            borderRadius: 10,
                            background: p.bg,
                            color: p.fg,
                            fontSize: 11,
                            fontWeight: 700,
                            fontFamily: "'JetBrains Mono', monospace",
                          }}
                        >
                          {p.label}
                        </span>
                      </td>
                    );
                  }
                  if (v == null) return <td key={c.key} style={{ ...td, color: C.tertiary }}>—</td>;
                  if (c.key === "capex_gbp_millions") {
                    return <td key={c.key} style={td}>{v.toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>;
                  }
                  return <td key={c.key} style={td}>{String(v)}</td>;
                })}
              </tr>
            ))}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length} style={{ padding: 28, textAlign: "center", color: C.tertiary, fontSize: 12 }}>
                  No substations match your filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div
        style={{
          padding: "10px 20px",
          borderTop: `1px solid ${C.border}`,
          background: C.bg,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          fontSize: 11,
          color: C.secondary,
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        <span>
          rows {cursor + 1}–{cursor + rows.length} / {total}
        </span>
        <div style={{ display: "flex", gap: 6 }}>
          <button
            type="button"
            disabled={cursor === 0}
            onClick={() => setCursor(Math.max(0, cursor - PAGE_SIZE))}
            style={pagerBtn(cursor === 0)}
          >
            Prev
          </button>
          <button
            type="button"
            disabled={!next_cursor}
            onClick={() => next_cursor != null && setCursor(next_cursor)}
            style={pagerBtn(!next_cursor)}
          >
            Next
          </button>
        </div>
      </div>

      <TrackerDetail
        id={selectedId}
        onClose={() => setSelectedId(null)}
        admin={admin}
      />
    </div>
  );
}

// ── Shared bits ─────────────────────────────────────────────────
const inputStyle = {
  padding: "7px 10px",
  borderRadius: 6,
  border: `1px solid ${C.border}`,
  background: C.bg,
  color: C.ink,
  fontSize: 12,
  fontFamily: "'DM Sans', sans-serif",
  outline: "none",
};

const pagerBtn = (disabled) => ({
  padding: "5px 12px",
  borderRadius: 6,
  border: `1px solid ${C.border}`,
  background: disabled ? C.bg : "transparent",
  color: disabled ? C.tertiary : C.ink,
  fontSize: 11,
  cursor: disabled ? "not-allowed" : "pointer",
  fontFamily: "'JetBrains Mono', monospace",
});

// Keep these small fixed lists in sync with the tracker schema; the
// backend filter payload accepts any string so no need to enumerate
// in the API layer.
const UK_REGIONS = [
  "NGET-North", "NGET-South", "NGET-East", "NGET-Midlands", "NGET-Wales", "NGET-Yorkshire",
  "EPN", "SPN", "LPN", "UKPN-LPN",
  "SEPD", "SHET", "SPEN",
  "SWL", "NGED-EMID", "NGED-WMID",
  "NIE",
];

const DEVELOPERS = [
  "NGET", "SHE-T", "SPT",
  "UKPN", "NGED", "SSEN", "SPEN", "NPG", "ENWL",
  "NIE Networks",
];
