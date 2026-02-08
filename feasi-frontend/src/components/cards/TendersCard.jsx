import React, { useState, useEffect } from "react";
import MetricCard from "../ui/MetricCard";
import api from "../../services/api";

export default function TendersCard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.tenders.energy().then(d => { setData(d); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  if (loading) return <MetricCard title="Energy Tenders" accentColor="#ff9800" headerValue="Loading..."><div className="dim">Fetching UK procurement data...</div></MetricCard>;
  if (!data || !data.tenders) return null;

  const { tenders, total_active, total_value_gbp, by_source } = data;
  const fmtVal = (v) => v >= 1e6 ? `£${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `£${(v / 1e3).toFixed(0)}K` : `£${v}`;

  return (
    <MetricCard
      title="Energy Tenders"
      accentColor="#ff9800"
      headerValue={`${total_active} active`}
      aiInsight={total_value_gbp ? `Total pipeline: ${fmtVal(total_value_gbp)}` : null}
      defaultOpen
    >
      <div style={{ fontSize: 11, color: "#aaa", marginBottom: 8 }}>
        {Object.entries(by_source || {}).map(([src, n]) => (
          <span key={src} style={{ marginRight: 10 }}>{src}: {n}</span>
        ))}
      </div>

      <div style={{ maxHeight: 400, overflowY: "auto" }}>
        {tenders.slice(0, 20).map((t, i) => {
          const isUrgent = t.deadline && daysDiff(t.deadline) <= 7;
          return (
            <div key={i} className="tender-item" style={{
              padding: "8px 10px", marginBottom: 6,
              background: "rgba(255,255,255,0.04)", borderRadius: 8,
              borderLeft: `3px solid ${isUrgent ? "#f44336" : "#ff9800"}`,
            }}>
              <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 3 }}>
                {t.title.length > 80 ? t.title.slice(0, 80) + "..." : t.title}
              </div>
              <div style={{ fontSize: 11, color: "#aaa", marginBottom: 4 }}>
                {t.buyer && <span>{t.buyer} · </span>}
                <span className="tender-source" style={{
                  background: sourceColor(t.source), color: "#fff",
                  padding: "1px 6px", borderRadius: 10, fontSize: 10,
                }}>{t.source}</span>
              </div>
              <div style={{ display: "flex", gap: 12, fontSize: 11, color: "#ccc" }}>
                {t.value_gbp && <span style={{ color: "#4caf50", fontWeight: 600 }}>{fmtVal(t.value_gbp)}</span>}
                {t.deadline && (
                  <span style={{ color: isUrgent ? "#f44336" : "#ff9800" }}>
                    {isUrgent ? "⚡ " : ""}Due: {t.deadline}
                    {isUrgent && ` (${daysDiff(t.deadline)}d)`}
                  </span>
                )}
                {t.url && <a href={t.url} target="_blank" rel="noreferrer" style={{ color: "#64b5f6", textDecoration: "none" }}>View →</a>}
              </div>
              {t.description && <div style={{ fontSize: 10, color: "#888", marginTop: 4 }}>{t.description.slice(0, 150)}</div>}
            </div>
          );
        })}
      </div>
    </MetricCard>
  );
}

function daysDiff(dateStr) {
  const d = new Date(dateStr);
  const now = new Date();
  return Math.ceil((d - now) / 86400000);
}

function sourceColor(src) {
  if (src === "Find a Tender") return "#1565c0";
  if (src === "Sell2Wales") return "#c62828";
  if (src === "Contracts Finder") return "#2e7d32";
  return "#666";
}
