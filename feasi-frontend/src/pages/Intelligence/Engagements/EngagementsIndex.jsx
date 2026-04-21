import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

/**
 * EngagementsIndex — Intelligence sub-tab at /intelligence/engagements.
 *
 * Council-approved spec (Task #20):
 *  - Filters: All / My team / Sent to DNO / Awaiting response
 *  - Columns: project | dno | status | days_since_sent | ΔIRR vs pre-pack | pack_version
 *  - CSV export
 *
 * Source of truth:
 *  - GET /api/intelligence/engagements?status=&team=
 *  - GET /api/v1/projects            (for project name / IRR lookup)
 *
 * This page is read-only on its own — write paths (send + ingest)
 * happen through the workspace modals (SendEngagementModal /
 * IngestResponseModal).
 */

const C = {
  ivory: "#FBF8F2",
  bg: "#F7F8FA",
  border: "#E8EAED",
  gold: "#F5B731",
  goldSoft: "#C9A64B",
  goldSurface: "rgba(245,183,49,0.10)",
  goldBorder: "rgba(245,183,49,0.32)",
  ink: "#0F1318",
  secondary: "#4B5563",
  tertiary: "#9C9590",
  go: "#2F7C46",
  caution: "#C07A1A",
  nogo: "#B23B3B",
  awaiting: "#1E5DA8",
};

const FILTERS = [
  { id: "all",        label: "All",               query: {} },
  { id: "my_team",    label: "My team",           query: { team: "self" } },
  { id: "sent",       label: "Sent to DNO",       query: { status: "sent,responded" } },
  { id: "awaiting",   label: "Awaiting response", query: { status: "sent" } },
];

function StatusChip({ status }) {
  const map = {
    drafting:    { bg: C.bg,          fg: C.secondary, label: "Drafting" },
    previewing:  { bg: C.goldSurface, fg: C.ink,       label: "Previewing" },
    sent:        { bg: "#E8EFF9",     fg: C.awaiting,  label: "Sent" },
    responded:   { bg: "#E7F4EB",     fg: C.go,        label: "Responded" },
    withdrawn:   { bg: "#F3F4F6",     fg: C.tertiary,  label: "Withdrawn" },
    superseded:  { bg: "#F3F4F6",     fg: C.tertiary,  label: "Superseded" },
  };
  const s = map[status] || { bg: C.bg, fg: C.secondary, label: status || "—" };
  return (
    <span style={{
      display: "inline-block",
      padding: "2px 8px",
      borderRadius: 6,
      fontSize: 11,
      fontWeight: 600,
      background: s.bg,
      color: s.fg,
      letterSpacing: "-0.005em",
      whiteSpace: "nowrap",
    }}>
      {s.label}
    </span>
  );
}

function daysSince(iso) {
  if (!iso) return null;
  try {
    const ms = Date.now() - new Date(iso).getTime();
    return Math.max(0, Math.round(ms / 86400000));
  } catch {
    return null;
  }
}

