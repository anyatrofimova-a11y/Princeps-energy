import React, { useEffect } from "react";
import { useSite } from "../SiteContext";

const INTENTS = [
  { value: "feasibility", label: "Feasibility" },
  { value: "grid_study", label: "Grid" },
  { value: "financial", label: "Financial" },
  { value: "environmental", label: "Environmental" },
  { value: "planning", label: "Planning" },
];

function verdictClass(v) {
  if (v === "GO") return "verdict-go";
  if (v === "CAUTION") return "verdict-caution";
  return "verdict-nogo";
}

export default function AgentVerdict() {
  const { parcelId, agentResult, agentLoading, runAgent, samCapacity, samDay, selectTab } = useSite();

  // Auto-run agent when parcelId is set and no result yet
  useEffect(() => {
    if (parcelId && !agentResult && !agentLoading) {
      runAgent(parcelId, "feasibility", samCapacity, samDay);
    }
  }, [parcelId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!parcelId) return null;

  if (agentLoading && !agentResult) {
    return (
      <div className="verdict-hero">
        <div className="verdict-loading">
          <div className="verdict-spinner" />
          Analysing site feasibility...
        </div>
      </div>
    );
  }

  if (!agentResult) return null;

  return (
    <div className="verdict-hero">
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span className={`verdict-badge ${verdictClass(agentResult.verdict)}`}>
          {agentResult.verdict}
        </span>
        <span style={{ fontSize: 12, color: "var(--text-dim)" }}>
          {Math.round((agentResult.confidence || 0) * 100)}% confidence
        </span>
        {agentLoading && <div className="verdict-spinner" />}
      </div>
      <div className="verdict-summary">{agentResult.summary}</div>
      <div className="verdict-intents">
        {INTENTS.map(i => (
          <button
            key={i.value}
            className={`verdict-intent-chip ${agentResult.intent === i.value ? "active" : ""}`}
            onClick={() => {
              if (agentResult.intent !== i.value) {
                runAgent(parcelId, i.value, samCapacity, samDay);
              }
            }}
          >
            {i.label}
          </button>
        ))}
        <button
          className="verdict-intent-chip"
          onClick={() => selectTab("agent")}
          style={{ marginLeft: "auto" }}
        >
          Details
        </button>
      </div>
    </div>
  );
}
