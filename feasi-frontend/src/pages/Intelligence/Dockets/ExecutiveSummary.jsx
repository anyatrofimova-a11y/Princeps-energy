import React, { useState, useMemo, useCallback } from "react";
import { COLOURS, SANS, MONO, formatDate } from "./tokens";
import api from "../../../api/dockets";

// Executive Summary card — LLM prose with inline gold numeral citations.
// Hover over a [n] reveals the source document in a tooltip.
export default function ExecutiveSummary({ docket }) {
  const [text, setText] = useState(docket?.summary || "");
  const [streaming, setStreaming] = useState(false);
  const [lastGen, setLastGen] = useState(new Date(Date.now() - 3 * 3600 * 1000));
  const citations = docket?.citations || [];

  const byN = useMemo(() => {
    const map = {};
    for (const c of citations) map[c.n] = c;
    return map;
  }, [citations]);

  const regenerate = useCallback(() => {
    if (!docket) return;
    setStreaming(true);
    setText("");
    const cancel = api.streamSummaryRefresh(docket.id, {
      onToken: (tk) => setText((prev) => prev + tk),
      onDone: (full) => {
        setText(full);
        setStreaming(false);
        setLastGen(new Date());
      },
      onError: () => setStreaming(false),
    });
    return cancel;
  }, [docket]);

  if (!docket) return null;

  return (
    <section
      style={{
        background: "#FFFFFF",
        border: `1px solid ${COLOURS.border}`,
        borderRadius: 8,
        padding: 20,
        fontFamily: SANS,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: COLOURS.ink, textTransform: "uppercase", letterSpacing: 0.5 }}>
          Executive Summary
        </h3>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 11, color: COLOURS.muted }}>
            Last generated {formatRel(lastGen)}
          </span>
          <button
            onClick={regenerate}
            disabled={streaming}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "5px 10px",
              fontSize: 11.5,
              fontWeight: 600,
              color: COLOURS.ink,
              background: streaming ? COLOURS.ivory : "#FFFFFF",
              border: `1px solid ${COLOURS.gold}`,
              borderRadius: 4,
              cursor: streaming ? "default" : "pointer",
              fontFamily: SANS,
            }}
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 8a6 6 0 11-1.8-4.2M14 3v3h-3" />
            </svg>
            {streaming ? "Generating…" : "Regenerate"}
          </button>
        </div>
      </div>

      <p style={{ fontSize: 14, lineHeight: 1.65, color: COLOURS.ink, margin: 0 }}>
        <Citations text={text} byN={byN} />
        {streaming && <span style={{ color: COLOURS.gold, marginLeft: 2 }}>▋</span>}
      </p>
    </section>
  );
}

// Render prose with [n] tags turned into hover-tooltip chips.
function Citations({ text, byN }) {
  const parts = [];
  const re = /\[(\d+)\]/g;
  let last = 0;
  let match;
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    parts.push({ n: parseInt(match[1], 10) });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));

  return (
    <>
      {parts.map((p, i) => {
        if (typeof p === "string") return <React.Fragment key={i}>{p}</React.Fragment>;
        return <CitationChip key={i} n={p.n} citation={byN[p.n]} />;
      })}
    </>
  );
}

function CitationChip({ n, citation }) {
  const [hover, setHover] = useState(false);
  return (
    <span
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        position: "relative",
        display: "inline-block",
        marginLeft: 2,
      }}
    >
      <sup
        style={{
          fontFamily: MONO,
          fontSize: 10.5,
          fontWeight: 700,
          color: COLOURS.gold,
          padding: "0 3px",
          cursor: "help",
        }}
      >
        [{n}]
      </sup>
      {hover && citation && (
        <span
          style={{
            position: "absolute",
            bottom: "125%",
            left: "50%",
            transform: "translateX(-50%)",
            minWidth: 240,
            maxWidth: 320,
            padding: "8px 10px",
            background: COLOURS.ink,
            color: "#FFFFFF",
            borderRadius: 6,
            fontSize: 11.5,
            lineHeight: 1.5,
            zIndex: 20,
            boxShadow: "0 6px 16px rgba(0,0,0,.25)",
            textAlign: "left",
          }}
        >
          <div style={{ fontWeight: 700, marginBottom: 2 }}>
            [{citation.n}] {citation.title}
          </div>
          <div style={{ opacity: 0.7, fontFamily: MONO, fontSize: 10.5 }}>{formatDate(citation.date)}</div>
        </span>
      )}
    </span>
  );
}

function formatRel(d) {
  const diff = Date.now() - (+d);
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}
