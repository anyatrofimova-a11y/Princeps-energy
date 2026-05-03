/**
 * /v2/council — minimal Council demo.
 *
 * One-line input bar, three pod columns, an adjudicator panel, and a
 * vertical event timeline. Engineering-tone, no flourish; the real
 * Council UI lands in a later cut.
 */

import React, { useState } from "react";
import useCouncilSession from "../../hooks/useCouncilSession";

const PALETTE = {
  bg: "#0F1318",
  panel: "#171C22",
  panelLight: "#1F252C",
  border: "#2A3138",
  text: "#E8ECF1",
  muted: "#94A3B8",
  gold: "#D4A018",
  go: "#10B981",
  caution: "#F59E0B",
  nogo: "#EF4444",
};

const VERDICT_COLOR = (v) => ({
  GO: PALETTE.go, CAUTION: PALETTE.caution, "NO-GO": PALETTE.nogo,
}[v] || PALETTE.muted);

function PodCard({ name, pod }) {
  const verdict = pod?.verdict?.verdict;
  const color = VERDICT_COLOR(verdict);
  return (
    <div style={{
      flex: 1, minWidth: 240,
      background: PALETTE.panel,
      border: `1px solid ${PALETTE.border}`,
      borderRadius: 8,
      padding: 14,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1.2, textTransform: "uppercase", color: PALETTE.muted }}>
          {name}
        </div>
        <div style={{
          fontSize: 11,
          padding: "2px 8px",
          borderRadius: 999,
          background: pod?.status === "complete" ? color + "22" : "#33343a",
          color: pod?.status === "complete" ? color : PALETTE.muted,
          fontWeight: 600,
        }}>
          {pod?.status || "pending"}
        </div>
      </div>
      {pod?.tools_bound?.length > 0 && (
        <div style={{ fontSize: 10, color: PALETTE.muted, marginBottom: 6 }}>
          tools: {pod.tools_bound.join(", ")}
        </div>
      )}
      {pod?.tools_stubbed?.length > 0 && (
        <div style={{ fontSize: 10, color: PALETTE.caution, marginBottom: 6 }}>
          stubbed: {pod.tools_stubbed.join(", ")}
        </div>
      )}
      {verdict && (
        <div style={{ marginTop: 10 }}>
          <div style={{
            fontSize: 22, fontWeight: 700, color, marginBottom: 4,
          }}>
            {verdict}
          </div>
          <div style={{ fontSize: 12, color: PALETTE.muted, marginBottom: 8 }}>
            confidence {(pod.verdict.confidence * 100 | 0)}%
          </div>
          <div style={{ fontSize: 12, lineHeight: 1.4, color: PALETTE.text }}>
            {pod.verdict.summary}
          </div>
          {pod.verdict.risks?.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 10, color: PALETTE.muted, fontWeight: 600 }}>RISKS</div>
              {pod.verdict.risks.slice(0, 3).map((r, i) => (
                <div key={i} style={{ fontSize: 11, color: PALETTE.text, lineHeight: 1.4 }}>
                  - {r}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AdjudicatorPanel({ state, onAnswer }) {
  const final = state.final;
  const adj = state.adjudication;
  const clar = state.clarification;
  return (
    <div style={{
      background: PALETTE.panel,
      border: `2px solid ${final ? VERDICT_COLOR(final.verdict) : PALETTE.gold}`,
      borderRadius: 8,
      padding: 16,
    }}>
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1.2, textTransform: "uppercase", color: PALETTE.gold, marginBottom: 8 }}>
        ADJUDICATOR
      </div>
      {!final && !adj && (
        <div style={{ fontSize: 12, color: PALETTE.muted }}>
          waiting on pods...
        </div>
      )}
      {adj && !final && (
        <div style={{ fontSize: 12, color: PALETTE.muted, marginBottom: 8 }}>
          adjudication: {adj.stage}
        </div>
      )}
      {final && (
        <>
          <div style={{ fontSize: 30, fontWeight: 700, color: VERDICT_COLOR(final.verdict) }}>
            {final.verdict}
          </div>
          <div style={{ fontSize: 12, color: PALETTE.muted, marginBottom: 10 }}>
            confidence {(final.confidence * 100 | 0)}%
          </div>
          <div style={{ fontSize: 13, lineHeight: 1.5, color: PALETTE.text }}>
            {final.summary}
          </div>
          {final.conflicts?.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 10, color: PALETTE.muted, fontWeight: 600 }}>CONFLICTS</div>
              {final.conflicts.map((c, i) => (
                <div key={i} style={{ fontSize: 11, color: PALETTE.text, lineHeight: 1.4 }}>
                  {c.pod_a} vs {c.pod_b} on {c.field}: "{c.claim_a}" / "{c.claim_b}" - {c.resolution}
                </div>
              ))}
            </div>
          )}
        </>
      )}
      {clar && clar.pending && (
        <ClarificationPrompt clar={clar} onAnswer={onAnswer} />
      )}
    </div>
  );
}

function ClarificationPrompt({ clar, onAnswer }) {
  const [answer, setAnswer] = useState("");
  return (
    <div style={{
      marginTop: 12, padding: 12,
      background: PALETTE.panelLight,
      border: `1px dashed ${PALETTE.gold}`,
      borderRadius: 6,
    }}>
      <div style={{ fontSize: 11, color: PALETTE.gold, fontWeight: 600, marginBottom: 6 }}>
        CLARIFICATION NEEDED
      </div>
      <div style={{ fontSize: 13, color: PALETTE.text, marginBottom: 10 }}>
        {clar.question}
      </div>
      {clar.options?.length > 0 && (
        <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
          {clar.options.map((o) => (
            <button
              key={o}
              onClick={() => onAnswer(o)}
              style={{
                background: PALETTE.bg,
                color: PALETTE.text,
                border: `1px solid ${PALETTE.border}`,
                padding: "6px 12px",
                fontSize: 12,
                borderRadius: 4,
                cursor: "pointer",
              }}
            >{o}</button>
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="type answer..."
          style={{
            flex: 1, padding: "6px 10px",
            background: PALETTE.bg,
            border: `1px solid ${PALETTE.border}`,
            color: PALETTE.text, fontSize: 12, borderRadius: 4,
          }}
        />
        <button
          onClick={() => answer && onAnswer(answer)}
          style={{
            background: PALETTE.gold, color: "#0F1318",
            border: "none", padding: "6px 14px",
            fontSize: 12, fontWeight: 600, borderRadius: 4, cursor: "pointer",
          }}
        >submit</button>
      </div>
    </div>
  );
}

function EventTimeline({ events }) {
  return (
    <div style={{
      background: PALETTE.panel,
      border: `1px solid ${PALETTE.border}`,
      borderRadius: 8,
      padding: 14,
      maxHeight: 400,
      overflowY: "auto",
      fontFamily: "'JetBrains Mono', monospace",
      fontSize: 11,
    }}>
      <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: 1.2, textTransform: "uppercase", color: PALETTE.muted, marginBottom: 8 }}>
        TIMELINE ({events.length})
      </div>
      {events.map((e, i) => (
        <div key={i} style={{ color: PALETTE.text, marginBottom: 4, lineHeight: 1.4 }}>
          <span style={{ color: PALETTE.gold }}>{e.type}</span>
          {e.pod && <span style={{ color: PALETTE.muted }}> [{e.pod}]</span>}
          {e.stage && <span style={{ color: PALETTE.muted }}> [{e.stage}]</span>}
          {e.type === "pod_verdict" && e.verdict?.verdict && (
            <span style={{ color: VERDICT_COLOR(e.verdict.verdict) }}>
              {" → " + e.verdict.verdict}
            </span>
          )}
          {e.type === "final_verdict" && e.result?.verdict && (
            <span style={{ color: VERDICT_COLOR(e.result.verdict) }}>
              {" → " + e.result.verdict}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

export default function CouncilDemo() {
  const [query, setQuery] = useState(
    "Can we colocate a 100MW DC at the Waltham Cross substation site?",
  );
  const [projectRid, setProjectRid] = useState("");
  const { events, state, start, clarify, creating } = useCouncilSession();

  const handleStart = () => {
    if (!query.trim() || creating) return;
    start({ query, project_rid: projectRid || null }).catch((e) => {
      console.error(e);
    });
  };

  return (
    <div style={{
      minHeight: "100vh",
      background: PALETTE.bg,
      color: PALETTE.text,
      fontFamily: "'Inter', 'DM Sans', sans-serif",
      padding: 32,
    }}>
      <div style={{ maxWidth: 1280, margin: "0 auto" }}>
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 11, color: PALETTE.gold, fontWeight: 700, letterSpacing: 2, textTransform: "uppercase" }}>
            PRINCEPS COUNCIL
          </div>
          <h1 style={{ fontSize: 24, fontWeight: 700, margin: "4px 0 0" }}>
            Three-pod adjudication
          </h1>
          <div style={{ fontSize: 12, color: PALETTE.muted, marginTop: 4 }}>
            GRID / BESS / DC pods run in parallel. Adjudicator detects conflicts and either ships a unified verdict or asks one specific question.
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. Can we site a 200MW DC at Waltham Cross?"
            style={{
              flex: 1, padding: "10px 14px",
              background: PALETTE.panel,
              border: `1px solid ${PALETTE.border}`,
              color: PALETTE.text, fontSize: 13, borderRadius: 6,
            }}
            onKeyDown={(e) => e.key === "Enter" && handleStart()}
          />
          <input
            value={projectRid}
            onChange={(e) => setProjectRid(e.target.value)}
            placeholder="project rid (optional)"
            style={{
              width: 220, padding: "10px 14px",
              background: PALETTE.panel,
              border: `1px solid ${PALETTE.border}`,
              color: PALETTE.text, fontSize: 12, borderRadius: 6,
            }}
          />
          <button
            onClick={handleStart}
            disabled={creating}
            style={{
              padding: "10px 22px",
              background: PALETTE.gold, color: "#0F1318",
              border: "none", borderRadius: 6,
              fontSize: 13, fontWeight: 700,
              cursor: creating ? "wait" : "pointer",
              opacity: creating ? 0.6 : 1,
            }}
          >
            {creating ? "..." : "convene"}
          </button>
        </div>

        <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
          <PodCard name="GRID" pod={state.pods?.grid} />
          <PodCard name="BESS" pod={state.pods?.bess} />
          <PodCard name="DC" pod={state.pods?.dc} />
        </div>

        <div style={{ marginBottom: 20 }}>
          <AdjudicatorPanel state={state} onAnswer={(a) => clarify(a).catch(console.error)} />
        </div>

        <EventTimeline events={events} />

        {state.session_rid && (
          <div style={{ marginTop: 16, fontSize: 11, color: PALETTE.muted, fontFamily: "monospace" }}>
            session: {state.session_rid}
          </div>
        )}
      </div>
    </div>
  );
}
