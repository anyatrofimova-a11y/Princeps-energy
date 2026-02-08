import React from "react";
import { useSite } from "../../SiteContext";
import MetricCard from "../ui/MetricCard";

function badgeStyle(score) {
  const pct = score / 120;
  const bg = pct > 0.7 ? "#4caf50" : pct > 0.4 ? "#ff9800" : "#f44336";
  return {
    display: "inline-block", padding: "2px 10px", borderRadius: 12,
    background: bg, color: "#fff", fontWeight: "bold", fontSize: 15,
  };
}

export default function ScoreCard() {
  const { explain, agentResult } = useSite();

  const insight = agentResult?.risks?.[0] || agentResult?.opportunities?.[0] || null;

  if (!explain) {
    return (
      <MetricCard title="Score" accentColor="#4caf50">
        <span className="muted">Click Analyse</span>
      </MetricCard>
    );
  }

  return (
    <MetricCard
      title="Score"
      accentColor="#4caf50"
      headerValue={`${explain.score_total}/120`}
      aiInsight={insight}
    >
      <div className="score-row">
        <span style={badgeStyle(explain.score_total)}>{explain.score_total}/120</span>
        {explain.context?.score_components && Object.entries(explain.context.score_components).map(([k, v]) => (
          <span key={k} className="score-chip">{k}: {v}</span>
        ))}
      </div>
      <pre className="overlay-pre">{explain.explanation}</pre>
    </MetricCard>
  );
}
