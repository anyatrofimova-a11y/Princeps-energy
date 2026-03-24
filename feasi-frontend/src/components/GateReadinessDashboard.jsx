import React, { useState, useEffect, useCallback, useRef, useMemo } from "react";

/* ── NESO Connections Reform: 5-Gate Queue System ──────────────────────── */

const GATES = [
  {
    id: 1,
    label: "Pre-Application",
    shortLabel: "Pre-App",
    description: "Site selection, feasibility, land rights, pre-app meeting with DNO/TO",
    requirements: [
      { id: "land_rights", label: "Land rights secured (option/lease)", category: "legal", fixAction: "site_prospecting" },
      { id: "grid_feasibility", label: "Grid feasibility study complete", category: "grid", fixAction: "grid_study" },
      { id: "env_screening", label: "Environmental screening complete", category: "environmental", fixAction: "environmental" },
      { id: "planning_pre_app", label: "Planning pre-application submitted", category: "planning", fixAction: "planning" },
      { id: "dno_pre_app", label: "DNO/TO pre-application meeting held", category: "grid", fixAction: "grid_connection" },
      { id: "community_engagement", label: "Community engagement plan drafted", category: "planning", fixAction: "planning" },
    ],
    typicalCostGbp: 50000,
    typicalWeeks: 26,
  },
  {
    id: 2,
    label: "Application",
    shortLabel: "Apply",
    description: "Formal connection application, planning submission, grid studies commissioned",
    requirements: [
      { id: "conn_application", label: "Connection application submitted", category: "grid", fixAction: "grid_connection" },
      { id: "planning_submitted", label: "Planning application submitted", category: "planning", fixAction: "planning" },
      { id: "eia_complete", label: "EIA / Environmental Statement complete", category: "environmental", fixAction: "environmental" },
      { id: "power_flow", label: "Power flow study completed (N-1)", category: "grid", fixAction: "grid_study" },
      { id: "financial_model", label: "Financial model with grid costs", category: "financial", fixAction: "financial" },
      { id: "design_frozen", label: "System design frozen", category: "technical", fixAction: "feasibility" },
      { id: "securities_posted", label: "Application securities posted", category: "financial", fixAction: "financial" },
    ],
    typicalCostGbp: 250000,
    typicalWeeks: 52,
  },
  {
    id: 3,
    label: "Offer",
    shortLabel: "Offer",
    description: "Connection offer received, commercial terms negotiated, planning consent secured",
    requirements: [
      { id: "conn_offer_received", label: "Connection offer received from DNO/TO", category: "grid", fixAction: "grid_connection" },
      { id: "planning_consent", label: "Planning consent granted", category: "planning", fixAction: "planning" },
      { id: "conn_terms_reviewed", label: "Connection terms commercially viable", category: "financial", fixAction: "financial" },
      { id: "reinforcement_scope", label: "Reinforcement scope confirmed", category: "grid", fixAction: "grid_study" },
      { id: "ppa_heads", label: "PPA heads of terms agreed", category: "financial", fixAction: "financial" },
    ],
    typicalCostGbp: 150000,
    typicalWeeks: 39,
  },
  {
    id: 4,
    label: "Acceptance",
    shortLabel: "Accept",
    description: "Connection agreement signed, construction programme, milestones agreed",
    requirements: [
      { id: "conn_agreement", label: "Connection agreement executed", category: "grid", fixAction: "grid_connection" },
      { id: "construction_programme", label: "Construction programme agreed", category: "technical", fixAction: "feasibility" },
      { id: "epc_contract", label: "EPC contract awarded", category: "financial", fixAction: "financial" },
      { id: "grid_securities", label: "Grid securities/bonds posted", category: "financial", fixAction: "financial" },
      { id: "pre_construction", label: "Pre-construction conditions discharged", category: "planning", fixAction: "planning" },
    ],
    typicalCostGbp: 500000,
    typicalWeeks: 26,
  },
  {
    id: 5,
    label: "Energisation",
    shortLabel: "Energise",
    description: "Commissioning, G99 compliance, energisation date confirmed",
    requirements: [
      { id: "construction_complete", label: "Construction substantially complete", category: "technical", fixAction: "feasibility" },
      { id: "g99_compliance", label: "G99 type test certificates obtained", category: "grid", fixAction: "grid_connection" },
      { id: "sat_complete", label: "Site acceptance tests passed", category: "technical", fixAction: "feasibility" },
      { id: "energisation_date", label: "Energisation date confirmed by DNO", category: "grid", fixAction: "grid_connection" },
      { id: "ofgem_registration", label: "Ofgem generation licence / exemption", category: "legal", fixAction: "planning" },
    ],
    typicalCostGbp: 200000,
    typicalWeeks: 13,
  },
];

