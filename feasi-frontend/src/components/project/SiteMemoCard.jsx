import React from "react";
import { useSiteMemo } from "../../hooks/useSiteMemo.js";

const GOLD = "#F5B731";
const IVORY = "#FBF8F2";
const INK = "#0F1318";
const GREEN = "#3B8A5A";
const AMBER = "#E89A2A";
const RED = "#B84A4A";

const VERDICT_COLOUR = { GO: GREEN, CAUTION: AMBER, "NO-GO": RED };

export default function SiteMemoCard({ projectId }) {
  const { latest, past, loading, generating, progress, generate } = useSiteMemo(projectId);
  const [expanded, setExpanded] = React.useState(false);
  const [pdfBusy, setPdfBusy] = React.useState(false);

  // Build a sensible PDF URL: prefer the URL the backend stamped on the
  // memo when it rendered; otherwise hit the live download endpoint.
  const pdfHref = latest?.pdf_url
    || (latest?.memo_id && projectId
        ? `/api/project/${encodeURIComponent(projectId)}/site-memo/pdf?memo_id=${encodeURIComponent(latest.memo_id)}`
        : null);

  const downloadPdf = async () => {
    if (!pdfHref) return;
    setPdfBusy(true);
    try {
      // window.open keeps the tab interactive; if the backend returns
      // a non-pdf (e.g., 404 JSON), the new tab shows the error inline.
      window.open(pdfHref, "_blank", "noopener,noreferrer");
    } finally {
      setPdfBusy(false);
    }
  };

  return (
    <section style={card}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <div style={eyebrow}>AI Site Memo</div>
          <h3 style={{ margin: "4px 0 0", fontSize: 16, fontWeight: 700 }}>
            Investment-grade one-pager
          </h3>
        </div>
        <button onClick={generate} disabled={generating}
          style={{
            padding: "8px 14px", background: generating ? "#E5CFA0" : GOLD,
            color: INK, fontWeight: 700, fontSize: 12, border: "none",
            borderRadius: 6, cursor: generating ? "wait" : "pointer",
            fontFamily: "inherit",
          }}>
          {generating ? "Generating…" : (latest ? "Regenerate memo" : "Generate AI Site Memo")}
        </button>
      </header>

      {generating && progress && (
        <div style={{ marginBottom: 12, padding: 12, background: "rgba(245,183,49,0.08)",
          border: `1px solid ${GOLD}44`, borderRadius: 6, fontSize: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
            <span>{progress.step}</span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", color: "#6B7280" }}>
              {progress.index + 1}/{progress.total}
            </span>
          </div>
          <div style={{ height: 3, background: "rgba(15,19,24,0.08)", borderRadius: 2, overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${((progress.index + 1) / progress.total) * 100}%`,
              background: GOLD, transition: "width 300ms ease" }} />
          </div>
        </div>
      )}

      {loading && <div style={{ color: "#6B7280", fontSize: 13 }}>Loading memo history…</div>}

      {!loading && !latest && !generating && (
        <div style={{ padding: 20, textAlign: "center", color: "#6B7280",
          border: "1px dashed rgba(15,19,24,0.15)", borderRadius: 6 }}>
          No memo yet. Click <strong>Generate AI Site Memo</strong> to produce an investment-grade one-pager.
        </div>
      )}

      {latest && (
        <article style={latestCard}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <Verdict v={latest.investment_verdict} />
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: "#6B7280" }}>
              v{latest.version} · {fmtTs(latest.generated_at)}
            </span>
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.45, marginBottom: 10 }}>
            {latest.one_liner}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginBottom: 10 }}>
            <Headline label="NPV" v={`£${latest.financial_headline?.npv_gbp_m?.toFixed(1) || "—"}m`} />
            <Headline label="IRR" v={`${latest.financial_headline?.irr_pct?.toFixed(1) || "—"}%`} />
            <Headline label="DSCR" v={latest.financial_headline?.dscr?.toFixed(2) || "—"} />
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button
              style={ghostBtn}
              onClick={() => setExpanded((e) => !e)}
            >
              {expanded ? "Hide full memo" : "Open full memo"}
            </button>
            <button
              style={{ ...ghostBtn, opacity: pdfHref ? 1 : 0.5, cursor: pdfHref ? "pointer" : "not-allowed" }}
              onClick={downloadPdf}
              disabled={!pdfHref || pdfBusy}
            >
              {pdfBusy ? "Opening…" : "Download PDF ↗"}
            </button>
          </div>

          {expanded && (
            <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid rgba(15,19,24,0.08)" }}>
              <MemoSection title="Key strengths" items={latest.key_strengths} />
              <MemoSection title="Critical risks" items={latest.critical_risks} accent={RED} />
              <MemoSection title="Next milestones" items={latest.next_milestones} accent={GREEN} />

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginTop: 12 }}>
                <Pillar title="Financial">
                  <Row k="NPV" v={`£${latest.financial_headline?.npv_gbp_m?.toFixed(1) ?? "—"}m`} />
                  <Row k="IRR" v={`${latest.financial_headline?.irr_pct?.toFixed(1) ?? "—"}%`} />
                  <Row k="DSCR" v={latest.financial_headline?.dscr?.toFixed(2) ?? "—"} />
                </Pillar>
                <Pillar title="Grid">
                  <Row k="POC" v={latest.grid_headline?.poc ?? "—"} />
                  <Row k="Firm" v={`${latest.grid_headline?.firm_mw ?? "—"} MW`} />
                  <Row k="Timeline" v={`${latest.grid_headline?.timeline_months ?? "—"} mo`} />
                </Pillar>
                <Pillar title="Planning">
                  <Row k="Approval" v={`${latest.planning_headline?.approval_pct ?? "—"}%`} />
                  <Row k="LPA" v={latest.planning_headline?.lpa ?? "—"} />
                  <Row k="Precedents" v={latest.planning_headline?.precedent_count ?? "—"} />
                </Pillar>
              </div>

              {(latest.regulatory_flags || []).length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={eyebrow}>Regulatory flags</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                    {latest.regulatory_flags.map((f, i) => (
                      <span key={i} style={{
                        fontSize: 11, padding: "3px 8px", borderRadius: 3,
                        background: AMBER + "22", color: AMBER, fontWeight: 600,
                      }}>{typeof f === "string" ? f : f?.label || f?.code}</span>
                    ))}
                  </div>
                </div>
              )}

              {(latest.source_evidence || []).length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={eyebrow}>Source evidence</div>
                  <ul style={{ margin: "6px 0 0", padding: "0 0 0 18px", fontSize: 11, color: "#374151" }}>
                    {latest.source_evidence.slice(0, 8).map((s, i) => (
                      <li key={i} style={{ marginBottom: 3 }}>
                        {s?.url ? (
                          <a href={s.url} target="_blank" rel="noopener noreferrer" style={{ color: INK }}>
                            {s.title || s.label || s.url}
                          </a>
                        ) : (
                          s?.title || s?.label || JSON.stringify(s).slice(0, 80)
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </article>
      )}

      {(past || []).length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={eyebrow}>Past memos</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }}>
            {past.slice(0, 3).map(m => (
              <div key={m.memo_id} style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "6px 10px", fontSize: 12,
                border: "1px solid rgba(15,19,24,0.08)", borderRadius: 4,
              }}>
                <Verdict v={m.investment_verdict} compact />
                <span style={{ fontFamily: "'JetBrains Mono', monospace", color: "#6B7280" }}>
                  v{m.version} · {fmtTs(m.generated_at)}
                </span>
                <span style={{ flex: 1, color: "#0F1318" }}>{m.one_liner}</span>
                <button style={{ ...ghostBtn, padding: "4px 8px", fontSize: 11 }}>PDF ↗</button>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function Verdict({ v, compact }) {
  const c = VERDICT_COLOUR[v] || "#6B7280";
  return (
    <span style={{
      padding: compact ? "2px 6px" : "3px 10px",
      fontSize: compact ? 10 : 11, fontWeight: 700,
      borderRadius: 4, background: c + "22", color: c,
      fontFamily: "'JetBrains Mono', monospace",
    }}>{v}</span>
  );
}
function Headline({ label, v }) {
  return (
    <div style={{ padding: "8px 10px", background: "rgba(15,19,24,0.03)", borderRadius: 4 }}>
      <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.06em", color: "#6B7280", fontWeight: 700 }}>{label}</div>
      <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 15, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{v}</div>
    </div>
  );
}
function MemoSection({ title, items, accent }) {
  if (!items || items.length === 0) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <div style={eyebrow}>{title}</div>
      <ul style={{ margin: "6px 0 0", padding: "0 0 0 18px", fontSize: 13, lineHeight: 1.5, color: "#1F2937" }}>
        {items.map((s, i) => (
          <li key={i} style={{
            marginBottom: 4,
            ...(accent ? { borderLeft: `2px solid ${accent}33`, paddingLeft: 6, marginLeft: -6 } : {}),
          }}>{s}</li>
        ))}
      </ul>
    </div>
  );
}
function Pillar({ title, children }) {
  return (
    <div style={{ padding: 10, background: "rgba(15,19,24,0.03)", borderRadius: 4 }}>
      <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.06em",
        textTransform: "uppercase", color: "#6B7280", marginBottom: 6 }}>{title}</div>
      {children}
    </div>
  );
}
function Row({ k, v }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 3 }}>
      <span style={{ color: "#6B7280" }}>{k}</span>
      <span style={{ fontWeight: 600, fontFamily: "'JetBrains Mono', monospace", textAlign: "right" }}>{v}</span>
    </div>
  );
}
function fmtTs(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

const card = {
  padding: 16,
  background: IVORY,
  border: "1px solid rgba(15,19,24,0.08)",
  borderRadius: 8,
  fontFamily: "'DM Sans', sans-serif",
  color: INK,
};
const latestCard = {
  padding: 14,
  background: "white",
  border: "1px solid rgba(15,19,24,0.08)",
  borderRadius: 6,
};
const eyebrow = {
  fontSize: 10, fontWeight: 700, letterSpacing: "0.06em",
  textTransform: "uppercase", color: "#6B7280",
};
const ghostBtn = {
  padding: "6px 10px", fontSize: 11, fontWeight: 600,
  background: "transparent", border: "1px solid rgba(15,19,24,0.2)",
  color: INK, borderRadius: 4, cursor: "pointer", fontFamily: "inherit",
};
