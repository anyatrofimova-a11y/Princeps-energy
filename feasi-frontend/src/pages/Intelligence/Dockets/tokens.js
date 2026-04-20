// Shared design tokens for the Dockets tab. Matches the Princeps
// design system (gold/ivory/ink + DM Sans/JetBrains Mono) but adds the
// docket-specific case-type and position-badge palettes from the brief.

export const COLOURS = {
  gold: "#F5B731",
  goldDeep: "#C8951E",
  ivory: "#FBF8F2",
  ink: "#0F1318",
  inkSoft: "#4B5563",
  muted: "#6B7280",
  mutedLight: "#9CA3AF",
  border: "#E8E5DF",
  card: "#FFFFFF",
  bg: "#F7F8FA",
  forGreen: "#3B8A5A",
  againstRed: "#B84A4A",
  conditionsAmber: "#E89A2A",
  neutralInk: "#0F1318",
  silentGrey: "#9CA3AF",
};

export const MONO = `"JetBrains Mono", "SF Mono", "Fira Code", monospace`;
export const SANS = `"DM Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`;

// ── Case-type chips — border + fill per the brief ──────────────
export const CASE_TYPE_CHIP = {
  NSIP_DCO:         { label: "NSIP DCO",      bg: "#C8951E",               fg: "#FFFFFF", border: "#C8951E" },
  LPA_PLANNING:     { label: "LPA",           bg: COLOURS.ivory,           fg: COLOURS.ink, border: COLOURS.gold },
  OFGEM_CODE_MOD:   { label: "Ofgem mod",     bg: "rgba(107,122,143,.12)", fg: "#6B7A8F", border: "#6B7A8F" },
  NESO:             { label: "NESO",          bg: "rgba(47,143,135,.12)",  fg: "#2F8F87", border: "#2F8F87" },
  APPEAL:           { label: "Appeal",        bg: "rgba(232,154,42,.12)",  fg: "#E89A2A", border: "#E89A2A" },
  CMA:              { label: "CMA",           bg: "rgba(184,74,74,.10)",   fg: "#B84A4A", border: "#B84A4A" },
  AR_ROUND:         { label: "AR round",      bg: "rgba(47,143,135,.12)",  fg: "#2F8F87", border: "#2F8F87" },
  CAPACITY_MARKET:  { label: "Cap Market",    bg: "rgba(47,143,135,.12)",  fg: "#2F8F87", border: "#2F8F87" },
};

export const POSITION_BADGE = {
  for:        { label: "For",        fg: "#FFFFFF", bg: "#3B8A5A" },
  against:    { label: "Against",    fg: "#FFFFFF", bg: "#B84A4A" },
  conditions: { label: "Conditions", fg: "#FFFFFF", bg: "#E89A2A" },
  neutral:    { label: "Neutral",    fg: "#FFFFFF", bg: "#0F1318" },
  silent:     { label: "Silent",     fg: "#FFFFFF", bg: "#9CA3AF" },
};

export const STATUS_PILL = {
  open:          { label: "Open",          fg: "#8A6514", bg: "rgba(245,183,49,.18)" },
  closed:        { label: "Closed",        fg: "#4B5563", bg: "rgba(107,114,128,.14)" },
  decided:       { label: "Decided",       fg: "#1F6A3F", bg: "rgba(59,138,90,.18)" },
  withdrawn:     { label: "Withdrawn",     fg: "#6B7280", bg: "rgba(107,114,128,.14)" },
  determination: { label: "Determination", fg: "#8A6514", bg: "rgba(245,183,49,.18)" },
};

export const ROLE_RINGS = [
  "applicant",
  "statutory",
  "dno_to",
  "lpa",
  "regulator",
  "objector",
  "supporter",
  "political",
];

export const ROLE_LABEL = {
  applicant: "Applicant",
  statutory: "Statutory",
  dno_to:    "DNO / TO",
  lpa:       "Local authority",
  regulator: "Regulator",
  objector:  "Objector",
  supporter: "Supporter",
  political: "Political",
};

// Approximate countdown-chip styling.
export function countdownStyle(daysLeft) {
  if (daysLeft == null) return { bg: "transparent", fg: COLOURS.muted, border: COLOURS.border };
  if (daysLeft <= 3) {
    return {
      bg: "#B84A4A", fg: "#FFFFFF", border: "#B84A4A",
      boxShadow: "0 0 0 2px rgba(184,74,74,.25)", animation: "princeps-pulse 1.4s ease-in-out infinite",
    };
  }
  if (daysLeft <= 14) {
    return { bg: "#E89A2A", fg: "#FFFFFF", border: "#E89A2A" };
  }
  return { bg: "transparent", fg: "#1F6A3F", border: "#3B8A5A" };
}

export const STAGE_ORDER = [
  "Pre-app",
  "Acceptance",
  "Pre-examination",
  "Examination",
  "Recommendation",
  "Determination",
  "Decision",
  "Challenge",
  "Post-consent",
  "Consultation",
  "Application",
  "Prequalification",
];

export function formatDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  } catch {
    return iso;
  }
}

export function daysFromNow(iso) {
  if (!iso) return null;
  const now = new Date();
  const then = new Date(iso);
  return Math.round((then - now) / (1000 * 60 * 60 * 24));
}