/* ── H2 2026 Window ────────────────────────────────────────────────────── */
const H2_2026_OPEN = new Date("2026-07-01T00:00:00Z");

function daysUntilWindow() {
  const now = new Date();
  const diff = H2_2026_OPEN.getTime() - now.getTime();
  return Math.max(0, Math.ceil(diff / (1000 * 60 * 60 * 24)));
}

/* ── Formatting helpers ────────────────────────────────────────────────── */
function fmtGbp(val) {
  if (val == null) return "--";
  if (val >= 1_000_000) return `\u00A3${(val / 1_000_000).toFixed(1)}M`;
  if (val >= 1000) return `\u00A3${(val / 1000).toFixed(0)}k`;
  return `\u00A3${val.toFixed(0)}`;
}

function fmtWeeks(w) {
  if (w == null) return "--";
  if (w >= 52) return `${(w / 52).toFixed(1)} yr`;
  return `${w} wk`;
}

/* ── Colour tokens (Princeps brand, light theme) ──────────────────────── */
const C = {
  bg: "#F8F9FA",
  card: "#FFFFFF",
  border: "#E8EAED",
  borderFocus: "#DADCE0",
  text: "#202124",
  textSecondary: "#5F6368",
  textTertiary: "#80868B",
  gold: "#F5B731",
  goldDark: "#E8A012",
  goldLight: "#FEF7E0",
  green: "#137333",
  greenBg: "#E6F4EA",
  red: "#C5221F",
  redBg: "#FCE8E6",
  amber: "#E37400",
  amberBg: "#FEF7E0",
  blue: "#1A73E8",
  blueBg: "#E8F0FE",
  mono: "'JetBrains Mono', 'SF Mono', 'Fira Code', monospace",
  sans: "'DM Sans', 'Inter', -apple-system, sans-serif",
};

/* ── Shared style fragments ────────────────────────────────────────────── */
const s = {
  card: {
    background: C.card,
    border: `1px solid ${C.border}`,
    borderRadius: 14,
    overflow: "hidden",
  },
  sectionTitle: {
    fontFamily: C.sans,
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: "0.8px",
    textTransform: "uppercase",
    color: C.textSecondary,
    margin: 0,
  },
  mono: {
    fontFamily: C.mono,
    fontFeatureSettings: "'tnum'",
  },
};

/* ── Status helpers ────────────────────────────────────────────────────── */
function statusColor(status) {
  if (status === "ready") return { fg: C.green, bg: C.greenBg };
  if (status === "blocked") return { fg: C.red, bg: C.redBg };
  return { fg: C.amber, bg: C.amberBg };
}

function statusLabel(status) {
  if (status === "ready") return "Ready";
  if (status === "blocked") return "Blocked";
  return "Pending";
}

function gateOverallStatus(reqStatuses) {
  if (!reqStatuses || reqStatuses.length === 0) return "pending";
  if (reqStatuses.every((r) => r === "ready")) return "ready";
  if (reqStatuses.some((r) => r === "blocked")) return "blocked";
  return "pending";
}