function toCsv(rows) {
  const head = ["project_id","project_name","dno_slug","pack_version","status","sent_at","days_since_sent","delta_irr_pct","recipient_email"];
  const esc = (v) => {
    if (v === null || v === undefined) return "";
    const s = String(v);
    return /[,"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const body = rows.map((r) => head.map((h) => esc(r[h])).join(","));
  return [head.join(","), ...body].join("\n");
}

export default function EngagementsIndex() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState("all");
  const [engagements, setEngagements] = useState([]);
  const [projects, setProjects] = useState({});  // id -> {name, irr_pct, irr_pct_pre_pack}
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const q = FILTERS.find((f) => f.id === filter)?.query || {};
      const params = new URLSearchParams();
      if (q.status) params.set("status", q.status);
      if (q.team && q.team !== "self") params.set("team", q.team);
      const url = "/api/intelligence/engagements" + (params.toString() ? "?" + params : "");
      const r = await fetch(url);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setEngagements(Array.isArray(data.engagements) ? data.engagements : []);

      // Best-effort project-name + IRR join. /api/v1/projects returns an
      // array or {projects: [...]}.
      try {
        const pr = await fetch("/api/v1/projects");
        if (pr.ok) {
          const pd = await pr.json();
          const arr = Array.isArray(pd) ? pd : (pd.projects || []);
          const byId = {};
          arr.forEach((p) => {
            const pid = String(p.project_id || p.id);
            byId[pid] = {
              name: p.name || p.project_name || "(untitled)",
              irr_pct: p.irr_pct ?? p.irr ?? null,
              irr_pct_pre_pack: p.irr_pct_pre_pack ?? null,
            };
          });
          setProjects(byId);
        }
      } catch {
        // Non-fatal — table just shows raw project UUIDs.
      }
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  const rows = useMemo(() => engagements.map((e) => {
    const proj = projects[String(e.project_id)] || {};
    const dsinceRaw = daysSince(e.sent_at);
    const irrNow = proj.irr_pct;
    const irrPre = proj.irr_pct_pre_pack;
    const deltaIrr = (irrNow != null && irrPre != null) ? (Number(irrNow) - Number(irrPre)) : null;
    return {
      id: e.id,
      project_id: e.project_id,
      project_name: proj.name || e.project_id,
      dno_slug: e.dno_slug,
      pack_version: e.pack_version,
      status: e.status,
      sent_at: e.sent_at,
      days_since_sent: dsinceRaw,
      delta_irr_pct: deltaIrr,
      recipient_email: e.recipient_email,
      latest_response: e.latest_response,
    };
  }), [engagements, projects]);

  const onExportCsv = useCallback(() => {
    const csv = toCsv(rows);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const stamp = new Date().toISOString().slice(0, 10);
    a.download = `princeps-engagements-${stamp}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [rows]);

  return (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        display: "flex",
        flexDirection: "column",
        background: C.ivory,
        color: C.ink,
        fontFamily: "'DM Sans', sans-serif",
      }}
    >
      {/* Toolbar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "16px 24px 12px",
          borderBottom: `1px solid ${C.border}`,
          background: "#FFFFFF",
          gap: 16,
        }}
      >
        <div role="tablist" style={{ display: "inline-flex", gap: 2, padding: 4, borderRadius: 10, background: C.bg, border: `1px solid ${C.border}` }}>
          {FILTERS.map((f) => {
            const active = filter === f.id;
            return (
              <button
                key={f.id}
                role="tab"
                aria-selected={active}
                onClick={() => setFilter(f.id)}
                style={{
                  padding: "6px 14px",
                  borderRadius: 8,
                  fontSize: 13,
                  fontWeight: active ? 700 : 600,
                  color: active ? C.ink : C.secondary,
                  background: active ? "#FFFFFF" : "transparent",
                  border: active ? `1px solid ${C.goldBorder}` : "1px solid transparent",
                  boxShadow: active ? "0 1px 2px rgba(15,19,24,0.05)" : "none",
                  cursor: "pointer",
                  fontFamily: "inherit",
                }}
              >
                {f.label}
              </button>
            );
          })}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 12, color: C.tertiary }}>
            {rows.length} engagement{rows.length === 1 ? "" : "s"}
          </span>
          <button
            onClick={onExportCsv}
            disabled={rows.length === 0}
            style={{
              padding: "6px 12px",
              fontSize: 12,
              fontWeight: 600,
              border: `1px solid ${C.border}`,
              borderRadius: 6,
              background: rows.length === 0 ? C.bg : "#FFFFFF",
              color: rows.length === 0 ? C.tertiary : C.ink,
              cursor: rows.length === 0 ? "default" : "pointer",
              fontFamily: "inherit",
            }}
          >
            Export CSV
          </button>
        </div>
      </div>

      {/* Body */}
      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "0 24px 24px" }}>
        {loading && (
          <div style={{ padding: 40, color: C.tertiary, fontSize: 13 }}>Loading engagements…</div>
        )}
        {!loading && err && (
          <div style={{ padding: 40, color: C.nogo, fontSize: 13 }}>Error: {err}</div>
        )}
        {!loading && !err && rows.length === 0 && (
          <div style={{ padding: 40, color: C.tertiary, fontSize: 13 }}>
            No engagements match the current filter.
          </div>
        )}
        {!loading && !err && rows.length > 0 && (
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: 13,
              marginTop: 16,
              background: "#FFFFFF",
              border: `1px solid ${C.border}`,
              borderRadius: 8,
              overflow: "hidden",
            }}
          >
            <thead>
              <tr style={{ background: C.bg, textAlign: "left" }}>
                <th style={th}>Project</th>
                <th style={th}>DNO</th>
                <th style={th}>Status</th>
                <th style={{ ...th, textAlign: "right" }}>Days since sent</th>
                <th style={{ ...th, textAlign: "right" }}>ΔIRR vs pre-pack</th>
                <th style={{ ...th, textAlign: "right" }}>Pack version</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.id}
                  onClick={() => navigate(`/projects/${r.project_id}`)}
                  style={{ cursor: "pointer", borderTop: `1px solid ${C.border}` }}
                  onMouseEnter={(ev) => { ev.currentTarget.style.background = C.goldSurface; }}
                  onMouseLeave={(ev) => { ev.currentTarget.style.background = "transparent"; }}
                >
                  <td style={td}>
                    <div style={{ fontWeight: 600 }}>{r.project_name}</div>
                    <div style={{ fontSize: 10, color: C.tertiary, fontFamily: "'JetBrains Mono', monospace" }}>
                      {r.project_id}
                    </div>
                  </td>
                  <td style={td}>{r.dno_slug}</td>
                  <td style={td}><StatusChip status={r.status} /></td>
                  <td style={{ ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                    {r.days_since_sent != null ? r.days_since_sent : "—"}
                  </td>
                  <td style={{ ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                    {r.delta_irr_pct != null ? (
                      <span style={{ color: r.delta_irr_pct >= 0 ? C.go : C.nogo, fontWeight: 600 }}>
                        {r.delta_irr_pct > 0 ? "+" : ""}{r.delta_irr_pct.toFixed(2)}%
                      </span>
                    ) : "—"}
                  </td>
                  <td style={{ ...td, textAlign: "right", fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>
                    v{r.pack_version}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

const th = {
  padding: "10px 12px",
  fontSize: 11,
  fontWeight: 700,
  color: C.secondary,
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  borderBottom: `1px solid ${C.border}`,
  whiteSpace: "nowrap",
};

const td = {
  padding: "12px",
  verticalAlign: "middle",
  color: C.ink,
};
