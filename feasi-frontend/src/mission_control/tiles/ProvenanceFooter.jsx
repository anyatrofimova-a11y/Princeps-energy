import React from "react";

/**
 * ProvenanceFooter — small reusable footer for every Mission Control tile.
 *
 * Renders "PROVENANCE: source1 · source2 · regenerated Xs ago" in 10px
 * uppercase letter-spaced JetBrains Mono, matching the Foundry-pattern
 * "every tile is auditable" surface — but in Princeps gold-on-cream.
 */
function timeAgo(iso) {
  if (!iso) return "—";
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
    return "—";
  }
}

export default function ProvenanceFooter({ provenance, fallbackSources = [] }) {
  const sources = (provenance && provenance.sources) || fallbackSources;
  const generatedAt = provenance && provenance.generated_at;
  const text = (sources && sources.length)
    ? sources.join(" · ")
    : "no source recorded";
  return (
    <div className="mcv2-provenance">
      <span>
        <span className="mcv2-provenance-label">PROVENANCE</span>
        {text}
      </span>
      <span>regenerated {timeAgo(generatedAt)}</span>
    </div>
  );
}