/* ── SVG icons (no emoji) ──────────────────────────────────────────────── */
function CheckIcon({ size = 14, color = C.green }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <path d="M3 8.5L6.5 12L13 4" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function BlockIcon({ size = 14, color = C.red }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="5.5" stroke={color} strokeWidth="1.5" />
      <line x1="4.5" y1="8" x2="11.5" y2="8" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function ClockIcon({ size = 14, color = C.amber }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="5.5" stroke={color} strokeWidth="1.5" />
      <path d="M8 5v3.5l2.5 1.5" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ArrowRightIcon({ size = 12, color = C.textTertiary }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <path d="M3 8h10M9 4l4 4-4 4" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function CloseIcon({ size = 18, color = C.textSecondary }) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" fill="none">
      <path d="M5 5l8 8M13 5l-8 8" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function BoltIcon({ size = 16, color = C.gold }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path d="M13 10V3L4 14h7v7l9-11h-7z" fill={color} />
    </svg>
  );
}

function FixIcon({ size = 12, color = C.blue }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
      <path d="M10.5 2.5l3 3-8 8H2.5v-3l8-8z" stroke={color} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* ── Countdown strip ───────────────────────────────────────────────────── */
function CountdownStrip() {
  const days = daysUntilWindow();
  const weeks = Math.floor(days / 7);
  const urgency = days <= 90 ? "critical" : days <= 180 ? "warning" : "normal";
  const stripBg =
    urgency === "critical" ? C.redBg : urgency === "warning" ? C.amberBg : C.goldLight;
  const stripFg =
    urgency === "critical" ? C.red : urgency === "warning" ? C.amber : C.goldDark;

  return (
    <div
      style={{
        ...s.card,
        display: "flex",
        alignItems: "center",
        gap: 16,
        padding: "14px 20px",
        background: stripBg,
        borderColor: urgency === "critical" ? "#F5C6CB" : urgency === "warning" ? "#FDEBD0" : "#F5E6B8",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1 }}>
        <BoltIcon size={20} color={stripFg} />
        <span style={{ fontFamily: C.sans, fontSize: 13, fontWeight: 600, color: stripFg }}>
          NESO H2 2026 Connection Window
        </span>
      </div>
      <div style={{ textAlign: "right" }}>
        <span style={{ ...s.mono, fontSize: 24, fontWeight: 700, color: stripFg, lineHeight: 1 }}>
          {days}
        </span>
        <span style={{ fontFamily: C.sans, fontSize: 11, color: stripFg, marginLeft: 4 }}>
          days ({weeks} weeks)
        </span>
      </div>
    </div>
  );
}

/* ── Gate progression bar ──────────────────────────────────────────────── */
function GateProgressionBar({ gateStatuses, activeGate, onGateClick }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 0 }}>
      {GATES.map((gate, i) => {
        const status = gateStatuses[gate.id] || "pending";
        const sc = statusColor(status);
        const isActive = activeGate === gate.id;
        return (
          <React.Fragment key={gate.id}>
            {i > 0 && (
              <div
                style={{
                  width: 32,
                  height: 2,
                  background: gateStatuses[gate.id] === "ready" ? C.green : C.border,
                  flexShrink: 0,
                }}
              />
            )}
            <button
              onClick={() => onGateClick(gate.id)}
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 6,
                padding: "8px 6px",
                border: isActive ? `2px solid ${C.goldDark}` : `1px solid ${C.border}`,
                borderRadius: 10,
                background: isActive ? C.goldLight : C.card,
                cursor: "pointer",
                minWidth: 80,
                flex: 1,
                transition: "all 0.2s ease",
                boxShadow: isActive ? `0 0 0 3px ${C.goldLight}` : "none",
              }}
            >
              <div
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: "50%",
                  background: sc.bg,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  border: `1.5px solid ${sc.fg}`,
                }}
              >
                {status === "ready" ? (
                  <CheckIcon size={14} color={sc.fg} />
                ) : status === "blocked" ? (
                  <BlockIcon size={14} color={sc.fg} />
                ) : (
                  <span style={{ ...s.mono, fontSize: 11, fontWeight: 700, color: sc.fg }}>{gate.id}</span>
                )}
              </div>
              <span
                style={{
                  fontFamily: C.sans,
                  fontSize: 10,
                  fontWeight: 600,
                  color: isActive ? C.text : C.textSecondary,
                  textAlign: "center",
                  lineHeight: 1.2,
                }}
              >
                {gate.shortLabel}
              </span>
            </button>
          </React.Fragment>
        );
      })}
    </div>
  );
}

