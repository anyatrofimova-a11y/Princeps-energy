import React, { useState } from "react";

const STATIC_ALERTS = [
  {
    title: "Ofgem: Connection charging reform consultation",
    source: "Ofgem",
    date: "2026-03-28",
    relevance: "High",
    impact: "Affects project IRR by -3% for new grid connections due to revised shallow/deep cost boundary.",
    description:
      "Ofgem has launched a consultation on reforming connection charging methodology. Proposals include changes to the shallow-deep boundary for transmission-connected generation, affecting connection cost allocation for projects above 50MW.",
  },
  {
    title: "NESO: TMO4+ queue reform implementation update",
    source: "NESO",
    date: "2026-03-25",
    relevance: "High",
    impact: "Queue position for 12 portfolio projects may be reclassified under new gate criteria.",
    description:
      "NESO has published updated implementation guidance for the TMO4+ queue reform. Projects without planning consent by Q3 2026 risk losing queue position. Milestone-based progression replaces first-come-first-served.",
  },
  {
    title: "EA: Updated flood risk guidance for energy projects",
    source: "EA",
    date: "2026-03-20",
    relevance: "Medium",
    impact: "Solar sites in Flood Zone 2 now require sequential test evidence, adding 8-12 weeks to planning.",
    description:
      "The Environment Agency has tightened flood risk assessment requirements for ground-mounted solar. Sequential and exception tests now mandatory for Flood Zone 2 sites, previously only required for Zone 3.",
  },
  {
    title: "DESNZ: NSIP threshold increase to 100MW confirmed",
    source: "DESNZ",
    date: "2026-03-15",
    relevance: "High",
    impact: "Projects 50-100MW can now use TCPA route, reducing consent timeline by 12-18 months.",
    description:
      "DESNZ has confirmed the increase of the NSIP threshold for onshore generation from 50MW to 100MW. Projects below 100MW will use the Town and Country Planning Act route via local planning authorities.",
  },
  {
    title: "Planning Inspectorate: Solar farm appeal decision (Kent)",
    source: "PINS",
    date: "2026-03-12",
    relevance: "Medium",
    impact: "Sets precedent for BMV land use — Grade 3b now explicitly acceptable for solar with ALC survey.",
    description:
      "PINS has allowed an appeal for a 40MW solar farm on Grade 3b agricultural land in Kent. The inspector accepted the ALC survey evidence and found the loss of BMV land was not significant given the reversible nature of solar development.",
  },
  {
    title: "Ofgem: DUoS tariff changes effective April 2026",
    source: "Ofgem",
    date: "2026-03-10",
    relevance: "Low",
    impact: "Marginal increase in operating costs (~0.2% of revenue) for distribution-connected assets.",
    description:
      "Annual DUoS tariff adjustments published by all DNOs. Average increase of 3.2% across all voltage levels. Largest increases in UKPN South Eastern region.",
  },
  {
    title: "NE: Updated BNG metric 4.0 guidance note",
    source: "Natural England",
    date: "2026-03-05",
    relevance: "Medium",
    impact: "BNG unit costs increase ~15% under the Statutory Biodiversity Metric (v1.0, July 2025 tooling update). Budget impact: +80-120k per typical 50MW solar site.",
    description:
      "Natural England has updated the Statutory Biodiversity Metric (v1.0) tooling (July 2025) with watercourse refinements and habitat condition clarifications. Baseline unit outputs unchanged; habitat values for improved grassland remain a key driver of BNG unit requirements for solar developments.",
  },
];

const RELEVANCE_CONFIG = {
  High: { color: "#dc2626", bg: "rgba(220,38,38,0.06)", label: "High Impact" },
  Medium: { color: "#f59e0b", bg: "rgba(245,158,11,0.06)", label: "Medium" },
  Low: { color: "#16a34a", bg: "rgba(22,163,74,0.06)", label: "Low" },
};

