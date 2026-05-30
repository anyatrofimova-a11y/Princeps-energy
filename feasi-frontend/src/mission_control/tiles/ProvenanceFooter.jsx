import React from "react";

/**
 * ProvenanceFooter — small reusable footer for every Mission Control tile.
 *
 * New canonical form (Nyxium-style "every number cites its source"):
 *   <ProvenanceFooter source="NESO TEC Register · NGED LTDS" claudeDerived />
 * renders:
 *   Source: NESO TEC Register · NGED LTDS · Claude Opus 4.7
 *
 * Back-compat: still accepts the legacy `provenance={{ sources: [...] }}`
 * shape used by earlier tiles. If `provenance.sources` is supplied it wins;
 * otherwise we fall through to the explicit `source` prop.
 *
 * Style: very low contrast, 10.5px, top border in light grey — should be
 * ignorable when scanning, available when scrutinising. CSS lives in
 * mission-control-v2.css under `.mcv2-provenance`.
 */
function timeAgo(iso) {
  if (!iso) return null;
  try {
    const delta = Date.now() - new Date(iso).getTime();
    if (delta < 0 || Number.isNaN(delta)) return "just now";
    const s = Math.floor(delta / 1000);
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  } catch {
    return null;
  }
}

/**
 * WarmingState — polite placeholder when a tile's slice of the snapshot is
 * null/undefined or empty. Use INSIDE the tile body, above the provenance
 * footer, so the citation surface still renders.
 */
export function WarmingState({ label = "Awaiting data — connectors warming" }) {
  return (
    <div className="mcv2-warming" aria-live="polite">
      <span className="mcv2-warming-dot" />
      <span className="mcv2-warming-dot" />
      <span className="mcv2-warming-dot" />
      <span>{label}</span>
    </div>
  );
}

/**
 * TileSkeleton — first-paint shimmer; three thin bars of varying widths
 * approximating a typical list/sparkline layout.
 */
export function TileSkeleton({ rows = 3 }) {
  const widths = ["78%", "94%", "62%", "88%", "70%"];
  return (
    <div className="mcv2-skeleton-stack" aria-hidden="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="mcv2-skeleton"
          style={{ width: widths[i % widths.length], height: 12 }}
        />
      ))}
    </div>
  );
}

/**
 * fmtOrDash — never render a naked zero when the value is genuinely missing.
 * `0` is preserved when it's a real measurement; `null`/`undefined`/`NaN`
 * render as an em-dash.
 */
export function fmtOrDash(v, formatter = (x) => String(x)) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number" && !Number.isFinite(v)) return "—";
  return formatter(v);
}

export default function ProvenanceFooter({
  source,
  claudeDerived = false,
  generatedAt,
  // Legacy props (still honoured)
  provenance,
  fallbackSources = [],
}) {
  // Prefer legacy `provenance.sources` if the caller passed it.
  const legacySources = (provenance && provenance.sources) || fallbackSources;
  const legacyGeneratedAt = provenance && provenance.generated_at;
  const stamp = generatedAt || legacyGeneratedAt;

  let body;
  if (source) {
    body = claudeDerived ? `${source} · Claude Opus 4.7` : source;
  } else if (legacySources && legacySources.length) {
    const joined = legacySources.join(" · ");
    body = claudeDerived ? `${joined} · Claude Opus 4.7` : joined;
  } else {
    body = "source not recorded";
  }

  const ago = timeAgo(stamp);

  return (
    <div className="mcv2-provenance" role="contentinfo">
      <span className="mcv2-provenance-source">
        <span className="mcv2-provenance-label">Source:</span> {body}
      </span>
      {ago && <span className="mcv2-provenance-stamp">{ago}</span>}
    </div>
  );
}