/* ── Readiness score ring ──────────────────────────────────────────────── */
function ScoreRing({ score, size = 64 }) {
  const r = (size - 8) / 2;
  const circ = 2 * Math.PI * r;
  const filled = (score / 100) * circ;
  const ringColor = score >= 80 ? C.green : score >= 50 ? C.amber : C.red;

  return (
    <div style={{ position: "relative", width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={C.border} strokeWidth={4} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={ringColor}
          strokeWidth={4}
          strokeDasharray={`${filled} ${circ - filled}`}
          strokeLinecap="round"
        />
      </svg>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <span style={{ ...s.mono, fontSize: 16, fontWeight: 700, color: C.text }}>{score}%</span>
      </div>
    </div>
  );
}

/* ── Requirement row ───────────────────────────────────────────────────── */
function RequirementRow({ req, status, note, onFix }) {
  const sc = statusColor(status);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "8px 0",
        borderBottom: `1px solid ${C.border}`,
      }}
    >
      <div style={{ flexShrink: 0, width: 20, display: "flex", justifyContent: "center" }}>
        {status === "ready" ? (
          <CheckIcon size={14} color={sc.fg} />
        ) : status === "blocked" ? (
          <BlockIcon size={14} color={sc.fg} />
        ) : (
          <ClockIcon size={14} color={sc.fg} />
        )}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontFamily: C.sans,
            fontSize: 12,
            fontWeight: 500,
            color: status === "ready" ? C.textSecondary : C.text,
            textDecoration: status === "ready" ? "line-through" : "none",
            lineHeight: 1.4,
          }}
        >
          {req.label}
        </div>
        {note && (
          <div style={{ fontFamily: C.sans, fontSize: 10, color: C.textTertiary, marginTop: 2 }}>{note}</div>
        )}
      </div>
      <div
        style={{
          flexShrink: 0,
          padding: "2px 8px",
          borderRadius: 6,
          background: sc.bg,
          fontFamily: C.sans,
          fontSize: 10,
          fontWeight: 600,
          color: sc.fg,
        }}
      >
        {statusLabel(status)}
      </div>
      {status !== "ready" && (
        <button
          onClick={() => onFix(req.fixAction, req.id)}
          style={{
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            gap: 4,
            padding: "4px 10px",
            border: `1px solid ${C.blue}`,
            borderRadius: 8,
            background: C.blueBg,
            cursor: "pointer",
            fontFamily: C.sans,
            fontSize: 10,
            fontWeight: 600,
            color: C.blue,
            transition: "all 0.15s",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = C.blue;
            e.currentTarget.style.color = "#fff";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = C.blueBg;
            e.currentTarget.style.color = C.blue;
          }}
        >
          <FixIcon size={10} color="currentColor" />
          Fix this
        </button>
      )}
    </div>
  );
}

/* ── Gate detail card ──────────────────────────────────────────────────── */
function GateDetail({ gate, reqStatuses, reqNotes, onFix, estimatedCost, estimatedWeeks }) {
  const statuses = gate.requirements.map((r) => reqStatuses?.[r.id] || "pending");
  const overallStatus = gateOverallStatus(statuses);
  const readyCount = statuses.filter((s) => s === "ready").length;
  const score = Math.round((readyCount / gate.requirements.length) * 100);
  const sc = statusColor(overallStatus);
  const cost = estimatedCost ?? gate.typicalCostGbp;
  const weeks = estimatedWeeks ?? gate.typicalWeeks;

  return (
    <div style={{ ...s.card, padding: 0 }}>
      {/* Gate header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          padding: "16px 20px",
          borderBottom: `1px solid ${C.border}`,
          background: C.bg,
        }}
      >
        <ScoreRing score={score} size={56} />
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <h3
              style={{
                fontFamily: C.sans,
                fontSize: 15,
                fontWeight: 700,
                color: C.text,
                margin: 0,
              }}
            >
              Gate {gate.id}: {gate.label}
            </h3>
            <span
              style={{
                padding: "2px 10px",
                borderRadius: 6,
                background: sc.bg,
                fontFamily: C.sans,
                fontSize: 10,
                fontWeight: 700,
                color: sc.fg,
                textTransform: "uppercase",
                letterSpacing: "0.5px",
              }}
            >
              {statusLabel(overallStatus)}
            </span>
          </div>
          <p style={{ fontFamily: C.sans, fontSize: 11, color: C.textSecondary, margin: "4px 0 0" }}>
            {gate.description}
          </p>
        </div>
      </div>

      {/* Metrics strip */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: 0,
          borderBottom: `1px solid ${C.border}`,
        }}
      >
        {[
          { label: "Requirements", value: `${readyCount}/${gate.requirements.length}`, sub: "complete" },
          { label: "Est. Cost", value: fmtGbp(cost), sub: "this gate" },
          { label: "Timeline", value: fmtWeeks(weeks), sub: "estimated" },
        ].map((m, i) => (
          <div
            key={m.label}
            style={{
              padding: "12px 16px",
              borderRight: i < 2 ? `1px solid ${C.border}` : "none",
              textAlign: "center",
            }}
          >
            <div style={{ ...s.sectionTitle, fontSize: 9, marginBottom: 4 }}>{m.label}</div>
            <div style={{ ...s.mono, fontSize: 16, fontWeight: 700, color: C.text }}>{m.value}</div>
            <div style={{ fontFamily: C.sans, fontSize: 9, color: C.textTertiary }}>{m.sub}</div>
          </div>
        ))}
      </div>

      {/* Requirements checklist */}
      <div style={{ padding: "12px 20px 16px" }}>
        <div style={{ ...s.sectionTitle, marginBottom: 8 }}>Requirements Checklist</div>
        {gate.requirements.map((req, i) => (
          <RequirementRow
            key={req.id}
            req={req}
            status={reqStatuses?.[req.id] || "pending"}
            note={reqNotes?.[req.id]}
            onFix={onFix}
          />
        ))}
      </div>
    </div>
  );
}

