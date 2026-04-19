import React from "react";

export const WORKLOADS = {
  SOLAR: "solar",
  BESS: "bess",
  DC: "dc",
  WIND: "wind",
  HYBRID: "hybrid",
};

export const WORKLOAD_LABELS = {
  solar: "Solar",
  bess: "BESS",
  dc: "Data centre",
  wind: "Wind",
  hybrid: "Hybrid",
};

export const WORKLOAD_ICONS = {
  solar: "☀",
  bess: "🔋",
  dc: "🏢",
  wind: "🌬",
  hybrid: "⚡",
};

// Returns true if workload matches one of the allowed list (or "all")
export function matchesWorkload(workloadType, allowed) {
  if (!allowed || allowed === "all" || (Array.isArray(allowed) && allowed.includes("all"))) return true;
  if (typeof allowed === "string") return workloadType === allowed;
  if (Array.isArray(allowed)) return allowed.includes(workloadType);
  return false;
}

// Pretty label/icon getters
export function workloadLabel(type) {
  return WORKLOAD_LABELS[type] || "Unknown";
}

export function workloadIcon(type) {
  return WORKLOAD_ICONS[type] || "•";
}

// Renders children only when project.workload_type matches `only` (and not `except`)
export function WhenWorkload({ project, only, except, children }) {
  const wl = project?.workload_type;
  if (except && matchesWorkload(wl, except)) return null;
  if (!only) return children;
  return matchesWorkload(wl, only) ? children : null;
}

// Pill-style badge showing icon + label
export function WorkloadBadge({ workloadType, size = "md" }) {
  const lbl = workloadLabel(workloadType);
  const icon = workloadIcon(workloadType);
  const fontSize = size === "sm" ? 11 : size === "lg" ? 16 : 13;
  const padding = size === "sm" ? "1px 6px" : size === "lg" ? "4px 10px" : "2px 8px";
  const style = {
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
    fontSize,
    lineHeight: 1.4,
    padding,
    borderRadius: 12,
    background: "var(--cds-layer-01)",
    border: "1px solid var(--cds-border-subtle)",
    color: "var(--cds-text-primary)",
    whiteSpace: "nowrap",
    fontWeight: 500,
  };
  return (
    <span className="wl-badge" style={style}>
      <span aria-hidden="true">{icon}</span>
      <span>{lbl}</span>
    </span>
  );
}
