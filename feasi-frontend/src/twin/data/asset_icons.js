/**
 * Shared icon atlas + status palette for twin asset-domain layers.
 *
 * We generate a small in-memory atlas from SVG strings so we don't need
 * to ship a PNG sprite at build time. Each icon is 64x64 with a 1px
 * drop-shadow so it reads against both light and dark basemaps.
 *
 * Palette matches Princeps gold theme and the status buckets emitted by
 * app/routers/twin_assets.py (operational / under_construction /
 * consented / application_submitted / refused / withdrawn /
 * decommissioned / pre_planning).
 */

// ── Status palette ─────────────────────────────────────────────────────────
export const STATUS_COLORS = {
  operational:            [76, 175, 80, 230],      // green
  under_construction:     [255, 165, 0, 230],      // amber
  consented:              [212, 160, 24, 220],     // light gold (Princeps)
  application_submitted:  [30, 136, 229, 210],     // blue
  refused:                [198, 40, 40, 200],      // dark red
  withdrawn:              [120, 120, 120, 170],    // dim grey
  decommissioned:         [80, 80, 80, 160],       // slate
  pre_planning:           [170, 170, 170, 180],    // mid grey
};

export function statusColor(bucket) {
  return STATUS_COLORS[bucket] || STATUS_COLORS.pre_planning;
}

export function statusLabel(bucket) {
  return {
    operational:           "Operational",
    under_construction:    "Under construction",
    consented:             "Consented",
    application_submitted: "In planning",
    refused:               "Refused",
    withdrawn:             "Withdrawn",
    decommissioned:        "Decommissioned",
    pre_planning:          "Pre-planning",
  }[bucket] || "Unknown";
}

