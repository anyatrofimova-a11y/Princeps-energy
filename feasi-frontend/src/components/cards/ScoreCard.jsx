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
        <span className="muted">Select a site to see scores</span>
      </MetricCard>
    );
  }

  const score = explain.score_total ?? explain.score?.total ?? 0;
  const components = explain.context?.score_components || explain.score_components || {};

  return (
    <MetricCard
      title="Score"
      accentColor="#4caf50"
      headerValue={score ? `${score}/120` : "—"}
      aiInsight={insight}
    >
      <div className="score-row">
        {score > 0 && <span style={badgeStyle(score)}>{score}/120</span>}
        {Object.entries(components).map(([k, v]) => (
          <span key={k} className="score-chip">{k}: {v}</span>
        ))}
      </div>
      {explain.explanation && <pre className="overlay-pre">{explain.explanation}</pre>}
      {explain.location_name && <div className="stat-inline" style={{ marginTop: 4, fontSize: 11, color: "#888" }}>{explain.location_name}</div>}
    </MetricCard>
  );
}
