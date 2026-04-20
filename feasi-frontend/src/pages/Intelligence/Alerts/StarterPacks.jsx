import React, { useEffect, useState } from "react";
import mock from "../../../data/mock-alerts.json";

const C = {
  gold: "#F5B731",
  goldDark: "#B5912F",
  goldSoft: "#C9A64B",
  goldSurface: "rgba(245,183,49,0.10)",
  goldBorder: "rgba(245,183,49,0.32)",
  ink: "#0F1318",
  secondary: "#4B5563",
  tertiary: "#9C9590",
  border: "#E8EAED",
  ivory: "#FBF8F2",
};

const PERSONA_ICONS = {
  "Solar developer":     "☀",
  "BESS developer":      "⬛",
  "Data centre developer": "▢",
  "Grid consultant":     "◈",
  "Land agent":          "⌂",
};

function PackCard({ pack, onSubscribeAll, onCustomise }) {
  const [hover, setHover] = useState(false);
  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        background: "#FFFFFF",
        border: `1px solid ${hover ? C.goldBorder : C.border}`,
        borderRadius: 10,
        padding: "14px 16px",
        minWidth: 0,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        transition: "border-color 120ms ease",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          aria-hidden
          style={{
            width: 28, height: 28,
            borderRadius: 6,
            background: C.goldSurface,
            color: C.goldDark,
            fontSize: 14,
            display: "inline-flex", alignItems: "center", justifyContent: "center",
          }}
        >
          {PERSONA_ICONS[pack.persona] || "◆"}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.ink }}>{pack.persona}</div>
          <div style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 10, color: C.tertiary, letterSpacing: "0.04em",
          }}>
            {pack.alert_count} alerts
          </div>
        </div>
      </div>

      <p style={{
        margin: 0,
        fontSize: 12, lineHeight: 1.5, color: C.secondary,
        minHeight: 54,
      }}>
        {pack.description}
      </p>

      <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
        <button
          onClick={() => onSubscribeAll(pack)}
          style={{
            flex: 1,
            padding: "6px 10px",
            fontSize: 11,
            fontWeight: 700,
            fontFamily: "'DM Sans', sans-serif",
            borderRadius: 6,
            border: `1px solid ${C.goldBorder}`,
            background: C.goldSurface,
            color: C.ink,
            cursor: "pointer",
          }}
        >
          Subscribe all
        </button>
        <button
          onClick={() => onCustomise(pack)}
          style={{
            padding: "6px 10px",
            fontSize: 11,
            fontWeight: 600,
            fontFamily: "'DM Sans', sans-serif",
            borderRadius: 6,
            border: `1px solid ${C.border}`,
            background: "transparent",
            color: C.secondary,
            cursor: "pointer",
          }}
        >
          Customise
        </button>
      </div>
    </div>
  );
}

export default function StarterPacks({ onSubscribePack, onCustomisePack, onAskAnything }) {
  const [packs, setPacks] = useState([]);

  useEffect(() => {
    // Starter packs are a static catalogue — use mock fixture directly.
    setPacks(mock.starter_packs || []);
  }, []);

  return (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        overflowY: "auto",
        padding: "28px 28px 32px",
        background: C.ivory,
      }}
    >
      {/* Hero */}
      <div style={{ maxWidth: 780, marginBottom: 24 }}>
        <div style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 10, fontWeight: 700, color: C.goldSoft,
          letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 6,
        }}>
          Alerts — get started
        </div>
        <h2 style={{
          margin: "0 0 6px",
          fontSize: 22, fontWeight: 800, letterSpacing: "-0.02em", color: C.ink,
        }}>
          Pick a starter pack, or wire up alerts one by one.
        </h2>
        <p style={{
          margin: 0,
          fontSize: 13, lineHeight: 1.55, color: C.secondary, maxWidth: 620,
        }}>
          Every pack is a curated bundle of live feeds — Ofgem TEC, DNO ECRs, PINS DCOs, LPA
          majors, DESNZ policy, NESO market. Subscribe in one click, customise later, and
          read the daily digest in the middle column.
        </p>
      </div>

      {/* Pack grid */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))",
          gap: 12,
          marginBottom: 24,
        }}
      >
        {packs.map((pack) => (
          <PackCard
            key={pack.id}
            pack={pack}
            onSubscribeAll={onSubscribePack}
            onCustomise={onCustomisePack}
          />
        ))}
      </div>

      {/* Ask-anything hint */}
      <div style={{
        maxWidth: 780,
        padding: "12px 14px",
        background: "#FFFFFF",
        border: `1px dashed ${C.goldBorder}`,
        borderRadius: 10,
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}>
        <div style={{
          fontSize: 20, color: C.goldDark,
        }}>◆</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.ink }}>
            Already know what you need?
          </div>
          <div style={{ fontSize: 12, color: C.secondary, lineHeight: 1.5 }}>
            Ask a question and Princeps will scan the document corpus, with citations.
          </div>
        </div>
        <button
          onClick={() => onAskAnything?.("What grid capacity changed in the last week?")}
          style={{
            padding: "6px 12px",
            fontSize: 11, fontWeight: 700,
            borderRadius: 6,
            border: `1px solid ${C.goldBorder}`,
            background: C.goldSurface,
            color: C.ink,
            cursor: "pointer",
          }}
        >
          Ask Princeps
        </button>
      </div>
    </div>
  );
}
