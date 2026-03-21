import React from "react";

const VARIANTS = {
  green:  { bg: "rgba(36, 161, 72, 0.15)", color: "#24a148", border: "rgba(36, 161, 72, 0.3)" },
  red:    { bg: "rgba(218, 30, 40, 0.15)", color: "#da1e28", border: "rgba(218, 30, 40, 0.3)" },
  amber:  { bg: "rgba(241, 194, 27, 0.15)", color: "#f1c21b", border: "rgba(241, 194, 27, 0.3)" },
  blue:   { bg: "rgba(212, 160, 24, 0.15)", color: "#D4A018", border: "rgba(212, 160, 24, 0.3)" },
  grey:   { bg: "rgba(141, 141, 141, 0.15)", color: "#8d8d8d", border: "rgba(141, 141, 141, 0.3)" },
};

// Map RAG / status strings to variants
function resolveVariant(status) {
  if (!status) return "grey";
  const s = status.toLowerCase();
  if (s === "green" || s === "go" || s === "published" || s === "available") return "green";
  if (s === "red" || s === "no-go" || s === "constrained" || s === "no capacity") return "red";
  if (s === "amber" || s === "caution" || s === "in review" || s === "limited") return "amber";
  if (s === "blue" || s === "validated" || s === "active") return "blue";
  return "grey";
}

export default function StatusBadge({ status, label, size = "sm" }) {
  const variant = resolveVariant(status);
  const v = VARIANTS[variant];
  const text = label || status || "Unknown";

  return (
    <span
      className={`status-badge status-badge--${size}`}
      style={{
        background: v.bg,
        color: v.color,
        border: `1px solid ${v.border}`,
      }}
    >
      <span className="status-badge__dot" style={{ background: v.color }} />
      {text}
    </span>
  );
}

export function RagDot({ rag, size = 6 }) {
  const variant = resolveVariant(rag);
  const v = VARIANTS[variant];
  return (
    <span
      className="rag-dot"
      style={{ width: size, height: size, background: v.color, borderRadius: "50%", display: "inline-block", flexShrink: 0 }}
      title={rag}
    />
  );
}
