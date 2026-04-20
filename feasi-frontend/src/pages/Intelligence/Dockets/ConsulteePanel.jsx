import React, { useMemo, useState } from "react";
import { COLOURS, SANS, MONO } from "./tokens";
import DraftEmailModal from "./DraftEmailModal";
import { useConsultees } from "../../../hooks/useConsultees";

// The "moat" component — grouped checklist of statutory consultees with
// per-row Draft-Email trigger.
const STATUS_COLOUR = {
  "Notified":  { fg: "#4B5563", bg: "rgba(107,114,128,.14)" },
  "Responded": { fg: "#1F6A3F", bg: "rgba(59,138,90,.18)" },
  "Objects":   { fg: "#FFFFFF", bg: "#B84A4A" },
  "Supports":  { fg: "#FFFFFF", bg: "#3B8A5A" },
  "Conditions":{ fg: "#FFFFFF", bg: "#E89A2A" },
  "Silent":    { fg: "#4B5563", bg: "rgba(156,163,175,.25)" },
};

const CATEGORY_ORDER = [
  "Statutory",
  "Network operators",
  "Local authority",
  "Environmental",
  "Heritage",
  "Safety",
  "Sector-specific",
  "Political",
];

export default function ConsulteePanel({ docket }) {
  const { consultees, loading } = useConsultees({
    case_type: docket?.case_type,
    tech: docket?.technology,
    capacity_mw: docket?.capacity_mw,
  });

  const [checked, setChecked] = useState({});
  const [draftFor, setDraftFor] = useState(null);

  const byCategory = useMemo(() => {
    const m = {};
    for (const c of consultees || []) {
      const cat = c.category || "Other";
      if (!m[cat]) m[cat] = [];
      m[cat].push(c);
    }
    return m;
  }, [consultees]);

  const cats = [
    ...CATEGORY_ORDER.filter((c) => byCategory[c]),
    ...Object.keys(byCategory).filter((c) => !CATEGORY_ORDER.includes(c)),
  ];

  const totalChecked = Object.values(checked).filter(Boolean).length;

  return (
    <>
      <section
        style={{
          background: "#FFFFFF",
          border: `1px solid ${COLOURS.border}`,
          borderRadius: 8,
          padding: 20,
          fontFamily: SANS,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: COLOURS.ink, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Consultees
            <span style={{ color: COLOURS.muted, fontWeight: 500, marginLeft: 6 }}>
              ({consultees?.length || 0})
            </span>
          </h3>
          <div style={{ fontSize: 11, color: COLOURS.muted }}>
            {totalChecked > 0 && (
              <>
                <span style={{ fontFamily: MONO, color: COLOURS.ink, fontWeight: 700 }}>{totalChecked}</span> selected —{" "}
              </>
            )}
            Generated from <strong style={{ color: COLOURS.ink }}>{docket?.case_type || "—"}</strong> · tech {docket?.technology || "—"}
          </div>
        </div>

        {loading && <div style={{ color: COLOURS.muted, fontSize: 12 }}>Loading consultees…</div>}

        {cats.map((cat) => (
          <div key={cat} style={{ marginBottom: 14 }}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: COLOURS.muted,
                textTransform: "uppercase",
                letterSpacing: 0.5,
                marginBottom: 6,
                paddingBottom: 6,
                borderBottom: `1px solid ${COLOURS.border}`,
              }}
            >
              {cat}
            </div>
            {byCategory[cat].map((c) => {
              const status = STATUS_COLOUR[c.status] || STATUS_COLOUR.Silent;
              const isChecked = !!checked[c.id];
              return (
                <div
                  key={c.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "8px 4px",
                    borderBottom: `1px solid ${COLOURS.border}`,
                  }}
                >
                  <button
                    onClick={() => setChecked({ ...checked, [c.id]: !isChecked })}
                    aria-label={isChecked ? "Uncheck" : "Check"}
                    style={{
                      width: 16,
                      height: 16,
                      padding: 0,
                      border: `1.5px solid ${isChecked ? COLOURS.gold : COLOURS.mutedLight}`,
                      background: isChecked ? COLOURS.gold : "transparent",
                      borderRadius: 3,
                      cursor: "pointer",
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flexShrink: 0,
                    }}
                  >
                    {isChecked && (
                      <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke={COLOURS.ink} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M2 5 L4 7 L8 3" />
                      </svg>
                    )}
                  </button>

                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: COLOURS.ink }}>{c.name}</div>
                    <div style={{ fontSize: 11, color: COLOURS.muted, marginTop: 1 }}>
                      <span style={{ fontFamily: MONO }}>{c.statutory_hook}</span>
                      {c.applicable_when && <span> · {c.applicable_when}</span>}
                    </div>
                  </div>

                  <span
                    style={{
                      padding: "2px 8px",
                      fontSize: 10.5,
                      fontWeight: 600,
                      color: status.fg,
                      background: status.bg,
                      borderRadius: 10,
                      textTransform: "uppercase",
                      letterSpacing: 0.4,
                      flexShrink: 0,
                    }}
                  >
                    {c.status}
                  </span>

                  <button
                    onClick={() => setDraftFor(c)}
                    style={{
                      padding: "4px 10px",
                      fontSize: 11.5,
                      fontWeight: 600,
                      border: `1px solid ${COLOURS.gold}`,
                      background: "#FFFFFF",
                      color: COLOURS.ink,
                      borderRadius: 4,
                      cursor: "pointer",
                      flexShrink: 0,
                      fontFamily: SANS,
                    }}
                  >
                    Draft email
                  </button>
                </div>
              );
            })}
          </div>
        ))}
      </section>

      <DraftEmailModal
        open={!!draftFor}
        consultee={draftFor}
        docket={docket}
        onClose={() => setDraftFor(null)}
      />
    </>
  );
}
