import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";

/**
 * ConnectorHealthDashboard
 *
 * Operational dashboard for every data connector the backend runs.
 * Columns: name, status pill, last_refreshed, rows_total, rows_stale_days.
 * Sortable by any column. Each row exposes a Refresh button that POSTs
 * /api/connectors/{name}/refresh (BOT-G's endpoint). Schema-hash changes
 * surface in a sub-row, expandable per connector.
 *
 * Renders a friendly "Data feed not yet wired" state when
 * GET /api/connectors/health 404s, so the layout is reviewable.
 */

const LIGHT_GOLD = "#F5E9C8";
const GOLD = "#C9A64B";
const INK = "#1a1a1a";

const STATUS_COLORS = {
  green:   { bg: "#DCFCE7", border: "#16A34A", text: "#166534", label: "Healthy" },
  amber:   { bg: "#FEF3C7", border: "#F59E0B", text: "#92400E", label: "Stale" },
  red:     { bg: "#FEE2E2", border: "#DC2626", text: "#991B1B", label: "Broken" },
  unknown: { bg: "#F3F4F6", border: "#9CA3AF", text: "#4B5563", label: "Unknown" },
};

function inferStatus(c) {
  if (c.status) return c.status; // backend-provided wins
  if (c.error || c.last_error) return "red";
  const stale = c.rows_stale_days ?? c.stale_days ?? 0;
  if (stale > 30) return "red";
  if (stale > 7) return "amber";
  return "green";
}