/* ── Cost timeline summary ─────────────────────────────────────────────── */
function CostTimeline({ gateData }) {
  const totalCost = GATES.reduce((sum, g) => sum + (gateData?.[g.id]?.cost ?? g.typicalCostGbp), 0);
  const totalWeeks = GATES.reduce((sum, g) => sum + (gateData?.[g.id]?.weeks ?? g.typicalWeeks), 0);

  return (
    <div style={{ ...s.card, padding: "16px 20px" }}>
      <div style={{ ...s.sectionTitle, marginBottom: 12 }}>Total Programme</div>
      <div style={{ display: "flex", gap: 24, marginBottom: 16 }}>
        <div>
          <div style={{ ...s.mono, fontSize: 22, fontWeight: 700, color: C.text }}>{fmtGbp(totalCost)}</div>
          <div style={{ fontFamily: C.sans, fontSize: 10, color: C.textTertiary }}>estimated total cost</div>
        </div>
        <div>
          <div style={{ ...s.mono, fontSize: 22, fontWeight: 700, color: C.text }}>{fmtWeeks(totalWeeks)}</div>
          <div style={{ fontFamily: C.sans, fontSize: 10, color: C.textTertiary }}>pre-app to energisation</div>
        </div>
      </div>

      {/* Cost waterfall */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {GATES.map((gate) => {
          const cost = gateData?.[gate.id]?.cost ?? gate.typicalCostGbp;
          const pct = totalCost > 0 ? (cost / totalCost) * 100 : 0;
          return (
            <div key={gate.id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span
                style={{
                  fontFamily: C.sans,
                  fontSize: 10,
                  color: C.textSecondary,
                  width: 70,
                  flexShrink: 0,
                  textAlign: "right",
                }}
              >
                Gate {gate.id}
              </span>
              <div
                style={{
                  flex: 1,
                  height: 8,
                  background: C.bg,
                  borderRadius: 4,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    width: `${pct}%`,
                    height: "100%",
                    background: `linear-gradient(90deg, ${C.gold}, ${C.goldDark})`,
                    borderRadius: 4,
                    transition: "width 0.4s ease",
                  }}
                />
              </div>
              <span style={{ ...s.mono, fontSize: 10, color: C.text, width: 50, flexShrink: 0 }}>
                {fmtGbp(cost)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Main: GateReadinessDashboard
   ═══════════════════════════════════════════════════════════════════════════ */
export default function GateReadinessDashboard({ lat, lon, capacityMw, technology, onClose }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeGate, setActiveGate] = useState(1);
  const [reqStatuses, setReqStatuses] = useState({});
  const [reqNotes, setReqNotes] = useState({});
  const [gateData, setGateData] = useState({});
  const [fixingAction, setFixingAction] = useState(null);
  const fetchedRef = useRef(false);

  /* ── Derive gate-level statuses from requirement statuses ──────────── */
  const gateStatuses = useMemo(() => {
    const result = {};
    for (const gate of GATES) {
      const statuses = gate.requirements.map((r) => reqStatuses[r.id] || "pending");
      result[gate.id] = gateOverallStatus(statuses);
    }
    return result;
  }, [reqStatuses]);

  /* ── Overall readiness score ───────────────────────────────────────── */
  const overallScore = useMemo(() => {
    const allReqs = GATES.flatMap((g) => g.requirements);
    const readyCount = allReqs.filter((r) => reqStatuses[r.id] === "ready").length;
    return Math.round((readyCount / allReqs.length) * 100);
  }, [reqStatuses]);

  /* ── Fetch data from APIs ──────────────────────────────────────────── */
  const fetchReadiness = useCallback(async () => {
    setLoading(true);
    setError(null);

    const params = new URLSearchParams({
      lat: lat ?? 52.5,
      lon: lon ?? -1.5,
      capacity_mw: capacityMw ?? 50,
      technology: technology ?? "solar",
    });

    try {
      // Fetch from all three endpoints in parallel
      const [readinessRes, assessRes, envRes] = await Promise.allSettled([
        fetch(`/api/grid/gate-readiness?${params}`).then((r) => (r.ok ? r.json() : null)),
        fetch(`/api/grid/assess?${params}`, { method: "POST" }).then((r) => (r.ok ? r.json() : null)),
        fetch(`/api/grid/environmental-constraints?${params}`).then((r) => (r.ok ? r.json() : null)),
      ]);

      const readiness = readinessRes.status === "fulfilled" ? readinessRes.value : null;
      const assess = assessRes.status === "fulfilled" ? assessRes.value : null;
      const env = envRes.status === "fulfilled" ? envRes.value : null;

      // Build requirement statuses from combined API data
      const statuses = {};
      const notes = {};
      const gData = {};

      // If /gate-readiness returned structured data, use it directly
      if (readiness?.requirements) {
        for (const [reqId, reqData] of Object.entries(readiness.requirements)) {
          statuses[reqId] = reqData.status || "pending";
          if (reqData.note) notes[reqId] = reqData.note;
        }
      }

      if (readiness?.gates) {
        for (const [gateId, data] of Object.entries(readiness.gates)) {
          gData[parseInt(gateId)] = {
            cost: data.estimated_cost_gbp,
            weeks: data.estimated_weeks,
          };
        }
      }

      // Enrich from /assess results
      if (assess) {
        // Grid feasibility is done if we got a response
        if (!statuses.grid_feasibility) {
          statuses.grid_feasibility = "ready";
          notes.grid_feasibility = `${assess.verdict || "Assessed"} - ${assess.candidates?.length || 0} substations found`;
        }

        // Power flow study — mark ready if assess includes power flow data
        if (assess.power_flow || assess.candidates?.some((c) => c.headroom_mw != null)) {
          statuses.power_flow = statuses.power_flow || "ready";
          notes.power_flow = "N-1 power flow analysis complete";
        }

        // Financial model — mark pending with note if cost data exists
        if (assess.cost_estimate && !statuses.financial_model) {
          statuses.financial_model = "pending";
          notes.financial_model = `Grid cost ${fmtGbp(assess.cost_estimate?.cost_gbp?.p50)} — awaiting full financial model`;
        }

        // Connection application status
        if (assess.verdict === "GO" && !statuses.conn_application) {
          statuses.conn_application = "pending";
          notes.conn_application = "Site viable for connection — application can proceed";
        }

        // DNO pre-application meeting
        if (assess.dno_area && !statuses.dno_pre_app) {
          statuses.dno_pre_app = "pending";
          notes.dno_pre_app = `${assess.dno_area.name} — request pre-app meeting`;
        }

        // Update Gate 2 cost estimate from grid assess
        if (assess.cost_estimate?.cost_gbp?.p50 && !gData[2]) {
          gData[2] = {
            cost: Math.round(assess.cost_estimate.cost_gbp.p50 * 0.15) + 100000,
            weeks: assess.cost_estimate.timeline_weeks?.p50 || 52,
          };
        }
      }

      // Enrich from /environmental-constraints
      if (env) {
        const hasConstraints = env.constraints?.length > 0 || env.designations?.length > 0;
        if (!statuses.env_screening) {
          statuses.env_screening = "ready";
          notes.env_screening = hasConstraints
            ? `${env.constraints?.length || 0} constraints identified — screening complete`
            : "No significant constraints found";
        }

        // EIA depends on constraint severity
        if (!statuses.eia_complete) {
          const severe = env.constraints?.filter((c) => c.severity === "high" || c.blocking)?.length || 0;
          if (severe > 0) {
            statuses.eia_complete = "blocked";
            notes.eia_complete = `${severe} high-severity constraint(s) require full EIA`;
          } else if (hasConstraints) {
            statuses.eia_complete = "pending";
            notes.eia_complete = "Screening opinion needed — likely no full EIA required";
          }
        }
      }

      setReqStatuses((prev) => ({ ...prev, ...statuses }));
      setReqNotes((prev) => ({ ...prev, ...notes }));
      setGateData((prev) => ({ ...prev, ...gData }));

      // Auto-select the first incomplete gate
      for (const gate of GATES) {
        const gStatuses = gate.requirements.map((r) => statuses[r.id] || "pending");
        if (!gStatuses.every((s) => s === "ready")) {
          setActiveGate(gate.id);
          break;
        }
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [lat, lon, capacityMw, technology]);

  useEffect(() => {
    if (fetchedRef.current) return;
    fetchedRef.current = true;
    fetchReadiness();
  }, [fetchReadiness]);

  /* ── Fix action handler ────────────────────────────────────────────── */
  const handleFix = useCallback(
    async (action, reqId) => {
      setFixingAction(reqId);
      try {
        const params = new URLSearchParams({
          lat: lat ?? 52.5,
          lon: lon ?? -1.5,
          capacity_mw: capacityMw ?? 50,
          technology: technology ?? "solar",
          intent: action,
        });

        const res = await fetch(`/api/agent/analyse?${params}`, { method: "POST" });
        if (res.ok) {
          const data = await res.json();
          // If analysis succeeded, update the requirement status
          if (data.verdict === "GO" || data.status === "complete") {
            setReqStatuses((prev) => ({ ...prev, [reqId]: "ready" }));
            setReqNotes((prev) => ({
              ...prev,
              [reqId]: data.summary || "Analysis complete — requirement satisfied",
            }));
          } else {
            setReqNotes((prev) => ({
              ...prev,
              [reqId]: data.summary || `Analysis run — review results (${action})`,
            }));
          }
        }
      } catch {
        // Silent fail — user sees no change
      } finally {
        setFixingAction(null);
      }
    },
    [lat, lon, capacityMw, technology]
  );

  const activeGateObj = GATES.find((g) => g.id === activeGate);

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        right: 0,
        bottom: 0,
        width: 520,
        zIndex: 14,
        display: "flex",
        flexDirection: "column",
        background: C.bg,
        borderLeft: `1px solid ${C.border}`,
        overflow: "hidden",
        animation: "grd-slide-in 0.3s cubic-bezier(0.16, 1, 0.3, 1)",
        fontFamily: C.sans,
      }}
    >
      {/* ── Inline keyframe animation ──────────────────────────────────── */}
      <style>{`
        @keyframes grd-slide-in {
          from { transform: translateX(100%); opacity: 0; }
          to   { transform: translateX(0);    opacity: 1; }
        }
        @keyframes grd-pulse {
          0%, 100% { opacity: 0.4; }
          50%      { opacity: 1; }
        }
        .grd-fix-btn:hover {
          background: ${C.blue} !important;
          color: #fff !important;
        }
      `}</style>

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 20px",
          borderBottom: `1px solid ${C.border}`,
          background: C.card,
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <BoltIcon size={18} color={C.goldDark} />
          <div>
            <div
              style={{
                fontSize: 13,
                fontWeight: 700,
                letterSpacing: "1.5px",
                textTransform: "uppercase",
                color: C.text,
              }}
            >
              Gate Readiness
            </div>
            <div style={{ fontSize: 10, color: C.textTertiary, marginTop: 1 }}>
              NESO Connections Reform Queue
            </div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <ScoreRing score={overallScore} size={40} />
          <button
            onClick={onClose}
            style={{
              width: 32,
              height: 32,
              border: `1px solid ${C.border}`,
              background: C.card,
              borderRadius: 8,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              transition: "all 0.15s",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = C.bg)}
            onMouseLeave={(e) => (e.currentTarget.style.background = C.card)}
          >
            <CloseIcon size={16} color={C.textSecondary} />
          </button>
        </div>
      </div>

      {/* ── Scrollable body ────────────────────────────────────────────── */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          overflowX: "hidden",
          padding: "16px 16px 24px",
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        {/* Countdown */}
        <CountdownStrip />

        {/* Site context */}
        <div
          style={{
            ...s.card,
            padding: "10px 16px",
            display: "flex",
            gap: 16,
            alignItems: "center",
          }}
        >
          {[
            { label: "Location", value: `${(lat ?? 52.5).toFixed(4)}, ${(lon ?? -1.5).toFixed(4)}` },
            { label: "Capacity", value: `${capacityMw ?? 50} MW` },
            { label: "Technology", value: (technology ?? "solar").charAt(0).toUpperCase() + (technology ?? "solar").slice(1) },
          ].map((item) => (
            <div key={item.label} style={{ flex: 1 }}>
              <div style={{ ...s.sectionTitle, fontSize: 9, marginBottom: 2 }}>{item.label}</div>
              <div style={{ ...s.mono, fontSize: 12, fontWeight: 600, color: C.text }}>{item.value}</div>
            </div>
          ))}
        </div>

        {/* Loading state */}
        {loading && (
          <div
            style={{
              ...s.card,
              padding: "40px 20px",
              textAlign: "center",
            }}
          >
            <div
              style={{
                width: 32,
                height: 32,
                margin: "0 auto 12px",
                border: `3px solid ${C.border}`,
                borderTopColor: C.goldDark,
                borderRadius: "50%",
                animation: "grd-spin 0.8s linear infinite",
              }}
            />
            <style>{`@keyframes grd-spin { to { transform: rotate(360deg); } }`}</style>
            <div style={{ fontSize: 12, color: C.textSecondary }}>Analysing gate readiness...</div>
            <div style={{ fontSize: 10, color: C.textTertiary, marginTop: 4 }}>
              Querying grid, environmental, and planning data
            </div>
          </div>
        )}

        {/* Error state */}
        {error && !loading && (
          <div style={{ ...s.card, padding: "16px 20px", background: C.redBg, borderColor: "#F5C6CB" }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: C.red, marginBottom: 4 }}>
              Assessment failed
            </div>
            <div style={{ fontSize: 11, color: C.red }}>{error}</div>
            <button
              onClick={() => {
                fetchedRef.current = false;
                fetchReadiness();
              }}
              style={{
                marginTop: 8,
                padding: "6px 16px",
                border: `1px solid ${C.red}`,
                borderRadius: 8,
                background: C.card,
                color: C.red,
                fontSize: 11,
                fontWeight: 600,
                cursor: "pointer",
                fontFamily: C.sans,
              }}
            >
              Retry
            </button>
          </div>
        )}

        {/* Gate progression */}
        {!loading && (
          <>
            <div style={{ ...s.card, padding: "16px 12px" }}>
              <div style={{ ...s.sectionTitle, marginBottom: 12, paddingLeft: 4 }}>Gate Progression</div>
              <GateProgressionBar
                gateStatuses={gateStatuses}
                activeGate={activeGate}
                onGateClick={setActiveGate}
              />
            </div>

            {/* Active gate detail */}
            {activeGateObj && (
              <GateDetail
                gate={activeGateObj}
                reqStatuses={reqStatuses}
                reqNotes={reqNotes}
                onFix={handleFix}
                estimatedCost={gateData[activeGateObj.id]?.cost}
                estimatedWeeks={gateData[activeGateObj.id]?.weeks}
              />
            )}

            {/* Cost & timeline summary */}
            <CostTimeline gateData={gateData} />

            {/* Refresh strip */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "8px 4px",
              }}
            >
              <span style={{ fontSize: 10, color: C.textTertiary }}>
                Data from grid assess, environmental constraints, and gate readiness APIs
              </span>
              <button
                onClick={() => {
                  fetchedRef.current = false;
                  fetchReadiness();
                }}
                style={{
                  padding: "4px 12px",
                  border: `1px solid ${C.border}`,
                  borderRadius: 8,
                  background: C.card,
                  color: C.textSecondary,
                  fontSize: 10,
                  fontWeight: 600,
                  cursor: "pointer",
                  fontFamily: C.sans,
                  transition: "all 0.15s",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = C.goldDark;
                  e.currentTarget.style.color = C.goldDark;
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = C.border;
                  e.currentTarget.style.color = C.textSecondary;
                }}
              >
                Refresh
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
