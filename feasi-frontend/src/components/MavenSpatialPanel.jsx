/**
 * MavenSpatialPanel — natural-language redesign loop for the DC Twin.
 *
 * A persistent chat rail anchored to the bottom of DCDesignTwin. Accepts
 * prompts like:
 *
 *   "move 200 m east"           → nudges the DC centroid
 *   "set IT load to 100 MW"     → updates capacity
 *   "swap to 2N"                → redundancy change
 *   "tier 4"                    → tier change
 *   "snap to nearest 132 kV"    → picks nearest ≥132 kV substation
 *   "what's here?"              → summarises current design
 *   "find nearest 275 kV"       → lists nearby 275 kV subs
 *
 * A local deterministic parser handles the common ops instantly with zero
 * LLM cost. Anything the parser can't match falls through to the Princeps
 * chat endpoint as an open-ended question — but the user gets a clear tag
 * showing which path answered.
 *
 * Actions are applied optimistically with an Undo chip. No Accept/Reject
 * ghosting at v1; the map already recomputes < 100 ms so the "ghost" and
 * "applied" states are visually indistinguishable.
 */
import React, { useState, useCallback, useRef, useEffect } from "react";

const M_PER_DEG_LAT = 111_320;
const mPerDegLon = (lat) => M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180);

const EXAMPLES = [
  "move 500m east",
  "set load to 100 MW",
  "swap to 2N",
  "tier 4",
  "snap to nearest 132 kV",
  "what's here?",
];

/** Parse a natural-language command into a structured action.
 *  Returns { action: "move" | "set_load" | ... , params, rationale } or null. */
function parseCommand(text, ctx) {
  if (!text) return null;
  const t = text.trim().toLowerCase();

  // ── move / nudge ──
  // "move 200m east", "nudge 500 m south", "go 1 km north"
  const moveMatch = t.match(/(?:move|nudge|go|shift)\s+(\d+(?:\.\d+)?)\s*(m|km|metres?|meters?|kilometres?|kilometers?)?\s*(north|south|east|west|n|s|e|w|ne|nw|se|sw)/);
  if (moveMatch) {
    let dist = Number(moveMatch[1]);
    const unit = (moveMatch[2] || "m").toLowerCase();
    if (unit.startsWith("k")) dist *= 1000;
    const dir = moveMatch[3];
    const dirs = {
      n: [0, 1], s: [0, -1], e: [1, 0], w: [-1, 0],
      ne: [0.707, 0.707], nw: [-0.707, 0.707], se: [0.707, -0.707], sw: [-0.707, -0.707],
      north: [0, 1], south: [0, -1], east: [1, 0], west: [-1, 0],
    };
    const [dx, dy] = dirs[dir];
    return {
      action: "move",
      params: { dx_m: dx * dist, dy_m: dy * dist },
      rationale: `Shift ${Math.round(dist)} m ${dir}`,
    };
  }

  // ── set IT load / capacity ──
  // "set load to 100 MW", "change capacity to 75 MW", "100 MW please"
  const loadMatch = t.match(/(?:set|change|make)?\s*(?:it\s+)?(?:load|capacity|mw)[^\d]*?(\d+(?:\.\d+)?)\s*mw/)
                 || t.match(/(\d+(?:\.\d+)?)\s*mw(?:\s+(?:load|capacity|it))?/);
  if (loadMatch) {
    const mw = Number(loadMatch[1]);
    if (mw > 0 && mw < 2000) {
      return { action: "set_load", params: { it_load_mw: mw }, rationale: `IT load → ${mw} MW` };
    }
  }

  // ── redundancy ──
  const redMatch = t.match(/\b(2n\+1|2n|n\+1|n)\b/);
  if (redMatch && (/redund|tier|swap|set|change|use|make/.test(t) || /^(2n\+1|2n|n\+1|n)$/.test(t.trim()))) {
    const r = redMatch[1].toUpperCase();
    return { action: "set_redundancy", params: { redundancy: r }, rationale: `Redundancy → ${r}` };
  }

  // ── tier ──
  const tierMatch = t.match(/\btier\s*([1-4])\b/)
                 || t.match(/\bt([1-4])\b/);
  if (tierMatch) {
    return { action: "set_tier", params: { tier: Number(tierMatch[1]) }, rationale: `Tier → ${tierMatch[1]}` };
  }

  // ── cooling ──
  if (/cool|chill|hvac/.test(t)) {
    if (/free|dry|air/.test(t))   return { action: "set_cooling", params: { cooling_type: "free_cooling" }, rationale: "Cooling → free air" };
    if (/evap|swamp/.test(t))     return { action: "set_cooling", params: { cooling_type: "evaporative" }, rationale: "Cooling → evaporative" };
    if (/liquid|immers/.test(t))  return { action: "set_cooling", params: { cooling_type: "mechanical" }, rationale: "Cooling → liquid / mechanical" };
    if (/hybrid|mixed/.test(t))   return { action: "set_cooling", params: { cooling_type: "hybrid" }, rationale: "Cooling → hybrid" };
  }

  // ── snap to nearest / find nearest ──
  const snapMatch = t.match(/(snap|go\s+to|move\s+to)[^\d]*?(?:(\d{2,3})\s*kv)?/);
  if (snapMatch && /substation|sub/.test(t)) {
    const kv = snapMatch[2] ? Number(snapMatch[2]) : null;
    return {
      action: "snap_to_sub",
      params: { min_kv: kv, filter: kv ? `≥ ${kv} kV` : "any voltage" },
      rationale: kv ? `Snap to nearest ≥${kv} kV substation` : "Snap to nearest substation",
    };
  }

  const findMatch = t.match(/(find|list|show|where).*?(\d{2,3})\s*kv/);
  if (findMatch && /substation|sub|headroom/.test(t)) {
    const kv = Number(findMatch[2]);
    return { action: "list_subs", params: { min_kv: kv }, rationale: `Nearest ≥${kv} kV substations` };
  }
  if (/near(by|est)?\s+sub/.test(t) || /^subs?\b/.test(t)) {
    return { action: "list_subs", params: { min_kv: null }, rationale: "Nearest substations" };
  }

  // ── what's here / summarise ──
  if (/^(what|where|tell|summar|status|show me|describe).{0,30}(here|this|site|design|now|current)/.test(t)
      || /^what'?s/.test(t)) {
    return { action: "summary", params: {}, rationale: "Summarise current design" };
  }

  return null;  // falls through to LLM
}