export default function ConnectorHealthDashboard() {
  const navigate = useNavigate();

  const [connectors, setConnectors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [feedOk, setFeedOk] = useState(true);
  const [errorMsg, setErrorMsg] = useState(null);
  const [sortKey, setSortKey] = useState("name");
  const [sortDir, setSortDir] = useState("asc");
  const [expandedId, setExpandedId] = useState(null);
  const [refreshing, setRefreshing] = useState({}); // { connectorName: true }

  const abortRef = useRef(null);

  const loadHealth = useCallback(() => {
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = new AbortController();
    setLoading(true);
    setErrorMsg(null);
    fetch("/api/connectors/health", { signal: abortRef.current.signal })
      .then(async (res) => {
        if (res.status === 404) { setFeedOk(false); return null; }
        if (!res.ok) { setErrorMsg(`Server returned ${res.status}`); return null; }
        setFeedOk(true);
        return res.json();
      })
      .then((data) => {
        if (data) {
          const list = Array.isArray(data) ? data : (data.connectors || []);
          setConnectors(list);
        }
        setLoading(false);
      })
      .catch((err) => {
        if (err.name !== "AbortError") {
          setErrorMsg(err.message || "Network error");
          setLoading(false);
        }
      });
  }, []);

  useEffect(() => {
    loadHealth();
    return () => { if (abortRef.current) abortRef.current.abort(); };
  }, [loadHealth]);

  const handleSort = useCallback((key) => {
    setSortKey(prev => {
      if (prev === key) {
        setSortDir(d => d === "asc" ? "desc" : "asc");
        return key;
      }
      setSortDir("asc");
      return key;
    });
  }, []);

  const handleRefresh = useCallback(async (name) => {
    setRefreshing(r => ({ ...r, [name]: true }));
    try {
      const res = await fetch(`/api/connectors/${encodeURIComponent(name)}/refresh`, {
        method: "POST",
      });
      if (!res.ok && res.status !== 202) {
        console.warn(`[ConnectorHealth] refresh ${name} → ${res.status}`);
      }
      // Re-load health after a short delay so the server has a chance to update.
      setTimeout(() => loadHealth(), 600);
    } catch (err) {
      console.warn(`[ConnectorHealth] refresh ${name} failed`, err);
    } finally {
      setRefreshing(r => { const next = { ...r }; delete next[name]; return next; });
    }
  }, [loadHealth]);

  const sorted = useMemo(() => {
    const copy = [...connectors];
    copy.sort((a, b) => {
      let av, bv;
      switch (sortKey) {
        case "status":
          av = inferStatus(a); bv = inferStatus(b);
          const order = { red: 0, amber: 1, green: 2, unknown: 3 };
          av = order[av] ?? 99; bv = order[bv] ?? 99;
          break;
        case "last_refreshed":
          av = a.last_refreshed ? new Date(a.last_refreshed).getTime() : 0;
          bv = b.last_refreshed ? new Date(b.last_refreshed).getTime() : 0;
          break;
        case "rows_total":
          av = Number(a.rows_total || 0); bv = Number(b.rows_total || 0);
          break;
        case "rows_stale_days":
          av = Number(a.rows_stale_days ?? a.stale_days ?? 0);
          bv = Number(b.rows_stale_days ?? b.stale_days ?? 0);
          break;
        case "name":
        default:
          av = (a.name || "").toLowerCase(); bv = (b.name || "").toLowerCase();
      }
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return copy;
  }, [connectors, sortKey, sortDir]);

  const counts = useMemo(() => {
    const c = { green: 0, amber: 0, red: 0, unknown: 0 };
    for (const conn of connectors) c[inferStatus(conn)] = (c[inferStatus(conn)] || 0) + 1;
    return c;
  }, [connectors]);

  return (
    <div style={styles.root}>
      <header style={styles.header}>
        <button onClick={() => navigate(-1)} style={styles.backBtn} aria-label="Back">
          &larr; Back
        </button>
        <div>
          <div style={styles.title}>Connector health</div>
          <div style={styles.subtitle}>
            {connectors.length} connectors · {counts.green} healthy · {counts.amber} stale · {counts.red} broken
          </div>
        </div>
        <div style={styles.headerRight}>
          {loading && <span style={styles.loadingPill}>Loading…</span>}
          {!feedOk && <span style={styles.warnPill}>Data feed not yet wired</span>}
          <button onClick={loadHealth} style={styles.primaryBtn} disabled={loading}>
            Refresh all
          </button>
        </div>
      </header>

      <div style={styles.body}>
        {!feedOk ? (
          <FeedOfflineSkeleton />
        ) : connectors.length === 0 && !loading ? (
          <div style={styles.emptyState}>
            No connectors reported by the backend. Either there are none registered,
            or the <span style={styles.mono}>/api/connectors/health</span> endpoint
            returned an empty list.
          </div>
        ) : (
          <div style={styles.tableWrap}>
            <table style={styles.table}>
              <thead>
                <tr>
                  <SortableTh label="Connector" k="name" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                  <SortableTh label="Status" k="status" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                  <SortableTh label="Last refreshed" k="last_refreshed" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                  <SortableTh label="Rows total" k="rows_total" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} align="right" />
                  <SortableTh label="Stale (days)" k="rows_stale_days" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} align="right" />
                  <th style={styles.th}>&nbsp;</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((c) => {
                  const status = inferStatus(c);
                  const id = c.name || c.id;
                  const expanded = expandedId === id;
                  const schemaChanges = c.schema_hash_history || c.schema_changes || [];
                  return (
                    <React.Fragment key={id}>
                      <tr style={styles.tr}>
                        <td style={styles.td}>
                          <button
                            onClick={() => setExpandedId(expanded ? null : id)}
                            style={styles.rowToggle}
                            aria-label={expanded ? "Collapse" : "Expand"}
                          >
                            {expanded ? "▾" : "▸"}
                          </button>
                          <span style={styles.connectorName}>{c.name || "—"}</span>
                          {c.source && <span style={styles.connectorSource}> · {c.source}</span>}
                        </td>
                        <td style={styles.td}><StatusPill status={status} /></td>
                        <td style={styles.td}>{fmtTime(c.last_refreshed)}</td>
                        <td style={{ ...styles.td, textAlign: "right", fontFamily: "var(--mono, monospace)" }}>
                          {fmtNum(c.rows_total)}
                        </td>
                        <td style={{ ...styles.td, textAlign: "right", fontFamily: "var(--mono, monospace)" }}>
                          {fmtNum(c.rows_stale_days ?? c.stale_days)}
                        </td>
                        <td style={{ ...styles.td, textAlign: "right" }}>
                          <button
                            onClick={() => handleRefresh(c.name)}
                            style={styles.refreshBtn}
                            disabled={!!refreshing[c.name]}
                          >
                            {refreshing[c.name] ? "Refreshing…" : "Refresh"}
                          </button>
                        </td>
                      </tr>
                      {expanded && (
                        <tr>
                          <td colSpan={6} style={styles.detailRow}>
                            <SchemaHashSubRow connector={c} changes={schemaChanges} />
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {errorMsg && <div style={styles.errorBar}>{errorMsg}</div>}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────

function SortableTh({ label, k, sortKey, sortDir, onSort, align = "left" }) {
  const active = sortKey === k;
  return (
    <th
      onClick={() => onSort(k)}
      style={{ ...styles.th, textAlign: align, cursor: "pointer", userSelect: "none" }}
    >
      <span style={{ color: active ? INK : undefined, fontWeight: active ? 700 : 600 }}>
        {label}
      </span>
      <span style={styles.sortIndicator}>
        {active ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
      </span>
    </th>
  );
}

function StatusPill({ status }) {
  const s = STATUS_COLORS[status] || STATUS_COLORS.unknown;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      fontSize: 11, fontWeight: 600,
      padding: "3px 10px", borderRadius: 999,
      background: s.bg, color: s.text, border: `1px solid ${s.border}`,
    }}>
      <span style={{
        width: 7, height: 7, borderRadius: "50%", background: s.border, display: "inline-block",
      }} />
      {s.label}
    </span>
  );
}

function SchemaHashSubRow({ connector, changes }) {
  const currentHash = connector.schema_hash || connector.current_schema_hash || null;
  const rowsWithChanges = Array.isArray(changes) ? changes : [];
  return (
    <div style={styles.detailBox}>
      <div style={styles.detailTitle}>Schema hash history</div>
      <div style={styles.detailRowKV}>
        <span style={styles.detailKey}>Current hash</span>
        <span style={styles.detailVal}>{currentHash || "—"}</span>
      </div>
      {connector.schema_updated_at && (
        <div style={styles.detailRowKV}>
          <span style={styles.detailKey}>Last schema change</span>
          <span style={styles.detailVal}>{fmtTime(connector.schema_updated_at)}</span>
        </div>
      )}
      {rowsWithChanges.length > 0 ? (
        <table style={{ ...styles.table, marginTop: 10, background: "#fff" }}>
          <thead>
            <tr>
              <th style={styles.th}>Timestamp</th>
              <th style={styles.th}>Old hash</th>
              <th style={styles.th}>New hash</th>
              <th style={styles.th}>Change</th>
            </tr>
          </thead>
          <tbody>
            {rowsWithChanges.map((chg, i) => (
              <tr key={i}>
                <td style={styles.td}>{fmtTime(chg.at || chg.timestamp)}</td>
                <td style={{ ...styles.td, fontFamily: "var(--mono, monospace)" }}>{chg.old_hash || "—"}</td>
                <td style={{ ...styles.td, fontFamily: "var(--mono, monospace)" }}>{chg.new_hash || "—"}</td>
                <td style={styles.td}>{chg.description || chg.diff || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div style={{ ...styles.emptyState, padding: 8 }}>
          No schema changes recorded for this connector.
        </div>
      )}
    </div>
  );
}

function FeedOfflineSkeleton() {
  // Render the dashboard shell so the layout is reviewable without the endpoint live.
  const placeholders = ["OSM grid", "NGED headroom", "NESO TEC register", "EA flood zones", "MHCLG green belt"];
  return (
    <div style={styles.skeletonWrap}>
      <div style={styles.skeletonNotice}>
        <div style={styles.feedOfflineTitle}>Data feed not yet wired</div>
        <div style={styles.feedOfflineBody}>
          The endpoint <span style={styles.mono}>GET /api/connectors/health</span> is
          not yet responding. The dashboard layout and interactions are in place —
          data will populate once BOT-G ships the endpoint.
        </div>
        <div style={styles.feedOfflineHint}>
          Waiting on: <span style={styles.mono}>GET /api/connectors/health</span>
          {" · "}
          <span style={styles.mono}>POST /api/connectors/&#123;name&#125;/refresh</span>
        </div>
      </div>
      <table style={styles.table}>
        <thead>
          <tr>
            <th style={styles.th}>Connector</th>
            <th style={styles.th}>Status</th>
            <th style={styles.th}>Last refreshed</th>
            <th style={{ ...styles.th, textAlign: "right" }}>Rows total</th>
            <th style={{ ...styles.th, textAlign: "right" }}>Stale (days)</th>
            <th style={styles.th} />
          </tr>
        </thead>
        <tbody>
          {placeholders.map((name, i) => (
            <tr key={i}>
              <td style={styles.td}><span style={styles.connectorName}>{name}</span></td>
              <td style={styles.td}><StatusPill status="unknown" /></td>
              <td style={{ ...styles.td, color: "var(--muted, #6B7280)" }}>Awaiting data</td>
              <td style={{ ...styles.td, textAlign: "right", color: "var(--muted, #6B7280)" }}>—</td>
              <td style={{ ...styles.td, textAlign: "right", color: "var(--muted, #6B7280)" }}>—</td>
              <td style={{ ...styles.td, textAlign: "right" }}>
                <button style={{ ...styles.refreshBtn, opacity: 0.5 }} disabled>Refresh</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────

function fmtTime(ts) {
  if (!ts) return "—";
  try {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return String(ts);
    const now = Date.now();
    const delta = now - d.getTime();
    if (delta < 60_000) return "just now";
    if (delta < 3_600_000) return `${Math.floor(delta / 60_000)}m ago`;
    if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)}h ago`;
    return d.toISOString().slice(0, 16).replace("T", " ") + " UTC";
  } catch {
    return String(ts);
  }
}
function fmtNum(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return Number(v).toLocaleString();
}

// ─────────────────────────────────────────────────────────────
// Styles — light-gold palette.
// ─────────────────────────────────────────────────────────────
const styles = {
  root: {
    position: "fixed", inset: 0, zIndex: 50,
    display: "flex", flexDirection: "column",
    background: "var(--bg, #F2F3F5)",
    color: INK,
    fontFamily: "var(--font-sans, 'DM Sans'), -apple-system, sans-serif",
    overflow: "hidden",
  },
  header: {
    display: "flex", alignItems: "center", gap: 16,
    padding: "14px 24px",
    borderBottom: "1px solid var(--cds-border-subtle, #E8EAED)",
    background: "#fff", flexShrink: 0,
  },
  backBtn: {
    background: "transparent", border: `1px solid ${GOLD}`, color: INK,
    padding: "6px 12px", borderRadius: 6, cursor: "pointer",
    fontSize: 13, fontWeight: 500, fontFamily: "inherit",
  },
  title: { fontSize: 18, fontWeight: 700, color: INK, lineHeight: 1.2 },
  subtitle: { fontSize: 12, color: "var(--muted, #6B7280)", marginTop: 2 },
  headerRight: { marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" },
  loadingPill: {
    fontSize: 11, fontWeight: 600, color: INK,
    background: LIGHT_GOLD, padding: "4px 10px", borderRadius: 999,
    border: `1px solid ${GOLD}`,
  },
  warnPill: {
    fontSize: 11, fontWeight: 600, color: "#92400E",
    background: "#FEF3C7", padding: "4px 10px", borderRadius: 999,
    border: "1px solid #F59E0B",
  },
  primaryBtn: {
    background: GOLD, color: INK, border: `1px solid ${GOLD}`,
    padding: "7px 14px", borderRadius: 6, cursor: "pointer",
    fontSize: 13, fontWeight: 600, fontFamily: "inherit",
  },

  body: { flex: 1, padding: 24, overflow: "auto" },

  tableWrap: {
    background: "#fff", borderRadius: 8,
    border: "1px solid var(--cds-border-subtle, #E8EAED)", overflow: "hidden",
  },
  table: { width: "100%", borderCollapse: "collapse" },
  th: {
    textAlign: "left", padding: "10px 14px",
    fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5,
    color: "var(--muted, #6B7280)", fontWeight: 600,
    background: LIGHT_GOLD,
    borderBottom: `2px solid ${GOLD}`,
  },
  sortIndicator: { color: GOLD, fontSize: 10, marginLeft: 4 },

  tr: { borderBottom: "1px solid #F3F4F6" },
  td: { padding: "10px 14px", fontSize: 13, color: INK, verticalAlign: "middle" },
  rowToggle: {
    background: "transparent", border: "none", cursor: "pointer",
    color: GOLD, fontSize: 12, marginRight: 6, padding: 0, fontFamily: "inherit",
  },
  connectorName: { fontWeight: 600, color: INK },
  connectorSource: { fontSize: 11, color: "var(--muted, #6B7280)" },
  refreshBtn: {
    background: "#fff", color: INK, border: `1px solid ${GOLD}`,
    padding: "5px 12px", borderRadius: 6, cursor: "pointer",
    fontSize: 12, fontWeight: 500, fontFamily: "inherit",
  },

  detailRow: { background: LIGHT_GOLD, padding: 0 },
  detailBox: { padding: "12px 20px 16px 40px" },
  detailTitle: {
    fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.8,
    color: INK, marginBottom: 8,
  },
  detailRowKV: { display: "flex", gap: 12, fontSize: 12, padding: "3px 0" },
  detailKey: { color: "var(--muted, #6B7280)", minWidth: 160 },
  detailVal: { color: INK, fontFamily: "var(--mono, monospace)" },

  emptyState: {
    fontSize: 13, color: "var(--muted, #6B7280)",
    padding: 40, textAlign: "center",
    background: "#fff", borderRadius: 8,
    border: "1px dashed var(--cds-border-subtle, #E8EAED)",
  },

  errorBar: {
    marginTop: 12,
    background: "#FEE2E2", border: "1px solid #FCA5A5", color: "#991B1B",
    padding: "8px 12px", borderRadius: 6, fontSize: 12,
  },

  skeletonWrap: {
    background: "#fff", borderRadius: 8,
    border: "1px solid var(--cds-border-subtle, #E8EAED)", overflow: "hidden",
  },
  skeletonNotice: {
    padding: 20, borderBottom: `2px solid ${GOLD}`,
    background: LIGHT_GOLD,
  },
  feedOfflineTitle: { fontSize: 15, fontWeight: 700, color: INK, marginBottom: 6 },
  feedOfflineBody:  { fontSize: 13, color: "var(--muted, #4B5563)", lineHeight: 1.55, marginBottom: 8 },
  feedOfflineHint:  { fontSize: 11, color: INK },

  mono: { fontFamily: "var(--mono, 'JetBrains Mono', monospace)", fontSize: "0.92em" },
};
