import React from "react";
import { useSite } from "../../SiteContext";
import MetricCard from "../ui/MetricCard";

export default function PlanningCard() {
  const { planningApps } = useSite();

  if (!planningApps) {
    return (
      <MetricCard title="Planning" accentColor="#e91e63">
        <span className="muted">Click Analyse</span>
      </MetricCard>
    );
  }

  return (
    <MetricCard
      title="Planning"
      accentColor="#e91e63"
      headerValue={`${planningApps.total_applications} apps`}
    >
      <div className="stat-grid">
        <div>Total: <strong>{planningApps.total_applications}</strong> apps</div>
        <div>Capacity: <strong>{planningApps.total_capacity_mw?.toLocaleString()} MW</strong></div>
      </div>
      {planningApps.by_category && (
        <>
          <div className="section-label">By Category</div>
          <div className="planning-cats">
            {Object.entries(planningApps.by_category).map(([cat, count]) => (
              <div key={cat} className="planning-cat-item">
                <span className="planning-cat-name">{cat.replace(/_/g, " ")}</span>
                <span className="planning-cat-count">{count}</span>
              </div>
            ))}
          </div>
        </>
      )}
      {planningApps.by_decision && (
        <>
          <div className="section-label">By Decision</div>
          <div className="planning-cats">
            {Object.entries(planningApps.by_decision).map(([dec, count]) => (
              <div key={dec} className="planning-cat-item">
                <span className="planning-cat-name">{dec}</span>
                <span className="planning-cat-count" style={{
                  background: dec === "Granted" ? "#4caf50" : dec === "Refused" ? "#f44336" : "#ff9800"
                }}>{count}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </MetricCard>
  );
}
