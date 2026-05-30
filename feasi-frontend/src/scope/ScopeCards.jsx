import React, { useState } from "react";

/**
 * Presentational sub-cards for /v2/scope. Pure render only — no fetching,
 * no map, no state coupling beyond a single local open/close on the draft
 * application accordion. Kept in a sibling file so ScopePage.jsx stays
 * under the 500-line ceiling.
 */

const fmtMoney = (v) =>
  v == null
    ? "—"
    : `£${(v / 1_000_000).toLocaleString("en-GB", {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      })}M`;

const ragColor = (rag) =>
  rag === "green" ? "#16A34A" : rag === "amber" ? "#E8A012" : "#DC2626";

export function VerdictPill({ verdict }) {
  if (!verdict?.label) return null;
  const color =
    verdict.label === "GO"
      ? "#16A34A"
      : verdict.label === "NO-GO"
      ? "#DC2626"
      : "#E8A012";
  return (
    <div className="scope-verdict">
      <span className="scope-verdict-pill" style={{ background: color }}>
        {verdict.label}
      </span>
      <div className="scope-verdict-body">
        <div className="scope-verdict-confidence">
          confidence {Math.round((verdict.confidence || 0) * 100)}%
        </div>
        <div className="scope-verdict-rationale">{verdict.rationale}</div>
      </div>
    </div>
  );
}

export function SubstationRow({ s }) {
  return (
    <div className="scope-sub-row">
      <div className="scope-sub-name">
        <span
          className="scope-rag-dot"
          style={{ background: ragColor(s.rag) }}
        />
        {s.name}
      </div>
      <div className="scope-sub-meta">
        <span>{s.distance_km} km</span>
        <span>{s.voltage_kv} kV</span>
        <span className="scope-sub-headroom">
          {s.firm_headroom_mw} MW firm
        </span>
        <span className="scope-sub-dno">{s.dno}</span>
      </div>
    </div>
  );
}

export function CostBars({ costs }) {
  if (!costs) return null;
  const max = Math.max(costs.p10, costs.p50, costs.p90);
  const cols = [
    { label: "P10", value: costs.p10, color: "#16A34A" },
    { label: "P50", value: costs.p50, color: "#F5B731" },
    { label: "P90", value: costs.p90, color: "#DC2626" },
  ];
  return (
    <div className="scope-cost-row">
      {cols.map((c) => (
        <div key={c.label} className="scope-cost-col">
          <div className="scope-cost-bar-wrap">
            <div
              className="scope-cost-bar"
              style={{
                height: `${Math.round((c.value / max) * 100)}%`,
                background: c.color,
              }}
            />
          </div>
          <div className="scope-cost-label">{c.label}</div>
          <div className="scope-cost-value">{fmtMoney(c.value)}</div>
        </div>
      ))}
    </div>
  );
}

export function PlanningCard({ planning }) {
  if (!planning) return null;
  const score = planning.risk_score_0_100;
  const color = score < 35 ? "#16A34A" : score < 65 ? "#E8A012" : "#DC2626";
  return (
    <div className="scope-planning">
      <div className="scope-planning-head">
        <div>
          <div className="scope-planning-lpa">{planning.lpa}</div>
          <div className="scope-planning-meta">
            {planning.recent_decisions_count} recent decisions ·{" "}
            {planning.approval_rate_pct}% approved
          </div>
        </div>
        <div className="scope-planning-score" style={{ color }}>
          {score}
          <span>/100</span>
        </div>
      </div>
      <div className="scope-planning-bar">
        <div
          className="scope-planning-bar-fill"
          style={{ width: `${score}%`, background: color }}
        />
      </div>
    </div>
  );
}

export function DraftApplication({ draft }) {
  const [open, setOpen] = useState(false);
  if (!draft) return null;
  const rows = [
    ["Gate", draft.gate],
    ["Applicant", draft.applicant],
    ["Site address", draft.site_address],
    ["Technology", draft.technology],
    ["Requested capacity", `${draft.requested_mw} MW`],
    ["Connection voltage", `${draft.connection_voltage_kv} kV`],
    ["Preferred substation", draft.preferred_substation],
    ["DNO", draft.dno],
    ["Estimated energisation", draft.estimated_energisation],
  ];
  return (
    <div className="scope-draft">
      <button
        className="scope-draft-head"
        onClick={() => setOpen((v) => !v)}
        type="button"
      >
        <div>
          <div className="scope-draft-eyebrow">PRE-FILLED</div>
          <div className="scope-draft-title">
            Draft {draft.gate} connection application
          </div>
        </div>
        <span className="scope-draft-caret">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="scope-draft-body">
          <div className="scope-draft-fields">
            {rows.map(([k, v]) => (
              <div key={k} className="scope-draft-row">
                <span className="scope-draft-k">{k}</span>
                <span className="scope-draft-v">{v ?? "—"}</span>
              </div>
            ))}
          </div>
          <div className="scope-draft-evidence">
            <div className="scope-draft-evidence-h">Supporting evidence</div>
            {draft.supporting_evidence?.map((e) => (
              <div key={e.ref} className="scope-evidence-row">
                <span className="scope-evidence-dot" />
                <span className="scope-evidence-label">{e.label}</span>
                <span className="scope-evidence-ref">{e.ref}</span>
              </div>
            ))}
          </div>
          <div className="scope-draft-actions">
            <button className="scope-btn-ghost" type="button">
              Edit
            </button>
            <button className="scope-btn-primary" type="button">
              Submit to DNO portal
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function StepsList({ steps, completedCount }) {
  if (!steps?.length) return null;
  return (
    <div className="scope-steps">
      {steps.map((s, i) => {
        const done = i < completedCount;
        const active = i === completedCount;
        return (
          <div
            key={i}
            className={`scope-step ${done ? "is-done" : ""} ${
              active ? "is-active" : ""
            }`}
          >
            <span className="scope-step-num">{i + 1}</span>
            <div className="scope-step-body">
              <div className="scope-step-label">{s.label}</div>
              {done && s.detail && (
                <div className="scope-step-detail">{s.detail}</div>
              )}
              {active && !done && (
                <div className="scope-step-pulse">
                  <span /> <span /> <span />
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
