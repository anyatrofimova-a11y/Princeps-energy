import React, { useState, useMemo } from "react";
import { COLOURS, SANS, MONO, STAGE_ORDER, formatDate } from "./tokens";

// Grouped accordion by procedural stage. Filter bar at top (query + author).
export default function DocumentList({ documents = [], filterByStakeholderName }) {
  const [q, setQ] = useState("");
  const [author, setAuthor] = useState("");
  const [openStages, setOpenStages] = useState(() =>
    STAGE_ORDER.reduce((acc, s) => ({ ...acc, [s]: true }), {})
  );

  const authors = useMemo(() => Array.from(new Set(documents.map((d) => d.author).filter(Boolean))), [documents]);

  const filtered = useMemo(() => {
    let rows = documents;
    if (q) {
      const needle = q.toLowerCase();
      rows = rows.filter((d) => d.title.toLowerCase().includes(needle));
    }
    if (author) rows = rows.filter((d) => d.author === author);
    if (filterByStakeholderName) {
      rows = rows.filter((d) => d.author === filterByStakeholderName);
    }
    return rows;
  }, [documents, q, author, filterByStakeholderName]);

  const byStage = useMemo(() => {
    const m = {};
    for (const d of filtered) {
      const key = d.stage || "Other";
      if (!m[key]) m[key] = [];
      m[key].push(d);
    }
    return m;
  }, [filtered]);

  const presentStages = STAGE_ORDER.filter((s) => byStage[s]);
  const otherStages = Object.keys(byStage).filter((s) => !STAGE_ORDER.includes(s));

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
          Documents <span style={{ color: COLOURS.muted, fontWeight: 500 }}>({filtered.length})</span>
        </h3>
        {filterByStakeholderName && (
          <div style={{ fontSize: 11, color: COLOURS.muted }}>
            Filtered by <strong style={{ color: COLOURS.ink }}>{filterByStakeholderName}</strong>
          </div>
        )}
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search titles…"
          style={{
            flex: 1,
            padding: "6px 10px",
            border: `1px solid ${COLOURS.border}`,
            borderRadius: 4,
            fontSize: 12.5,
            fontFamily: SANS,
            outline: "none",
          }}
        />
        <select
          value={author}
          onChange={(e) => setAuthor(e.target.value)}
          style={{
            padding: "6px 10px",
            border: `1px solid ${COLOURS.border}`,
            borderRadius: 4,
            fontSize: 12.5,
            fontFamily: SANS,
            background: "#FFFFFF",
            minWidth: 180,
          }}
        >
          <option value="">All authors</option>
          {authors.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
      </div>

      {[...presentStages, ...otherStages].map((stage) => (
        <div key={stage} style={{ marginBottom: 8, border: `1px solid ${COLOURS.border}`, borderRadius: 6, overflow: "hidden" }}>
          <button
            onClick={() => setOpenStages({ ...openStages, [stage]: !openStages[stage] })}
            style={{
              width: "100%",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "8px 12px",
              background: COLOURS.ivory,
              border: "none",
              cursor: "pointer",
              fontFamily: SANS,
              fontSize: 12,
              fontWeight: 700,
              color: COLOURS.ink,
              textTransform: "uppercase",
              letterSpacing: 0.4,
            }}
          >
            <span>{stage} <span style={{ color: COLOURS.muted, fontWeight: 500, marginLeft: 4 }}>({byStage[stage].length})</span></span>
            <span style={{ color: COLOURS.muted, fontSize: 10 }}>{openStages[stage] ? "−" : "+"}</span>
          </button>
          {openStages[stage] && (
            <div>
              {byStage[stage].map((d) => (
                <DocRow key={d.id} doc={d} />
              ))}
            </div>
          )}
        </div>
      ))}
    </section>
  );
}

function DocRow({ doc }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "8px 12px",
        borderTop: `1px solid ${COLOURS.border}`,
        background: "#FFFFFF",
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: COLOURS.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {doc.title}
        </div>
        <div style={{ fontSize: 11, color: COLOURS.muted, marginTop: 1 }}>
          {doc.author || "—"}
        </div>
      </div>
      <span style={{ fontFamily: MONO, fontSize: 11, color: COLOURS.muted, flexShrink: 0 }}>{formatDate(doc.date)}</span>
      <span style={{ fontFamily: MONO, fontSize: 11, color: COLOURS.muted, width: 48, textAlign: "right", flexShrink: 0 }}>
        {doc.pages != null ? `${doc.pages}p` : "—"}
      </span>
      <button
        style={{
          padding: "3px 8px",
          fontSize: 11,
          border: `1px solid ${COLOURS.border}`,
          background: "#FFFFFF",
          color: COLOURS.inkSoft,
          borderRadius: 4,
          cursor: "pointer",
          fontFamily: SANS,
          flexShrink: 0,
        }}
      >
        Open
      </button>
    </div>
  );
}