// ── SVG icon definitions ───────────────────────────────────────────────────
const ICON_SVGS = {
  solar: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect x="8" y="20" width="48" height="28" fill="#D4A018" stroke="#222" stroke-width="1.5"/><line x1="20" y1="20" x2="20" y2="48" stroke="#222"/><line x1="32" y1="20" x2="32" y2="48" stroke="#222"/><line x1="44" y1="20" x2="44" y2="48" stroke="#222"/><line x1="8" y1="34" x2="56" y2="34" stroke="#222"/></svg>`,
  wind_onshore: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect x="30" y="28" width="4" height="28" fill="#ccc" stroke="#222"/><circle cx="32" cy="28" r="3" fill="#222"/><path d="M32 28 L 50 20 L 50 24 Z" fill="#eee" stroke="#222"/><path d="M32 28 L 18 14 L 22 14 Z" fill="#eee" stroke="#222"/><path d="M32 28 L 28 48 L 34 48 Z" fill="#eee" stroke="#222"/></svg>`,
  wind_offshore: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><path d="M0 48 Q16 44 32 48 T 64 48 L 64 64 L 0 64 Z" fill="#1e88e5" opacity="0.6"/><rect x="30" y="20" width="4" height="28" fill="#ccc" stroke="#222"/><circle cx="32" cy="20" r="3" fill="#222"/><path d="M32 20 L 50 12 L 50 16 Z" fill="#eee" stroke="#222"/><path d="M32 20 L 18 6 L 22 6 Z" fill="#eee" stroke="#222"/><path d="M32 20 L 28 40 L 34 40 Z" fill="#eee" stroke="#222"/></svg>`,
  bess: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect x="8" y="20" width="48" height="32" fill="#444" stroke="#222" stroke-width="1.5" rx="2"/><rect x="12" y="24" width="10" height="24" fill="#4caf50"/><rect x="24" y="24" width="10" height="24" fill="#4caf50"/><rect x="36" y="24" width="10" height="24" fill="#8bc34a"/><rect x="48" y="24" width="6" height="24" fill="#cddc39"/><path d="M14 16 L 20 16 L 16 12 Z" fill="#ffeb3b" stroke="#222"/></svg>`,
  dc: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect x="8" y="14" width="48" height="42" fill="#2c2c2c" stroke="#222" stroke-width="1.5"/><rect x="12" y="18" width="40" height="4" fill="#111"/><rect x="12" y="24" width="40" height="4" fill="#111"/><rect x="12" y="30" width="40" height="4" fill="#111"/><rect x="12" y="36" width="40" height="4" fill="#111"/><rect x="12" y="42" width="40" height="4" fill="#111"/><rect x="12" y="48" width="40" height="4" fill="#111"/><circle cx="48" cy="20" r="1.5" fill="#4caf50"/><circle cx="48" cy="26" r="1.5" fill="#4caf50"/><circle cx="48" cy="32" r="1.5" fill="#ffc107"/></svg>`,
  ev: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect x="22" y="10" width="20" height="44" fill="#333" stroke="#222" stroke-width="1.5" rx="2"/><rect x="26" y="16" width="12" height="10" fill="#4caf50"/><path d="M30 30 L 34 30 L 32 38 L 36 38 L 30 50 L 32 40 L 28 40 Z" fill="#ffeb3b" stroke="#222" stroke-width="0.6"/></svg>`,
  hydrogen: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="32" r="22" fill="#03a9f4" stroke="#222" stroke-width="1.5"/><text x="32" y="40" font-size="24" font-family="sans-serif" font-weight="bold" fill="#fff" text-anchor="middle">H₂</text></svg>`,
};

// ── Build data URLs (used by deck.gl IconLayer) ────────────────────────────
function svgToDataUrl(svg) {
  const encoded = encodeURIComponent(svg)
    .replace(/'/g, "%27")
    .replace(/"/g, "%22");
  return `data:image/svg+xml;charset=utf-8,${encoded}`;
}

export const ICON_URLS = Object.fromEntries(
  Object.entries(ICON_SVGS).map(([k, v]) => [k, svgToDataUrl(v)])
);

// Standard IconLayer atlas-mapping-free shape: each feature gets its own
// icon definition inline (url, width, height, anchorY).
export function iconDef(key) {
  return {
    url: ICON_URLS[key] || ICON_URLS.solar,
    width: 64,
    height: 64,
    anchorY: 32,
    mask: false,
  };
}

// ── Tooltip formatter ─────────────────────────────────────────────────────
export function formatTooltip({ object }) {
  if (!object) return null;
  const p = object.properties || {};
  const lines = [
    p.name ? `<b>${escapeHtml(p.name)}</b>` : null,
    p.technology ? escapeHtml(p.technology) : null,
    p.capacity_mw != null ? `${p.capacity_mw.toFixed(1)} MW` : null,
    p.it_load_mw != null ? `IT load ${p.it_load_mw.toFixed(1)} MW` : null,
    p.electrolyser_mw != null ? `Electrolyser ${p.electrolyser_mw.toFixed(1)} MW` : null,
    p.status || statusLabel(p.status_bucket),
    p.developer ? `<i>${escapeHtml(p.developer)}</i>` : null,
    p.county ? escapeHtml(p.county) : null,
  ].filter(Boolean);
  return {
    html: lines.join("<br/>"),
    style: {
      backgroundColor: "rgba(20,20,20,0.92)",
      color: "#f5f5f5",
      fontSize: "11px",
      padding: "6px 8px",
      borderRadius: "4px",
      border: "1px solid #D4A018",
    },
  };
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ── Capacity-to-size helper ───────────────────────────────────────────────
export function capacityToPixelSize(mw, { min = 14, max = 48, cap = 500 } = {}) {
  if (!mw || mw <= 0) return min;
  const n = Math.min(1, Math.sqrt(mw / cap));
  return Math.round(min + (max - min) * n);
}

// Bbox string from Mapbox/deck.gl viewport → "west,south,east,north"
export function bboxFromViewState(viewState) {
  if (!viewState) return null;
  const { longitude, latitude, zoom } = viewState;
  // Rough bbox from zoom level — fine for bbox-clipping DB queries at any zoom.
  const scale = 360 / Math.pow(2, zoom);
  const aspect = 1.4;
  return [
    longitude - scale * aspect,
    latitude - scale * 0.7,
    longitude + scale * aspect,
    latitude + scale * 0.7,
  ].join(",");
}
