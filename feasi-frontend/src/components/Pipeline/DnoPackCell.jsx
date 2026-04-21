import React, { useEffect, useState } from "react";

/**
 * DnoPackCell — compact pipeline-column cell showing the DNO engagement
 * status for a single project.
 *
 * Usage: drop inline as a kanban column next to the verdict chip.
 *
 *   <DnoPackCell projectId={p.project_id} />
 *
 * States rendered:
 *   - none           → subtle "No pack" ghost chip
 *   - drafting       → "Draft v{n}" (amber)
 *   - previewing     → "Preview v{n}" (amber)
 *   - sent (<7d)     → "Sent — {n}d" (blue)
 *   - sent (7-14d)   → "Sent — {n}d" (blue, bold)
 *   - sent (>14d)    → "Sent — {n}d" (caution — nudge to follow up)
 *   - responded      → "Responded" (green) + sentiment dot if extracted
 *   - withdrawn/sup. → tertiary ghost chip
 *
 * Data source: GET /api/dno-engagement/project/{project_id}/history
 * (returns newest-first; we key off the first row).
 *
 * Resilient to backend being down — falls back to rendering nothing
 * rather than blowing up the pipeline board.
 */

const C = {
  ink: "#0F1318",
  secondary: "#4B5563",
  tertiary: "#9C9590",
  border: "#E8EAED",
  bg: "#F7F8FA",
  gold: "#F5B731",
  goldSoft: "#C9A64B",
  goldSurface: "rgba(245,183,49,0.10)",
  blue: "#1E5DA8",
  blueSurface: "#E8EFF9",
  go: "#2F7C46",
  goSurface: "#E7F4EB",
  caution: "#C07A1A",
  cautionSurface: "#FCF2E4",
  nogo: "#B23B3B",
};

function daysSince(iso) {
  if (!iso) return null;
  try {
    const ms = Date.now() - new Date(iso).getTime();
    return Math.max(0, Math.round(ms / 86400000));
  } catch {
    return null;
  }
}

function sentimentDot(sentiment) {
  const map = {
    positive:    C.go,
    conditional: C.caution,
    negative:    C.nogo,
    holding:     C.blue,
    silent:      C.tertiary,
  };
  const col = map[sentiment] || C.tertiary;
  return (
    <span
      title={sentiment || "unknown"}
      aria-hidden
      style={{
        display: "inline-block",
        width: 6, height: 6, borderRadius: 3,
        background: col, marginLeft: 6,
      }}
    />
  );
}

function chipStyle(bg, fg) {
  return {
    display: "inline-flex",
    alignItems: "center",
    padding: "2px 8px",
    borderRadius: 6,
    fontSize: 11,
    fontWeight: 600,
    background: bg,
    color: fg,
    letterSpacing: "-0.005em",
    whiteSpace: "nowrap",
    fontFamily: "'DM Sans', sans-serif",
  };
}

export default function DnoPackCell({ projectId }) {
  const [state, setState] = useState({ loading: true, latest: null });

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;

    (async () => {
      try {
        const r = await fetch(`/api/dno-engagement/project/${projectId}/history`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        if (cancelled) return;
        const latest = Array.isArray(data.engagements) && data.engagements.length
          ? data.engagements[0]
          : null;
        setState({ loading: false, latest });
      } catch {
        if (!cancelled) setState({ loading: false, latest: null });
      }
    })();

    return () => { cancelled = true; };
  }, [projectId]);

  if (state.loading) {
    return (
      <span style={chipStyle(C.bg, C.tertiary)} aria-label="Loading DNO pack">
        …
      </span>
    );
  }

  const latest = state.latest;
  if (!latest) {
    return (
      <span style={chipStyle(C.bg, C.tertiary)} title="No engagement pack yet">
        No pack
      </span>
    );
  }

  const { status, pack_version, sent_at, latest_response } = latest;
  const d = daysSince(sent_at);

  if (status === "drafting" || status === "previewing") {
    const label = status === "drafting" ? "Draft" : "Preview";
    return (
      <span style={chipStyle(C.goldSurface, C.ink)} title={`v${pack_version} · ${status}`}>
        {label} v{pack_version}
      </span>
    );
  }

  if (status === "sent") {
    const over14 = d != null && d > 14;
    const style = over14
      ? chipStyle(C.cautionSurface, C.caution)
      : chipStyle(C.blueSurface, C.blue);
    return (
      <span style={style} title={`Sent ${d ?? "?"} days ago · v${pack_version}`}>
        Sent · {d ?? "?"}d
      </span>
    );
  }

  if (status === "responded") {
    // If we have the sentiment on latest_response, drive the dot.
    // Our history endpoint stores sentiment inside structured_extract,
    // but the latest_response summary doesn't include it — just the
    // ack flag. The dot is optional; when absent we render without it.
    const sentiment = latest_response?.sentiment || null;
    return (
      <span style={chipStyle(C.goSurface, C.go)} title={`v${pack_version} responded`}>
        Responded
        {sentiment && sentimentDot(sentiment)}
      </span>
    );
  }

  // withdrawn / superseded / anything else
  return (
    <span style={chipStyle(C.bg, C.tertiary)} title={`v${pack_version} · ${status}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}
