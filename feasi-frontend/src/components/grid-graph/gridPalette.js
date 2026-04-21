/**
 * gridPalette.js — single source of truth for every colour used by the
 * Grid Graph view (map overlays, graph canvas, legend chips, tooltip
 * swatches, pipeline strip pills).
 *
 * HOW TO ADD A NEW COLOUR (read before editing):
 *   1. Prefer extending an existing named category — RAG, voltage class,
 *      asset type, DNO, status. A new one-off hex in a layer file is a
 *      smell; push the value back here and import it.
 *   2. Semantic colours are RGB tuples `[r,g,b]` (deck.gl friendly) and
 *      are converted to CSS via `rgbToCss(tuple)` where a string is needed.
 *   3. DNO + status colours are kept as CSS hex strings because they are
 *      used predominantly by plain React/DOM chips, not deck.gl layers.
 *   4. Thresholds (e.g. RAG cutoffs) live next to their colour map so
 *      callers can import one object and derive the colour deterministically.
 *   5. If BOT-GL (legend) / BOT-GO (overlays) / BOT-GA need a new category,
 *      add it here first, then import — never redeclare downstream.
 *
 * Owners: BOT-GC (palette), BOT-GO (overlays), BOT-GL (legend), BOT-GA (analysis).
 */

/* ─────────── RAG (headroom) ──────────────────────────────────────────
   `green_min` / `amber_min` are fractional utilisation headroom thresholds
   (headroom_mw / firm_capacity_mw). >=30% headroom = green, 10-30% = amber,
   <10% = red. Keep the RGB tuples deck.gl friendly.                    */
export const RAG_THRESHOLDS = Object.freeze({
  green_min: 0.30,
  amber_min: 0.10,
});

export const RAG_COLORS = Object.freeze({
  green: [70, 180, 130],
  amber: [220, 160, 60],
  red:   [210, 80, 80],
});

/** Classify a fractional headroom value into a RAG bucket key. */
export function ragBucket(fractionalHeadroom) {
  const x = Number(fractionalHeadroom) || 0;
  if (x >= RAG_THRESHOLDS.green_min) return "green";
  if (x >= RAG_THRESHOLDS.amber_min) return "amber";
  return "red";
}

/** Return the RGB tuple for a fractional headroom value. */
export function ragColor(fractionalHeadroom) {
  return RAG_COLORS[ragBucket(fractionalHeadroom)];
}

/* ─────────── Voltage class ───────────────────────────────────────────
   Seven canonical UK voltage buckets. Colour ramp runs hot (400 kV =
   orange-red) through yellow (distribution) to cool (11 kV = pale cyan)
   so a glance at the map tells you transmission vs distribution. Any
   non-canonical kV reading should be snapped before lookup.             */
export const VOLTAGE_BUCKETS = Object.freeze([400, 275, 132, 66, 33, 22, 11]);

export const VOLTAGE_COLORS = Object.freeze({
  400: [230, 90, 50],    // orange-red  — National Grid ET transmission
  275: [240, 140, 50],   // orange      — National Grid ET transmission
  132: [245, 200, 60],   // yellow      — DNO extra-high
  66:  [245, 225, 130],  // pale yellow — DNO high
  33:  [90, 180, 210],   // cyan        — DNO primary
  22:  [130, 200, 220],  // mid cyan    — DNO (Scotland)
  11:  [170, 220, 230],  // pale cyan   — DNO secondary
});

/** Snap an arbitrary kV reading to its nearest canonical bucket. */
export function snapVoltage(v) {
  const x = Number(v) || 0;
  return VOLTAGE_BUCKETS.reduce((p, c) =>
    Math.abs(c - x) < Math.abs(p - x) ? c : p
  );
}

/** Lookup a voltage colour with a safe neutral fallback. */
export function getVoltageColor(kv) {
  const snap = snapVoltage(kv);
  return VOLTAGE_COLORS[snap] || [148, 163, 184]; // slate-400 fallback
}

/* ─────────── Asset type markers ──────────────────────────────────────
   Marker SHAPE carries the asset category (deck.gl IconLayer + SVG
   glyphs downstream); ASSET_COLORS carries the status-derived tint
   for REPD rows (so a consented site is amber regardless of shape).    */
export const ASSET_MARKERS = Object.freeze({
  substation:        "circle",
  tec_queue:         "triangle",
  repd_operational:  "square",
  repd_consented:    "square",
  repd_application:  "square",
});

export const ASSET_COLORS = Object.freeze({
  substation:        [201, 166, 75],  // --gold (neutral / primary asset)
  tec_queue:         [124, 58, 237],  // purple (queued, not yet energised)
  repd_operational:  [22, 163, 74],   // green
  repd_consented:    [217, 119, 6],   // amber
  repd_application:  [156, 163, 175], // grey — still in planning
});

/* ─────────── DNO brand colours ───────────────────────────────────────
   Six regional DNOs. Reconciled with the legacy `DNO_COLOURS` constant
   previously inlined in GridGraphContainer.jsx. Existing palette kept
   intact — only the SOURCE is now centralised.                         */
export const DNO_COLORS = Object.freeze({
  UKPN: "#3b82f6", // blue
  NGED: "#10b981", // emerald
  SSEN: "#a855f7", // purple
  SPEN: "#f59e0b", // amber
  ENWL: "#06b6d4", // cyan
  NPG:  "#ef4444", // red
});

/** Lookup DNO colour with neutral fallback. */
export function getDnoColor(dno) {
  return DNO_COLORS[dno] || "#94a3b8";
}

/* ─────────── Pipeline status pills ───────────────────────────────────
   Canonical lifecycle states used by the top-right pipeline strip AND
   the map pipeline overlay. Keeps map pins and strip pills in visual
   agreement. Synonyms from other surfaces (operational ≈ energised,
   in_progress ≈ construction) map here by adapter, not by duplication. */
export const STATUS_COLORS = Object.freeze({
  prospect:     "#9CA3AF",  // slate-400 — pre-planning, speculative
  planning:     "#3b82f6",  // blue-500  — application submitted / consented
  construction: "#d97706",  // amber-600 — pre-energisation build
  energised:    "#16a34a",  // green-600 — operating
});

/* ─────────── Utility ─────────────────────────────────────────────────
   Convert a deck.gl RGB tuple to a CSS `rgb(...)` string. Alpha optional. */
export function rgbToCss(tuple, alpha) {
  if (!tuple || tuple.length < 3) return "rgb(148,163,184)";
  const [r, g, b] = tuple;
  return alpha == null
    ? `rgb(${r},${g},${b})`
    : `rgba(${r},${g},${b},${alpha})`;
}