export default function RegulatoryFeed() {
  const [query, setQuery] = useState("");
  const [hoverIdx, setHoverIdx] = useState(null);
  const [expandedIdx, setExpandedIdx] = useState(null);

  const filtered = query.trim()
    ? STATIC_ALERTS.filter(
        (a) =>
          a.title.toLowerCase().includes(query.toLowerCase()) ||
          a.source.toLowerCase().includes(query.toLowerCase()) ||
          a.impact.toLowerCase().includes(query.toLowerCase())
      )
    : STATIC_ALERTS;

  return (
    <div>
      {/* Search */}
      <div style={{ padding: "14px 20px 10px" }}>
        <div style={{ position: "relative" }}>
          <svg
            width="14"
            height="14"
            viewBox="0 0 16 16"
            fill="none"
            stroke="var(--muted-light)"
            strokeWidth="1.5"
            strokeLinecap="round"
            style={{
              position: "absolute",
              left: 12,
              top: "50%",
              transform: "translateY(-50%)",
              pointerEvents: "none",
            }}
          >
            <circle cx="7" cy="7" r="5" />
            <path d="M11 11l3.5 3.5" />
          </svg>
          <input
            type="text"
            placeholder="Search UK energy regulations..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{
              width: "100%",
              padding: "8px 14px 8px 36px",
              fontSize: 13,
              fontFamily: "'DM Sans', sans-serif",
              border: "1px solid var(--border)",
              borderRadius: 10,
              outline: "none",
              background: "var(--cds-layer-02)",
              color: "var(--ink)",
              boxSizing: "border-box",
              transition: "border-color 0.15s, box-shadow 0.15s",
            }}
            onFocus={(e) => {
              e.target.style.borderColor = "var(--gold)";
              e.target.style.boxShadow = "0 0 0 2px rgba(245,183,49,0.1)";
            }}
            onBlur={(e) => {
              e.target.style.borderColor = "var(--border)";
              e.target.style.boxShadow = "none";
            }}
          />
        </div>
      </div>

      {/* List */}
      <div style={{ padding: "0 0 8px" }}>
        {filtered.map((item, i) => {
          const rel = RELEVANCE_CONFIG[item.relevance] || RELEVANCE_CONFIG.Low;
          const isExpanded = expandedIdx === i;
          const isHover = hoverIdx === i;

          return (
            <div
              key={i}
              style={{
                padding: "14px 20px",
                borderBottom: "1px solid var(--cds-layer-03, #EBEDF0)",
                background: isHover ? "rgba(245,183,49,0.02)" : "transparent",
                transition: "background 0.15s ease",
              }}
              onMouseEnter={() => setHoverIdx(i)}
              onMouseLeave={() => setHoverIdx(null)}
            >
              <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                {/* Priority dot */}
                <span
                  className={`pd3-risk-dot pd3-risk-dot-${item.relevance === "High" ? "high" : item.relevance === "Medium" ? "medium" : "low"}`}
                  style={{ marginTop: 5, flexShrink: 0 }}
                />

                <div style={{ flex: 1 }}>
                  <div style={{
                    fontSize: 13,
                    fontWeight: 600,
                    color: "var(--ink)",
                    lineHeight: 1.4,
                  }}>
                    {item.title}
                  </div>
                  <div style={{
                    fontSize: 11,
                    color: "var(--muted)",
                    marginTop: 2,
                  }}>
                    {item.source} &middot; {item.date}
                  </div>
                  <div style={{
                    fontSize: 12,
                    color: "var(--ink)",
                    marginTop: 6,
                    lineHeight: 1.5,
                  }}>
                    <span style={{
                      fontWeight: 700,
                      color: "var(--muted)",
                      fontSize: 10,
                      textTransform: "uppercase",
                      letterSpacing: "0.04em",
                    }}>
                      Impact:{" "}
                    </span>
                    {item.impact}
                  </div>

                  {isExpanded && (
                    <div style={{
                      fontSize: 12,
                      color: "var(--muted)",
                      marginTop: 8,
                      lineHeight: 1.5,
                      padding: "10px 14px",
                      background: "var(--cds-layer-02)",
                      borderRadius: 8,
                      borderLeft: "2px solid var(--border)",
                      animation: "pd-fade-up 0.2s ease",
                    }}>
                      {item.description}
                    </div>
                  )}

                  <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                    <button
                      onClick={() => setExpandedIdx(isExpanded ? null : i)}
                      style={{
                        fontSize: 11,
                        fontWeight: 500,
                        padding: "4px 12px",
                        borderRadius: 6,
                        border: "1px solid var(--border)",
                        background: isExpanded ? "var(--cds-layer-02)" : "var(--cds-layer-01)",
                        color: "var(--ink)",
                        cursor: "pointer",
                        transition: "all 0.15s",
                        fontFamily: "'DM Sans', sans-serif",
                      }}
                    >
                      {isExpanded ? "Hide Detail" : "Explain in 30s"}
                    </button>
                    <button
                      style={{
                        fontSize: 11,
                        fontWeight: 600,
                        padding: "4px 12px",
                        borderRadius: 6,
                        border: "1px solid rgba(245,183,49,0.25)",
                        background: "rgba(245,183,49,0.04)",
                        color: "var(--gold-dark)",
                        cursor: "pointer",
                        transition: "all 0.15s",
                        fontFamily: "'DM Sans', sans-serif",
                      }}
                    >
                      Apply to Portfolio
                    </button>
                  </div>
                </div>

                {/* Relevance tag */}
                <span style={{
                  fontSize: 10,
                  fontWeight: 700,
                  padding: "3px 10px",
                  borderRadius: 20,
                  background: rel.bg,
                  color: rel.color,
                  border: `1px solid ${rel.color}20`,
                  whiteSpace: "nowrap",
                  flexShrink: 0,
                  letterSpacing: "0.02em",
                }}>
                  {rel.label}
                </span>
              </div>
            </div>
          );
        })}
        {filtered.length === 0 && (
          <div style={{
            padding: 48,
            textAlign: "center",
            color: "var(--muted-light)",
            fontSize: 12,
          }}>
            No matching regulatory documents found.
          </div>
        )}
      </div>
    </div>
  );
}
