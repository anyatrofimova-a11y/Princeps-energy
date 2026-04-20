import React, { useState } from "react";
import { COLOURS, SANS, MONO } from "./tokens";
import api from "../../../api/dockets";

// Three starter Q&A cards with refresh. Plus an "Ask your own" bar.
export default function QuestionCards({ docket }) {
  const starters = docket?.questions || [];
  const [custom, setCustom] = useState("");
  const [customAnswer, setCustomAnswer] = useState(null);
  const [asking, setAsking] = useState(false);

  const ask = () => {
    if (!custom.trim() || !docket) return;
    setAsking(true);
    setCustomAnswer({ q: custom, text: "" });
    api.streamQuestion(docket.id, custom, {
      onToken: (tk) => setCustomAnswer((p) => ({ ...p, text: (p?.text || "") + tk })),
      onDone: () => setAsking(false),
      onError: () => setAsking(false),
    });
    setCustom("");
  };

  return (
    <section style={{ fontFamily: SANS }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: COLOURS.ink, textTransform: "uppercase", letterSpacing: 0.5 }}>
          Starter Questions
        </h3>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 12, marginBottom: 12 }}>
        {starters.map((s, i) => (
          <QuestionCard key={i} card={s} docketId={docket?.id} />
        ))}
      </div>

      {/* Ask your own */}
      <div
        style={{
          display: "flex",
          gap: 8,
          padding: 10,
          background: "#FFFFFF",
          border: `1px solid ${COLOURS.border}`,
          borderRadius: 8,
        }}
      >
        <input
          type="text"
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") ask();
          }}
          placeholder="Ask your own question about this docket…"
          style={{
            flex: 1,
            padding: "8px 10px",
            border: `1px solid ${COLOURS.border}`,
            borderRadius: 6,
            fontSize: 13,
            fontFamily: SANS,
            color: COLOURS.ink,
            outline: "none",
          }}
        />
        <button
          onClick={ask}
          disabled={asking || !custom.trim()}
          style={{
            padding: "8px 16px",
            background: COLOURS.gold,
            color: COLOURS.ink,
            border: "none",
            borderRadius: 6,
            fontSize: 12.5,
            fontWeight: 600,
            cursor: custom.trim() && !asking ? "pointer" : "default",
            opacity: custom.trim() && !asking ? 1 : 0.5,
            fontFamily: SANS,
          }}
        >
          Ask
        </button>
      </div>

      {customAnswer && (
        <div style={{ marginTop: 10, padding: 14, background: "#FFFFFF", border: `1px solid ${COLOURS.border}`, borderRadius: 8 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: COLOURS.inkSoft, marginBottom: 6 }}>{customAnswer.q}</div>
          <div style={{ fontSize: 13, lineHeight: 1.6, color: COLOURS.ink }}>{customAnswer.text}{asking && <span style={{ color: COLOURS.gold }}>▋</span>}</div>
        </div>
      )}
    </section>
  );
}

function QuestionCard({ card, docketId }) {
  const [bullets, setBullets] = useState(card.bullets);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = () => {
    if (!docketId) return;
    setRefreshing(true);
    let acc = "";
    api.streamQuestion(docketId, card.q, {
      onToken: (tk) => {
        acc += tk;
      },
      onDone: () => {
        setBullets([acc]);
        setRefreshing(false);
      },
      onError: () => setRefreshing(false),
    });
  };

  return (
    <div
      style={{
        background: "#FFFFFF",
        border: `1px solid ${COLOURS.border}`,
        borderRadius: 8,
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        minHeight: 160,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: COLOURS.ink, lineHeight: 1.35 }}>{card.q}</div>
        <button
          onClick={refresh}
          title="Refresh"
          disabled={refreshing}
          style={{
            flexShrink: 0,
            width: 24,
            height: 24,
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            background: "transparent",
            border: `1px solid ${COLOURS.border}`,
            borderRadius: 4,
            cursor: refreshing ? "default" : "pointer",
            color: COLOURS.muted,
          }}
        >
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 8a6 6 0 11-1.8-4.2M14 3v3h-3" />
          </svg>
        </button>
      </div>
      <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12, color: COLOURS.inkSoft, lineHeight: 1.55 }}>
        {bullets.map((b, i) => (
          <li key={i} style={{ marginBottom: 4 }}>
            <Citations text={b} />
          </li>
        ))}
      </ul>
    </div>
  );
}

// Lightweight citation highlighter — just recolours [n] to gold.
function Citations({ text }) {
  const parts = [];
  const re = /\[(\d+)\]/g;
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    parts.push({ n: m[1] });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return (
    <>
      {parts.map((p, i) =>
        typeof p === "string" ? (
          <React.Fragment key={i}>{p}</React.Fragment>
        ) : (
          <sup key={i} style={{ fontFamily: MONO, fontSize: 10, fontWeight: 700, color: COLOURS.gold, marginLeft: 2 }}>
            [{p.n}]
          </sup>
        )
      )}
    </>
  );
}