function Message({ role, text, meta }) {
  const you = role === "user";
  return (
    <div style={{
      display: "flex", flexDirection: "column",
      alignItems: you ? "flex-end" : "flex-start",
      gap: 2,
    }}>
      <div style={{
        padding: "6px 10px", borderRadius: 8, maxWidth: "85%",
        background: you ? "#f5b731" : "rgba(255,255,255,0.08)",
        color: you ? "#0f172a" : "#e2e8f0",
        fontSize: 11, lineHeight: 1.45,
        fontFamily: '"DM Sans", sans-serif',
        whiteSpace: "pre-wrap",
      }}>
        {text}
      </div>
      {meta && (
        <div style={{ fontSize: 9, color: "#64748b", fontFamily: '"JetBrains Mono", monospace', letterSpacing: 0.3 }}>
          {meta}
        </div>
      )}
    </div>
  );
}

export default function MavenSpatialPanel({
  lat, lon, itLoadMw, tier, redundancy,
  nearbySubs = [],
  onMove,        // ({ lat, lon }) => void
  onSetLoad,    // (mw) => void
  onSetTier,    // (tier) => void
  onSetRedundancy, // ("N"|"N+1"|"2N"|"2N+1") => void
  onSetCooling, // ("free_cooling"|"evaporative"|"hybrid"|"mechanical") => void
  onSnapToSub,  // (sub) => void
}) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [msgs, setMsgs] = useState([
    { role: "assistant", text: "Princeps spatial AI — tell me how you want to change the design.", meta: "maven · local parser" },
  ]);
  const [lastCmd, setLastCmd] = useState(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 40);
  }, [open]);

  const applyCmd = useCallback((cmd, ctx) => {
    switch (cmd.action) {
      case "move": {
        const newLat = ctx.lat + cmd.params.dy_m / M_PER_DEG_LAT;
        const newLon = ctx.lon + cmd.params.dx_m / mPerDegLon(ctx.lat);
        onMove?.({ lat: newLat, lon: newLon });
        return `Moved ${Math.round(Math.hypot(cmd.params.dx_m, cmd.params.dy_m))} m. New centroid: ${newLat.toFixed(4)}°, ${newLon.toFixed(4)}°`;
      }
      case "set_load":
        onSetLoad?.(cmd.params.it_load_mw);
        return `IT load set to ${cmd.params.it_load_mw} MW. Shell + cooling + power chain resizing now.`;
      case "set_redundancy":
        onSetRedundancy?.(cmd.params.redundancy);
        return `Redundancy set to ${cmd.params.redundancy}. Regenerating plan.`;
      case "set_tier":
        onSetTier?.(cmd.params.tier);
        return `Tier set to ${cmd.params.tier}.`;
      case "set_cooling":
        onSetCooling?.(cmd.params.cooling_type);
        return `Cooling topology → ${cmd.params.cooling_type.replace("_", " ")}.`;
      case "snap_to_sub": {
        const minKv = cmd.params.min_kv || 0;
        const candidates = (nearbySubs || []).filter(s => (s.voltage_kv || 0) >= minKv);
        if (candidates.length === 0) {
          return `No substations within 10 km at ≥${minKv} kV. Try a lower voltage or pan elsewhere.`;
        }
        const withDist = candidates.map(s => ({
          ...s,
          dist_m: Math.hypot(
            (s.lat - ctx.lat) * M_PER_DEG_LAT,
            (s.lon - ctx.lon) * mPerDegLon(ctx.lat),
          ),
        })).sort((a, b) => a.dist_m - b.dist_m);
        const best = withDist[0];
        onSnapToSub?.(best);
        return `Snapped DC to ${best.name} (${best.voltage_kv || "?"} kV, ${(best.dist_m / 1000).toFixed(2)} km away).`;
      }
      case "list_subs": {
        const minKv = cmd.params.min_kv || 0;
        const list = (nearbySubs || [])
          .filter(s => (s.voltage_kv || 0) >= minKv)
          .map(s => ({
            ...s,
            dist_m: Math.hypot(
              (s.lat - ctx.lat) * M_PER_DEG_LAT,
              (s.lon - ctx.lon) * mPerDegLon(ctx.lat),
            ),
          }))
          .sort((a, b) => a.dist_m - b.dist_m)
          .slice(0, 5);
        if (list.length === 0) return `No substations within 10 km matching ≥${minKv} kV.`;
        return list
          .map((s, i) => `${i + 1}. ${s.name} · ${s.voltage_kv || "?"} kV · ${(s.dist_m / 1000).toFixed(2)} km`)
          .join("\n");
      }
      case "summary": {
        const ghaShell = (600 * ctx.itLoadMw) / 10_000;
        return [
          `Site: ${ctx.lat.toFixed(4)}°, ${ctx.lon.toFixed(4)}°`,
          `IT load: ${ctx.itLoadMw} MW · Tier ${ctx.tier} · ${ctx.redundancy}`,
          `Shell: ~${ghaShell.toFixed(2)} ha building`,
          `Grid: ${(ctx.nearbySubs || []).filter(s => (s.voltage_kv || 0) >= 132).length} substations ≥132 kV within 10 km`,
        ].join("\n");
      }
      default:
        return null;
    }
  }, [onMove, onSetLoad, onSetTier, onSetRedundancy, onSetCooling, onSnapToSub, nearbySubs]);

  const handleSubmit = useCallback(async (raw) => {
    const text = (raw ?? input).trim();
    if (!text) return;
    setInput("");
    setMsgs(m => [...m, { role: "user", text }]);

    const ctx = { lat, lon, itLoadMw, tier, redundancy, nearbySubs };
    const cmd = parseCommand(text, ctx);

    if (cmd) {
      setLastCmd({ cmd, prevState: { lat, lon, itLoadMw, tier, redundancy } });
      const result = applyCmd(cmd, ctx);
      setMsgs(m => [...m, {
        role: "assistant",
        text: result || cmd.rationale,
        meta: `maven · ${cmd.action}`,
      }]);
      return;
    }

    // Fallback: hand off to the Princeps chat endpoint. Gives the user a
    // clear signal this route costs credits and may be rate-limited.
    setMsgs(m => [...m, {
      role: "assistant",
      text: "I can't resolve that locally. For open-ended design questions, use the main Ask Princeps chat (bottom-right) — it has the full agent with grid/planning tools. Local parser supports: move, set load/tier/redundancy, snap to substation, find nearest, what's here.",
      meta: "maven · no-match",
    }]);
  }, [input, lat, lon, itLoadMw, tier, redundancy, nearbySubs, applyCmd]);

  const undo = useCallback(() => {
    if (!lastCmd) return;
    const s = lastCmd.prevState;
    if (s.lat !== lat || s.lon !== lon) onMove?.({ lat: s.lat, lon: s.lon });
    if (s.itLoadMw !== itLoadMw) onSetLoad?.(s.itLoadMw);
    if (s.tier !== tier) onSetTier?.(s.tier);
    if (s.redundancy !== redundancy) onSetRedundancy?.(s.redundancy);
    setMsgs(m => [...m, { role: "assistant", text: "Undone.", meta: "maven · undo" }]);
    setLastCmd(null);
  }, [lastCmd, lat, lon, itLoadMw, tier, redundancy, onMove, onSetLoad, onSetTier, onSetRedundancy]);

  /* ── Collapsed pill ── */
  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        style={{
          position: "absolute", bottom: 12, right: 12,
          padding: "9px 14px", borderRadius: 999, border: "none",
          background: "linear-gradient(135deg, #f5b731, #e8a012)",
          color: "#0f172a", fontWeight: 700, fontSize: 12,
          cursor: "pointer", fontFamily: '"DM Sans", sans-serif',
          boxShadow: "0 4px 16px rgba(245,183,49,0.45)",
          display: "inline-flex", alignItems: "center", gap: 8,
          zIndex: 7,
        }}
      >
        <span style={{ fontSize: 10 }}>◆</span>
        Maven · redesign this site
      </button>
    );
  }

  /* ── Expanded rail ── */
  return (
    <div style={{
      position: "absolute", bottom: 12, right: 12,
      width: 380, maxHeight: 420, display: "flex", flexDirection: "column",
      background: "rgba(15,23,42,0.96)", color: "#f1f5f9",
      borderRadius: 10, padding: "12px 14px",
      fontFamily: '"DM Sans", sans-serif',
      boxShadow: "0 12px 40px rgba(0,0,0,0.55)",
      backdropFilter: "blur(10px)",
      zIndex: 7,
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#f5b731", boxShadow: "0 0 8px #f5b731" }} />
          <span style={{ fontWeight: 700, fontSize: 12 }}>Maven · spatial redesign</span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {lastCmd && (
            <button onClick={undo} style={headerBtn}>Undo</button>
          )}
          <button onClick={() => setOpen(false)} style={{ ...headerBtn, fontWeight: 700 }}>×</button>
        </div>
      </div>

      {/* Messages */}
      <div style={{
        flex: 1, minHeight: 0, overflowY: "auto",
        display: "flex", flexDirection: "column", gap: 8,
        padding: "4px 2px",
      }}>
        {msgs.map((m, i) => <Message key={i} role={m.role} text={m.text} meta={m.meta} />)}
      </div>

      {/* Example chips (shown only at start) */}
      {msgs.length <= 1 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
          {EXAMPLES.map((ex, i) => (
            <button key={i} onClick={() => handleSubmit(ex)} style={exampleBtn}>
              {ex}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <form
        onSubmit={(e) => { e.preventDefault(); handleSubmit(); }}
        style={{ display: "flex", gap: 6, marginTop: 8 }}
      >
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="move 200m east · set load to 100 MW · tier 4…"
          style={{
            flex: 1, padding: "7px 10px", borderRadius: 6,
            border: "1px solid rgba(255,255,255,0.12)",
            background: "rgba(15,23,42,0.6)", color: "#e2e8f0",
            fontSize: 11, outline: "none",
            fontFamily: '"DM Sans", sans-serif',
          }}
        />
        <button type="submit" style={{
          padding: "7px 12px", borderRadius: 6, border: "none",
          background: "#f5b731", color: "#0f172a",
          fontWeight: 700, fontSize: 11, cursor: "pointer",
          fontFamily: '"DM Sans", sans-serif',
        }}>Go</button>
      </form>
    </div>
  );
}

const headerBtn = {
  padding: "3px 9px", borderRadius: 4, border: "none",
  background: "rgba(255,255,255,0.08)", color: "#e2e8f0",
  fontSize: 10, cursor: "pointer", fontFamily: '"DM Sans", sans-serif',
};
const exampleBtn = {
  padding: "3px 8px", borderRadius: 12, border: "1px solid rgba(245,183,49,0.35)",
  background: "rgba(245,183,49,0.08)", color: "#f5b731",
  fontSize: 10, cursor: "pointer", fontFamily: '"DM Sans", sans-serif',
  fontWeight: 600,
};
