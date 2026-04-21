/**
 * GridGraphContainer — squid.energy-inspired multi-tab Grid Graph view.
 *
 * Replaces / wraps the existing Map view. Layout:
 *   ┌──────────────────────────────────────────────────────────────────┐
 *   │ Browse │ Map │ Graph │ Table │ Resources          [filter bar]   │
 *   ├────────┬─────────────────────────┬──────────────────────────────┤
 *   │ ASSET  │                         │ GridIntelPanel (from Pulse)  │
 *   │ BROWSER│    [ active sub-view ]  │ when selection is set        │
 *   │ (14k)  │                         │                              │
 *   └────────┴─────────────────────────┴──────────────────────────────┘
 *
 * • Left:   GridAssetBrowser (virtualised 14k substation list)
 * • Center: 5 tabs — Browse / Map / Graph (d3-force) / Table / Resources
 * • Right:  GridIntelPanel from pulse/ (already built)
 */
import React, { useEffect, useMemo, useRef, useState, useCallback } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { MapboxOverlay } from "@deck.gl/mapbox";
import api from "../../services/api";
import { useSite } from "../../SiteContext";
import GridAssetDrawer from "./GridAssetDrawer";
import {
  VOLTAGE_BUCKETS,
  snapVoltage,
  DNO_COLORS,
} from "./gridPalette";
import { buildGridGraphLayers } from "./gridGraphLayers";
/* ── BOT-GL: persistent legend + hover tooltip + label builders ───────
   GridGraphLegend and GridGraphHoverTip are mounted below. GridGraphLabels
   exposes deck.gl TextLayer builders that BOT-GO can wire into its overlay
   layer list without touching this file. */
import GridGraphLegend from "./GridGraphLegend";
import GridGraphHoverTip from "./GridGraphHoverTip";
/* ── BOT-CN-M: neighbourhood rail + data hook for connection-node hybrid
   highlight (docs/audits/connection_nodes_spec.md §6). Root id is kept
   in container-level state so clicks from the map AND the asset list
   both feed it; the hook handles fetch + sessionStorage cache. */
import NeighbourhoodRail from "./NeighbourhoodRail";
import useGridNeighbourhood from "../../hooks/useGridNeighbourhood";

/* ─────────── Theme — light-gold palette (2026-04 redesign) ─────────── */
const C = {
  bg:       "#faf9f6",   // warm cream — whitespace IS the feature
  card:     "#ffffff",
  border:   "#e8e5df",
  borderSoft: "#f0ece4",
  text:     "#1a1a1a",   // --ink
  textDim:  "#4a4a4a",   // --ink-muted
  textMuted:"#9c9590",
  // Gold scale
  gold:     "#C9A64B",   // --gold
  goldDark: "#A88732",   // --gold-dark
  goldLight:"#F5E9C8",   // --gold-light
  goldSoft: "rgba(201,166,75,0.10)",
  // Semantic
  blue:     "#2563eb",
  green:    "#16a34a",
  red:      "#dc2626",
  amber:    "#d97706",
  purple:   "#7c3aed",
};

/* Internal views of the Grid Graph page. Exposed via a small segmented
   control in the left rail, NOT as a tab strip — the app-level ViewTabs
   strip is already the only horizontal nav this page needs. */
const SUBVIEWS = [
  { id: "map",       label: "Map",       hint: "Geo map" },
  { id: "graph",     label: "Graph",     hint: "Topology" },
  { id: "table",     label: "Table",     hint: "Ranked rows" },
  { id: "browse",    label: "Browse",    hint: "By DNO" },
  { id: "resources", label: "Resources", hint: "Data sources" },
];

/* VOLTAGE_BUCKETS + snapVoltage + DNO_COLORS are imported from gridPalette.js
   — the single source of truth for grid-graph colours and classification.
   The DNOS filter list is ORDER-preserving (derived from DNO_COLORS keys) so
   pill rows render in a consistent order across views. */
const DNOS = Object.keys(DNO_COLORS);

/* Transmission voltages (400/275 kV) are owned by National Grid ET, not the
   6 regional DNOs, so a DNO + 400/275 kV combo is inherently empty. The
   explanatory copy below nudges the user toward the nearest fix. */
const TRANSMISSION_VOLTAGES = new Set([400, 275]);

/* ─────────── Styles ─────────── */
const S = {
  root: {
    height: "100%",
    background: C.bg,
    fontFamily: "'DM Sans', 'Inter', system-ui, sans-serif",
    color: C.text,
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },
  /* ONE unified top bar: title · search · count. No breadcrumb, no tab
     strip, no filter band. All secondary controls live in the left rail. */
  topBar: {
    flexShrink: 0,
    background: C.card,
    borderBottom: `1px solid ${C.border}`,
    display: "flex",
    alignItems: "center",
    gap: 16,
    padding: "10px 20px",
    minHeight: 48,
  },
  title: {
    fontSize: 14,
    fontWeight: 700,
    color: C.text,
    letterSpacing: "-0.01em",
  },
  titleMuted: {
    fontSize: 11,
    fontWeight: 500,
    color: C.textMuted,
    fontFamily: "'JetBrains Mono', monospace",
  },
  searchWrap: {
    position: "relative",
    flex: 1,
    maxWidth: 520,
    display: "flex",
    alignItems: "center",
  },
  searchIcon: {
    position: "absolute",
    left: 12,
    color: C.textMuted,
    pointerEvents: "none",
    display: "flex",
  },
  searchInputTop: {
    width: "100%",
    padding: "8px 12px 8px 34px",
    border: `1px solid ${C.border}`,
    borderRadius: 8,
    fontSize: 12,
    fontFamily: "inherit",
    background: C.bg,
    color: C.text,
    outline: "none",
  },
  countBadge: {
    fontSize: 11,
    color: C.textDim,
    fontFamily: "'JetBrains Mono', monospace",
    whiteSpace: "nowrap",
  },
  body: { flex: 1, display: "flex", minHeight: 0 },
  /* Left rail: quiet sub-view picker on top, Grid Assets list below.
     No second "visual competition" sidebar. The portfolio tree lives in
     the global Sidebar and is now auto-collapsed on non-Projects routes. */
  sidebar: {
    width: 280,
    flexShrink: 0,
    borderRight: `1px solid ${C.border}`,
    background: C.card,
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  },
  subviewPicker: {
    display: "flex",
    padding: "10px 12px",
    gap: 4,
    borderBottom: `1px solid ${C.borderSoft}`,
    flexShrink: 0,
  },
  subviewBtn: (active) => ({
    flex: 1,
    padding: "6px 4px",
    background: active ? C.goldSoft : "transparent",
    border: "none",
    borderRadius: 6,
    color: active ? C.goldDark : C.textDim,
    fontSize: 10,
    fontWeight: active ? 700 : 500,
    letterSpacing: 0.3,
    cursor: "pointer",
    textTransform: "uppercase",
    fontFamily: "inherit",
  }),
  sbHeader: {
    padding: "12px 14px 10px",
    borderBottom: `1px solid ${C.borderSoft}`,
    flexShrink: 0,
  },
  sbTitleRow: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
  },
  sbTitle: {
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: 0.6,
    color: C.textMuted,
    textTransform: "uppercase",
  },
  sbCount: {
    fontSize: 22,
    fontWeight: 700,
    color: C.text,
    fontFamily: "'JetBrains Mono', monospace",
    letterSpacing: "-0.02em",
    marginTop: 2,
  },
  filterBlock: {
    marginTop: 10,
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },
  filterLabel: {
    fontSize: 9,
    color: C.textMuted,
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: 0.6,
  },
  pillRow: {
    display: "flex",
    flexWrap: "wrap",
    gap: 4,
  },
  pill: (active, colour = C.gold, disabled = false) => ({
    padding: "3px 9px",
    fontSize: 10,
    fontWeight: 700,
    background: active ? colour : "transparent",
    color: active ? "#fff" : C.textDim,
    border: `1px solid ${active ? colour : C.border}`,
    borderRadius: 10,
    cursor: disabled ? "not-allowed" : "pointer",
    fontFamily: "inherit",
    letterSpacing: 0.3,
    transition: "all 0.12s",
    opacity: disabled ? 0.4 : 1,
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
  }),
  pillCount: {
    fontSize: 9,
    fontWeight: 500,
    opacity: 0.75,
    fontFamily: "'JetBrains Mono', monospace",
  },
  resetBtn: {
    marginTop: 8,
    padding: "4px 10px",
    fontSize: 10,
    background: "transparent",
    border: `1px dashed ${C.border}`,
    color: C.textDim,
    borderRadius: 6,
    cursor: "pointer",
    alignSelf: "flex-start",
    fontFamily: "inherit",
  },
  list: { flex: 1, overflowY: "auto", position: "relative" },
  listItem: (selected) => ({
    padding: "8px 14px",
    borderBottom: `1px solid ${C.borderSoft}`,
    cursor: "pointer",
    background: selected ? C.goldSoft : "transparent",
    borderLeft: selected ? `3px solid ${C.gold}` : "3px solid transparent",
    display: "flex", alignItems: "center", gap: 10,
    fontSize: 11,
  }),
  listDot: (colour) => ({
    width: 8, height: 8, borderRadius: 4, background: colour || C.textMuted, flexShrink: 0,
  }),
  listName: {
    color: C.text, overflow: "hidden", textOverflow: "ellipsis",
    whiteSpace: "nowrap", fontWeight: 600, maxWidth: 180,
  },
  listBadge: {
    fontSize: 9, padding: "1px 6px",
    background: C.bg,
    color: C.textDim, borderRadius: 8,
    fontFamily: "'JetBrains Mono', monospace",
    marginLeft: "auto",
  },
  center: { flex: 1, position: "relative", overflow: "hidden", background: C.bg },
};


/* ═══════════════════════════════════════════════════════════════════
 * Main component
 * ═══════════════════════════════════════════════════════════════════ */
export default function GridGraphContainer({ mapContent }) {
  const [activeTab, setActiveTab] = useState("map");
  const [substations, setSubstations] = useState([]);
  const [search, setSearch] = useState("");
  const [voltageFilter, setVoltageFilter] = useState(new Set());
  const [dnoFilter, setDnoFilter] = useState(new Set());
  const [selection, setSelection] = useState(null);
  const [loading, setLoading] = useState(true);
  /* ── BOT-GL: hover-info state for the overlay tooltip. ─────────────────
     Published on a window global so BOT-GO's deck.gl onHover callback can
     drive it without a React-context round-trip. Callback signature:
       window.__gridGraphHover(info)   // info = deck.gl PickingInfo | null
     The tooltip hides itself when info.object is null/absent. */
  const [hoverInfo, setHoverInfo] = useState(null);
  useEffect(() => {
    if (typeof window === "undefined") return;
    window.__gridGraphHover = setHoverInfo;
    return () => {
      if (window.__gridGraphHover === setHoverInfo) delete window.__gridGraphHover;
    };
  }, []);
  const { pickedLocation, setPickedLocation } = useSite();

  /* ── BOT-CN-M: neighbourhood root + depth ───────────────────────────
     `neighbourhoodRootId` drives the hook + sidecar rail + layer
     highlight. Clicking a substation (map OR list) sets it; clicking the
     same id again OR pressing Esc clears it. `nbhDepth` is the 1/2/3
     toggle in the rail header — default 2 per spec (§4).               */
  const [neighbourhoodRootId, setNeighbourhoodRootId] = useState(null);
  const [nbhDepth, setNbhDepth] = useState(2);
  const { data: neighbourhoodData, loading: neighbourhoodLoading, error: neighbourhoodError } =
    useGridNeighbourhood(neighbourhoodRootId, { depth: nbhDepth, radiusKm: 20 });

  const clearNeighbourhood = useCallback(() => {
    setNeighbourhoodRootId(null);
  }, []);

  const rootNeighbourhood = useCallback((id) => {
    if (!id) return;
    setNeighbourhoodRootId((prev) => (prev === id ? null : id));
  }, []);

  // Esc clears both selection and the neighbourhood highlight.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") {
        setNeighbourhoodRootId(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  /* Load substation index on mount (one-shot, ~14k rows) */
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/nged/substations/index?min_voltage_kv=11");
        if (!res.ok) throw new Error("fetch failed");
        const data = await res.json();
        if (!cancelled && Array.isArray(data)) setSubstations(data);
      } catch (e) {
        console.warn("[GridGraph] substation index load failed:", e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  /* Filter pipeline */
  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    return substations.filter(s => {
      if (voltageFilter.size > 0) {
        if (!voltageFilter.has(snapVoltage(s.voltage_kv))) return false;
      }
      if (dnoFilter.size > 0 && !dnoFilter.has(s.dno)) return false;
      if (q && !(s.name || "").toLowerCase().includes(q)) return false;
      return true;
    });
  }, [substations, search, voltageFilter, dnoFilter]);

  /* ─── Facet counts ──────────────────────────────────────────────────
     Each pill's count reflects how many substations would remain if the
     user toggled THAT pill in addition to the filters currently applied
     on the OTHER axes (standard cross-facet pattern — lets the user see
     where moves actually yield results without having to guess).       */
  const voltageCounts = useMemo(() => {
    const q = search.toLowerCase().trim();
    const counts = Object.fromEntries(VOLTAGE_BUCKETS.map(v => [v, 0]));
    for (const s of substations) {
      if (dnoFilter.size > 0 && !dnoFilter.has(s.dno)) continue;
      if (q && !(s.name || "").toLowerCase().includes(q)) continue;
      const snap = snapVoltage(s.voltage_kv);
      if (snap in counts) counts[snap]++;
    }
    return counts;
  }, [substations, dnoFilter, search]);

  const dnoCounts = useMemo(() => {
    const q = search.toLowerCase().trim();
    const counts = Object.fromEntries(DNOS.map(d => [d, 0]));
    for (const s of substations) {
      if (voltageFilter.size > 0 && !voltageFilter.has(snapVoltage(s.voltage_kv))) continue;
      if (q && !(s.name || "").toLowerCase().includes(q)) continue;
      if (s.dno in counts) counts[s.dno]++;
    }
    return counts;
  }, [substations, voltageFilter, search]);

  const toggleVoltage = (v) => {
    setVoltageFilter(prev => {
      const next = new Set(prev);
      if (next.has(v)) next.delete(v); else next.add(v);
      return next;
    });
  };
  const toggleDno = (d) => {
    setDnoFilter(prev => {
      const next = new Set(prev);
      if (next.has(d)) next.delete(d); else next.add(d);
      return next;
    });
  };

  const handleRowClick = (s) => {
    setSelection({
      kind: "substation",
      feature: { properties: s },
      lngLat: { lat: s.lat, lng: s.lon },
    });
    if (s.lat != null && s.lon != null) {
      setPickedLocation({ lat: s.lat, lon: s.lon });
    }
    // BOT-CN-M: a substation click also roots the neighbourhood. If the
    // user clicks the *same* substation twice the toggle in
    // rootNeighbourhood() clears the highlight (second-click-to-unpin).
    if (s?.id) rootNeighbourhood(s.id);
  };

  const hasFilters = voltageFilter.size > 0 || dnoFilter.size > 0 || search;
  const resetFilters = () => {
    setVoltageFilter(new Set()); setDnoFilter(new Set()); setSearch("");
  };

  /* Build the smart empty-state copy based on *why* the combo is empty.
     Priority order:
       1. Transmission voltage (400/275 kV) + any DNO — hard mismatch.
       2. Voltage + DNO selected but no overlap even without the search.
       3. Search-only misses vs. a filter combo that would itself yield 0.
       4. Generic "try removing the last thing you toggled".             */
  const emptyStateMessage = useMemo(() => {
    if (filtered.length !== 0 || substations.length === 0) return null;

    const selVoltages = Array.from(voltageFilter);
    const selDnos = Array.from(dnoFilter);
    const transmissionSel = selVoltages.filter(v => TRANSMISSION_VOLTAGES.has(v));

    if (transmissionSel.length > 0 && selDnos.length > 0) {
      const vTxt = transmissionSel.map(v => `${v}kV`).join(" / ");
      const dTxt = selDnos.join(" / ");
      return {
        title: `No ${vTxt} substations operated by ${dTxt}.`,
        body: `${vTxt} is National Grid ET transmission, not DNO-owned. Clear the DNO filter to see NGET assets, or pick 132 kV / 33 kV / 11 kV to stay within ${dTxt}.`,
        suggestion: `clear-dno`,
      };
    }

    // Voltage + DNO selected, just no overlap in the data we have
    if (selVoltages.length > 0 && selDnos.length > 0) {
      return {
        title: `No substations match ${selVoltages.map(v => v + "kV").join(" / ")} on ${selDnos.join(" / ")}.`,
        body: `This DNO may not operate assets at that voltage, or the combo isn't in the open-data feed yet. Try clearing one of the two filters.`,
        suggestion: `clear-dno`,
      };
    }

    if (search && !selVoltages.length && !selDnos.length) {
      return {
        title: `No substations match "${search}".`,
        body: `The 14k index is indexed by name — check spelling, or browse by DNO / voltage instead.`,
        suggestion: `clear-search`,
      };
    }

    if (selVoltages.length > 0) {
      return {
        title: `No substations at ${selVoltages.map(v => v + "kV").join(" / ")}.`,
        body: `Try expanding the voltage selection or clearing all filters.`,
        suggestion: `clear-all`,
      };
    }
    if (selDnos.length > 0) {
      return {
        title: `No substations for ${selDnos.join(" / ")}.`,
        body: `The ingest for this DNO may be mid-refresh — try another operator or clear filters.`,
        suggestion: `clear-all`,
      };
    }
    return {
      title: `No substations loaded.`,
      body: `The grid index is empty. Check the /api/nged/substations/index feed.`,
      suggestion: `clear-all`,
    };
  }, [filtered.length, substations.length, voltageFilter, dnoFilter, search]);

  return (
    <div style={S.root}>
      {/* ═══ ONE unified top bar ═══════════════════════════════════════════
          • title + "/ Map" contextual sub-view tag
          • primary action: Find-a-Site search (replaces the floating modal)
          • quiet count badge on the right
          No breadcrumb here — AppShell already hides its breadcrumb on
          grid-native routes. The workspace tab strip (Dashboard / Projects /
          Pulse / Grid Graph / Curtailment) lives in CenterCanvas/ViewTabs.
          ══════════════════════════════════════════════════════════════════ */}
      <div style={S.topBar}>
        <div style={S.title}>Grid Graph</div>
        <div style={S.titleMuted}>
          &#47;&nbsp;{SUBVIEWS.find(s => s.id === activeTab)?.label || activeTab}
        </div>
        <div style={S.searchWrap}>
          <span style={S.searchIcon}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2"
                 strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <path d="M21 21l-4.35-4.35" />
            </svg>
          </span>
          <input
            style={S.searchInputTop}
            type="search"
            placeholder="Find a substation, postcode, or DNO…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search grid assets"
          />
        </div>
        <div style={{ flex: 1 }} />
        <div style={S.countBadge}>
          <b style={{ color: C.text }}>{filtered.length.toLocaleString()}</b>
          {substations.length > 0 && filtered.length !== substations.length && (
            <span style={{ color: C.textMuted }}> / {substations.length.toLocaleString()}</span>
          )}&nbsp;sites
        </div>
      </div>

      {/* ═══ 3-column body ═══════════════════════════════════════════════ */}
      <div style={S.body}>
        {/* LEFT — sub-view picker + filtered Grid Assets list */}
        <aside style={S.sidebar} aria-label="Grid Assets">
          <div style={S.subviewPicker} role="tablist" aria-label="Grid Graph view">
            {SUBVIEWS.map(v => (
              <button
                key={v.id}
                role="tab"
                aria-selected={activeTab === v.id}
                title={v.hint}
                style={S.subviewBtn(activeTab === v.id)}
                onClick={() => setActiveTab(v.id)}
              >
                {v.label}
              </button>
            ))}
          </div>

          <div style={S.sbHeader}>
            <div style={S.sbTitleRow}>
              <span style={S.sbTitle}>Grid Assets</span>
              {hasFilters && (
                <button style={S.resetBtn} onClick={resetFilters}>Reset</button>
              )}
            </div>
            <div style={S.sbCount}>
              {loading ? "…" : filtered.length.toLocaleString()}
            </div>

            {/* Voltage + DNO filters moved INSIDE the Grid Assets header.
                No separate horizontal filter band above the content. */}
            <div style={S.filterBlock}>
              <span style={S.filterLabel}>Voltage</span>
              <div style={S.pillRow}>
                {VOLTAGE_BUCKETS.map(v => {
                  const count = voltageCounts[v] || 0;
                  const active = voltageFilter.has(v);
                  const disabled = count === 0 && !active;
                  return (
                    <button
                      key={v}
                      style={S.pill(active, C.gold, disabled)}
                      title={
                        disabled
                          ? `No ${v}kV substations under the current DNO filter — click to clear DNO`
                          : `${v}kV — ${count.toLocaleString()} sites`
                      }
                      onClick={() => {
                        // Zero-count pill: clear the OTHER axis so the user
                        // actually escapes the dead-end combo.
                        if (disabled) setDnoFilter(new Set());
                        else toggleVoltage(v);
                      }}
                    >
                      <span>{v}kV</span>
                      <span style={S.pillCount}>{count.toLocaleString()}</span>
                    </button>
                  );
                })}
              </div>
            </div>
            <div style={S.filterBlock}>
              <span style={S.filterLabel}>DNO</span>
              <div style={S.pillRow}>
                {DNOS.map(d => {
                  const count = dnoCounts[d] || 0;
                  const active = dnoFilter.has(d);
                  const disabled = count === 0 && !active;
                  return (
                    <button
                      key={d}
                      style={S.pill(active, C.goldDark, disabled)}
                      title={
                        disabled
                          ? `${d} has no substations at the currently-selected voltage — click to clear voltage`
                          : `${d} — ${count.toLocaleString()} sites`
                      }
                      onClick={() => {
                        if (disabled) setVoltageFilter(new Set());
                        else toggleDno(d);
                      }}
                    >
                      <span>{d}</span>
                      <span style={S.pillCount}>{count.toLocaleString()}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          <VirtualList
            items={filtered}
            selection={selection}
            onSelect={handleRowClick}
            loading={loading}
            emptyState={emptyStateMessage}
            onClearVoltage={() => setVoltageFilter(new Set())}
            onClearDno={() => setDnoFilter(new Set())}
            onClearAll={resetFilters}
          />
        </aside>

        {/* CENTER — active sub-view; map is the hero when active */}
        <div style={S.center}>
          {activeTab === "browse"    && <BrowseView substations={substations} filtered={filtered} onSelect={handleRowClick} />}
          {activeTab === "map"       && mapContent}
          {activeTab === "graph"     && (
            <GraphView
              substations={filtered}
              selection={selection}
              onSelect={handleRowClick}
              neighbourhood={neighbourhoodData}
              onRootNode={rootNeighbourhood}
              onClearRoot={clearNeighbourhood}
            />
          )}
          {activeTab === "table"     && <TableView substations={filtered} onSelect={handleRowClick} />}
          {activeTab === "resources" && <ResourcesView />}

          {/* BOT-GL: persistent colour legend — only on the visual sub-views.
              The Table / Resources / Browse tabs have no map canvas to key. */}
          {(activeTab === "map" || activeTab === "graph") && (
            <GridGraphLegend />
          )}
        </div>

        {/* ── BOT-CN-M: Neighbourhood rail — sidecar between center and drawer.
            Mounts only when a substation is rooted (click on map / list).
            40 px wide per spec §3 wireframe. ─────────────────────────── */}
        {neighbourhoodRootId && (activeTab === "map" || activeTab === "graph") && (
          <NeighbourhoodRail
            data={neighbourhoodData}
            loading={neighbourhoodLoading}
            error={neighbourhoodError}
            depth={nbhDepth}
            onDepthChange={setNbhDepth}
            onReroot={(id) => {
              if (!id) return;
              // Clicking the root again = clear; otherwise chain.
              if (id === neighbourhoodRootId) {
                setNeighbourhoodRootId(null);
              } else {
                setNeighbourhoodRootId(id);
              }
            }}
            onReset={clearNeighbourhood}
          />
        )}

        {/* RIGHT — full-height drawer shell (clearly-marked slots for BOT-Z3) */}
        {selection && (
          <GridAssetDrawer
            selection={selection}
            onClose={() => setSelection(null)}
          />
        )}
      </div>

      {/* BOT-GL: hover tooltip — position: fixed, renders above everything.
          Driven by window.__gridGraphHover(info) from BOT-GO's onHover. */}
      <GridGraphHoverTip info={hoverInfo} />
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════
 * Hand-rolled virtualized list (avoids adding react-window as a dep)
 * ═══════════════════════════════════════════════════════════════════ */
function VirtualList({
  items, selection, onSelect, loading,
  emptyState, onClearVoltage, onClearDno, onClearAll,
}) {
  const ROW_H = 42;
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(600);
  const containerRef = useRef(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setViewportH(el.clientHeight);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const onScroll = (e) => setScrollTop(e.target.scrollTop);

  if (loading) {
    return <div style={{ padding: 20, color: C.textMuted, fontSize: 12, textAlign: "center" }}>Loading 14k substations…</div>;
  }
  if (items.length === 0) {
    const msg = emptyState || {
      title: "No matches",
      body: "Adjust filters or clear them to see the full network.",
      suggestion: "clear-all",
    };
    const primaryHandler =
      msg.suggestion === "clear-dno"    ? onClearDno    :
      msg.suggestion === "clear-search" ? onClearAll    :
      msg.suggestion === "clear-all"    ? onClearAll    :
                                          onClearAll;
    const primaryLabel =
      msg.suggestion === "clear-dno"    ? "Clear DNO filter" :
      msg.suggestion === "clear-search" ? "Clear search"     :
                                          "Clear all filters";
    return (
      <div style={{
        padding: "22px 18px",
        color: C.textDim,
        fontSize: 12,
        lineHeight: 1.5,
      }}>
        <div style={{
          fontSize: 12,
          fontWeight: 700,
          color: C.text,
          marginBottom: 6,
          letterSpacing: "-0.01em",
        }}>
          {msg.title}
        </div>
        <div style={{
          fontSize: 11,
          color: C.textDim,
          marginBottom: 14,
        }}>
          {msg.body}
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <button
            style={{
              padding: "5px 12px",
              fontSize: 10,
              fontWeight: 700,
              background: C.gold,
              color: "#fff",
              border: "none",
              borderRadius: 6,
              cursor: "pointer",
              fontFamily: "inherit",
              letterSpacing: 0.3,
              textTransform: "uppercase",
            }}
            onClick={primaryHandler}
          >
            {primaryLabel}
          </button>
          {msg.suggestion !== "clear-all" && (
            <button
              style={{
                padding: "5px 12px",
                fontSize: 10,
                fontWeight: 600,
                background: "transparent",
                color: C.textDim,
                border: `1px solid ${C.border}`,
                borderRadius: 6,
                cursor: "pointer",
                fontFamily: "inherit",
                letterSpacing: 0.3,
                textTransform: "uppercase",
              }}
              onClick={onClearAll}
            >
              Clear all
            </button>
          )}
        </div>
      </div>
    );
  }

  const startIdx = Math.max(0, Math.floor(scrollTop / ROW_H) - 10);
  const endIdx = Math.min(items.length, startIdx + Math.ceil(viewportH / ROW_H) + 20);
  const totalH = items.length * ROW_H;
  const offsetY = startIdx * ROW_H;

  return (
    <div ref={containerRef} style={S.list} onScroll={onScroll}>
      <div style={{ height: totalH, position: "relative" }}>
        <div style={{ position: "absolute", top: offsetY, left: 0, right: 0 }}>
          {items.slice(startIdx, endIdx).map(s => {
            const selectedId = selection?.feature?.properties?.id;
            const isSel = selectedId === s.id;
            const displayName = s.name && s.name.trim()
              ? s.name
              : (s.external_id || `Unnamed ${s.dno || ""}`);
            return (
              <div key={s.id} style={{ ...S.listItem(isSel), height: ROW_H, boxSizing: "border-box" }}
                   onClick={() => onSelect(s)}>
                <div style={S.listDot(s.colour)} />
                <div>
                  <div style={S.listName} title={displayName}>{displayName}</div>
                  <div style={{ fontSize: 9, color: C.textMuted, marginTop: 1 }}>
                    {s.dno || "—"}{s.site_type ? ` · ${s.site_type}` : ""}
                  </div>
                </div>
                <div style={S.listBadge}>{Math.round(s.voltage_kv || 0)}kV</div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════
 * Browse tab — onboarding cards
 * ═══════════════════════════════════════════════════════════════════ */
function BrowseView({ substations, filtered, onSelect }) {
  const byDno = useMemo(() => {
    const map = {};
    for (const s of substations) {
      const k = s.dno || "UNKNOWN";
      if (!map[k]) map[k] = { dno: k, count: 0, mw: 0 };
      map[k].count++;
      map[k].mw += s.headroom_mw || 0;
    }
    return Object.values(map).sort((a, b) => b.count - a.count);
  }, [substations]);

  const byVoltage = useMemo(() => {
    const map = {};
    for (const s of substations) {
      const v = Math.round(s.voltage_kv || 0);
      if (!map[v]) map[v] = { voltage: v, count: 0 };
      map[v].count++;
    }
    return Object.values(map).sort((a, b) => b.voltage - a.voltage);
  }, [substations]);

  const top = useMemo(() =>
    [...substations].sort((a, b) => (b.headroom_mw || 0) - (a.headroom_mw || 0)).slice(0, 12),
    [substations]
  );

  return (
    <div style={{ padding: 24, overflowY: "auto", height: "100%" }}>
      <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800 }}>UK Grid Network — Browse</h2>
      <p style={{ fontSize: 12, color: C.textDim, marginTop: 4, marginBottom: 22, maxWidth: 700 }}>
        {substations.length.toLocaleString()} substations across the 6 UK DNOs, ingested from OpenDataSoft portals + NGED LTDS CIM Stage 1.3.
        Pick a DNO below to drill in, or switch to <b>Map</b> / <b>Graph</b> / <b>Table</b> above.
      </p>

      <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5, color: C.textMuted, marginBottom: 10 }}>
        By DNO
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12, marginBottom: 28 }}>
        {byDno.map(d => (
          <div key={d.dno} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 14 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: C.textMuted, textTransform: "uppercase", letterSpacing: 0.5 }}>
              {d.dno}
            </div>
            <div style={{ fontSize: 24, fontWeight: 800, fontFamily: "'JetBrains Mono', monospace", marginTop: 4 }}>
              {d.count.toLocaleString()}
            </div>
            <div style={{ fontSize: 10, color: C.textDim, marginTop: 2 }}>
              {Math.round(d.mw).toLocaleString()} MW headroom
            </div>
          </div>
        ))}
      </div>

      <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5, color: C.textMuted, marginBottom: 10 }}>
        By voltage level
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 28 }}>
        {byVoltage.slice(0, 10).map(v => (
          <div key={v.voltage} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: "8px 14px" }}>
            <div style={{ fontSize: 14, fontWeight: 800 }}>{v.voltage} kV</div>
            <div style={{ fontSize: 10, color: C.textDim }}>{v.count.toLocaleString()} sites</div>
          </div>
        ))}
      </div>

      <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.5, color: C.textMuted, marginBottom: 10 }}>
        Top substations by headroom
      </div>
      <div>
        {top.map(s => (
          <div key={s.id}
               onClick={() => onSelect(s)}
               style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px",
                        background: C.card, border: `1px solid ${C.border}`, borderRadius: 6,
                        marginBottom: 4, cursor: "pointer", fontSize: 11 }}>
            <div style={S.listDot(s.colour)} />
            <div style={{ flex: 1, fontWeight: 700 }}>{s.name}</div>
            <div style={{ color: C.textDim }}>{s.dno}</div>
            <div style={{ color: C.textDim }}>{Math.round(s.voltage_kv)} kV</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: C.green }}>
              {Math.round(s.headroom_mw)} MW
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════
 * Table tab
 * ═══════════════════════════════════════════════════════════════════ */
function TableView({ substations, onSelect }) {
  const [sortKey, setSortKey] = useState("headroom_mw");
  const [sortDir, setSortDir] = useState(-1);

  const sorted = useMemo(() => {
    const arr = [...substations];
    arr.sort((a, b) => {
      const av = a[sortKey] ?? 0;
      const bv = b[sortKey] ?? 0;
      if (typeof av === "string" && typeof bv === "string") return av.localeCompare(bv) * sortDir;
      return (av - bv) * sortDir;
    });
    return arr.slice(0, 500);
  }, [substations, sortKey, sortDir]);

  const clickHeader = (k) => {
    if (k === sortKey) setSortDir(d => -d);
    else { setSortKey(k); setSortDir(-1); }
  };

  const HEADER = (k, label, w) => (
    <th style={{ padding: "10px 12px", textAlign: "left", fontSize: 10, fontWeight: 700,
                 color: C.textDim, textTransform: "uppercase", letterSpacing: 0.5,
                 borderBottom: `2px solid ${C.border}`, cursor: "pointer", width: w }}
        onClick={() => clickHeader(k)}>
      {label}{sortKey === k ? (sortDir < 0 ? " ↓" : " ↑") : ""}
    </th>
  );

  return (
    <div style={{ padding: 20, overflowY: "auto", height: "100%", background: C.card }}>
      <div style={{ fontSize: 11, color: C.textDim, marginBottom: 10 }}>
        {substations.length.toLocaleString()} substations — showing top 500 by {sortKey}
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
        <thead>
          <tr>
            {HEADER("name", "Name", "30%")}
            {HEADER("dno", "DNO", "10%")}
            {HEADER("voltage_kv", "Voltage", "10%")}
            {HEADER("site_type", "Type", "15%")}
            {HEADER("headroom_mw", "Demand HR (MW)", "15%")}
            {HEADER("gen_headroom_mw", "Gen HR (MW)", "15%")}
            <th style={{ padding: "10px 12px", width: "5%" }} />
          </tr>
        </thead>
        <tbody>
          {sorted.map(s => (
            <tr key={s.id}
                style={{ borderBottom: `1px solid ${C.border}`, cursor: "pointer" }}
                onClick={() => onSelect(s)}
                onMouseEnter={e => e.currentTarget.style.background = "#f8fafc"}
                onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
              <td style={{ padding: "8px 12px", fontWeight: 700 }}>
                <span style={{ ...S.listDot(s.colour), display: "inline-block", marginRight: 8 }} />
                {s.name}
              </td>
              <td style={{ padding: "8px 12px", color: C.textDim }}>{s.dno}</td>
              <td style={{ padding: "8px 12px", fontFamily: "'JetBrains Mono', monospace" }}>{Math.round(s.voltage_kv)}</td>
              <td style={{ padding: "8px 12px", color: C.textDim, fontSize: 10 }}>{s.site_type || "—"}</td>
              <td style={{ padding: "8px 12px", fontFamily: "'JetBrains Mono', monospace",
                           fontWeight: 700, color: s.headroom_mw > 50 ? C.green : s.headroom_mw > 10 ? C.amber : C.red }}>
                {Math.round(s.headroom_mw || 0)}
              </td>
              <td style={{ padding: "8px 12px", fontFamily: "'JetBrains Mono', monospace", color: C.textDim }}>
                {Math.round(s.gen_headroom_mw || 0)}
              </td>
              <td style={{ padding: "8px 12px", color: C.textMuted, fontSize: 10 }}>→</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════
 * Graph tab — deck.gl + Mapbox GL geographic view.
 *
 * OWNED by BOT-GO for its layer-builder + toggle wiring. Siblings:
 *   - BOT-GL owns GridGraphLegend + GridGraphHoverTip + GridGraphLabels
 *   - BOT-GA owns the left asset browser
 *   - BOT-GC owns gridPalette.js
 *
 * Seven toggles in a top-right overlay panel each mutate at least one
 * deck.gl layer in the `deckLayers` memo:
 *   substations  → grid-graph-substations  (Scatterplot, dot by DNO)
 *   capacityRag  → grid-graph-capacity-rag (Scatterplot, RAG by headroom)
 *   constraints  → grid-graph-constraints-*(GeoJson polygon + centroid)
 *   queueDepth   → grid-graph-queue-depth  (Scatterplot, bubble ∝ depth)
 *   lines        → grid-graph-lines        (GeoJson PathLayer, V-coloured)
 *   tecQueue     → grid-graph-tec-queue    (IconLayer, triangle, fade yr)
 *   repd         → grid-graph-repd         (IconLayer, square, by status)
 *
 * Toggle state is LOCAL to the Graph view so it doesn't collide with the
 * MapView's own layer-rail toggles (those are driven by SiteContext and
 * belong to the Mapbox sub-view, not this one).
 * ═══════════════════════════════════════════════════════════════════ */

const GRAPH_TOGGLES = [
  { id: "substations",  label: "Substations",   hint: "All substation dots, coloured by DNO",     swatch: "#C9A64B" },
  { id: "capacityRag",  label: "Capacity (RAG)", hint: "Green >30% / amber 10-30% / red <10%",    swatch: "#46b482" },
  { id: "constraints",  label: "Constraints",    hint: "Congestion boundary polygons",            swatch: "#e6732a" },
  { id: "queueDepth",   label: "Queue Depth",    hint: "Bubble size ∝ queue depth (MW)",          swatch: "#7c3aed" },
  { id: "lines",        label: "Lines",          hint: "Power lines (OSM/LTDS), coloured by kV",  swatch: "#f5b731" },
  { id: "tecQueue",     label: "TEC Queue",      hint: "ECR/TEC-registered projects (triangles)", swatch: "#7c3aed" },
  { id: "repd",         label: "REPD",           hint: "Renewable energy planning database",      swatch: "#16a34a" },
];

const DEFAULT_VIEW_STATE = {
  longitude: -2.8,
  latitude: 54.0,
  zoom: 5.2,
  pitch: 0,
  bearing: 0,
};

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || "";

function GraphView({ substations, selection, onSelect, neighbourhood, onRootNode, onClearRoot }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const overlayRef = useRef(null);
  const [mapError, setMapError] = useState(null);
  const [mapReady, setMapReady] = useState(false);

  // ── 7 toggle states. Substations on by default so the view isn't empty. ──
  const [toggles, setToggles] = useState({
    substations:  true,
    capacityRag:  false,
    constraints:  false,
    queueDepth:   false,
    lines:        false,
    tecQueue:     false,
    repd:         false,
  });

  const toggle = useCallback((id) => {
    setToggles((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  // ── Fetched-on-demand datasets per toggle ─────────────────────────────
  const [constraintsFC, setConstraintsFC] = useState(null);
  const [queueData,     setQueueData]     = useState(null);
  const [linesFC,       setLinesFC]       = useState(null);
  const [tecFC,         setTecFC]         = useState(null);
  const [repdFC,        setRepdFC]        = useState(null);

  // Current map bbox (for viewport-limited endpoints). Updated on moveend.
  const [bbox, setBbox] = useState(null);

  /* Init Mapbox + MapboxOverlay once */
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    if (!MAPBOX_TOKEN) {
      setMapError("Missing VITE_MAPBOX_TOKEN — map cannot initialise.");
      return;
    }
    mapboxgl.accessToken = MAPBOX_TOKEN;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/light-v11",
      center: [DEFAULT_VIEW_STATE.longitude, DEFAULT_VIEW_STATE.latitude],
      zoom: DEFAULT_VIEW_STATE.zoom,
      pitch: DEFAULT_VIEW_STATE.pitch,
      bearing: DEFAULT_VIEW_STATE.bearing,
      attributionControl: false,
    });
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new mapboxgl.AttributionControl({ compact: true }), "bottom-right");

    const overlay = new MapboxOverlay({ interleaved: false, layers: [] });
    map.once("load", () => {
      map.addControl(overlay);
      overlayRef.current = overlay;
      setMapReady(true);
      const b = map.getBounds();
      setBbox([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]);
    });

    const onMoveEnd = () => {
      const b = map.getBounds();
      setBbox([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]);
    };
    map.on("moveend", onMoveEnd);

    /* BOT-CN-M: click on empty map (no deck.gl object under cursor) clears
       the neighbourhood root. MapboxOverlay in non-interleaved mode
       consumes clicks on its own objects before dispatching to the map,
       so by the time mapbox's click handler runs we can safely assume
       nothing under the cursor was a grid asset. Confirm with pickObject
       as a double-check — if deck picks something there the click would
       have been intercepted first anyway. */
    const onMapClick = (e) => {
      const overlayNow = overlayRef.current;
      if (!overlayNow) return;
      let picked = null;
      try {
        picked = overlayNow.pickObject({ x: e.point.x, y: e.point.y, radius: 4 });
      } catch {}
      if (!picked) onClearRootRef.current?.();
    };
    map.on("click", onMapClick);

    mapRef.current = map;
    return () => {
      map.off("moveend", onMoveEnd);
      map.off("click", onMapClick);
      try { overlay.finalize?.(); } catch {}
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
    };
  }, []);

  /* Pin onClearRoot into a ref so the click handler above (which closes
     over the first render's prop) can always reach the latest callback
     without forcing the whole map-init effect to re-run. */
  const onClearRootRef = useRef(onClearRoot);
  useEffect(() => { onClearRootRef.current = onClearRoot; }, [onClearRoot]);

  /* Fetch constraints once when toggled on */
  useEffect(() => {
    if (!toggles.constraints || constraintsFC) return;
    let cancelled = false;
    api.grid.constraints(48).then((d) => {
      if (cancelled || !d) return;
      setConstraintsFC({ type: "FeatureCollection", features: d.features || [] });
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [toggles.constraints, constraintsFC]);

  /* Fetch queue summary when toggled on (use current bbox; falls back to synthetic) */
  useEffect(() => {
    if (!toggles.queueDepth) return;
    let cancelled = false;
    api.grid.queueSummary(bbox).then((d) => {
      if (cancelled) return;
      setQueueData(d); // may be [] or null; builder handles fallback
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [toggles.queueDepth, bbox]);

  /* Fetch power lines viewport-scoped on zoom ≥ 7 */
  useEffect(() => {
    if (!toggles.lines || !bbox) return;
    let cancelled = false;
    const z = mapRef.current?.getZoom() || 0;
    // Keep the request bounded — at low zoom use min_voltage_kv=132 filter
    const minKv = z < 7 ? 132 : z < 9 ? 33 : 0;
    api.grid.osmLines(bbox, minKv).then((d) => {
      if (cancelled || !d) return;
      setLinesFC(d.features ? d : { type: "FeatureCollection", features: d || [] });
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [toggles.lines, bbox]);

  /* Fetch TEC queue viewport-scoped */
  useEffect(() => {
    if (!toggles.tecQueue || !bbox) return;
    let cancelled = false;
    api.eso.tecGeojson(bbox).then((d) => {
      if (cancelled || !d) return;
      setTecFC(d.features ? d : { type: "FeatureCollection", features: d || [] });
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [toggles.tecQueue, bbox]);

  /* Fetch REPD viewport-scoped (zoom-dependent min MW to avoid clutter) */
  useEffect(() => {
    if (!toggles.repd || !bbox) return;
    let cancelled = false;
    const z = mapRef.current?.getZoom() || 0;
    const minMw = z < 7 ? 50 : z < 9 ? 10 : z < 11 ? 1 : 0;
    api.repd.geojson(bbox, null, null, minMw).then((d) => {
      if (cancelled || !d) return;
      setRepdFC(d.features ? d : { type: "FeatureCollection", features: d || [] });
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [toggles.repd, bbox]);

  /* Build layers from current toggles + data */
  const handleLayerClick = useCallback((sel) => {
    if (sel && onSelect) {
      // GridAssetDrawer expects an object shaped like the list row; adapt.
      if (sel.kind === "substation" && sel.feature?.properties) {
        onSelect(sel.feature.properties);
      } else {
        // Non-substation kinds — set selection directly via parent state
        // bridge. The parent onSelect expects a substation-shape, so we
        // pass a synthetic object with name + id so the drawer can fall
        // back to its basic KV view for ECR/TEC/REPD/constraint kinds.
        const p = sel.feature?.properties || {};
        onSelect({
          id:            p.ref_id || p.project_id || p.boundary_id || p.id || p.name,
          name:          p.name || p.project_name || p.connection_site || "—",
          dno:           p.dno,
          voltage_kv:    p.voltage_kv,
          headroom_mw:   p.capacity_mw,
          lat:           sel.lngLat?.lat,
          lon:           sel.lngLat?.lng,
          _kind:         sel.kind,
          _raw:          p,
        });
      }
    }
  }, [onSelect]);

  const deckLayers = useMemo(() => {
    if (!mapReady) return [];
    return buildGridGraphLayers({
      substations,
      constraintsFC,
      queueData,
      linesFC,
      tecFC,
      repdFC,
      toggles,
      onClick: handleLayerClick,
      // BOT-CN-M: when a root is set, the assembler dims non-related
      // base substations and stacks the three neighbourhood layers
      // (edges / nodes-glow / geo-adjacent) above everything else.
      neighbourhood,
      // BOT-GL integration: every layer calls this on hover so
      // GridGraphHoverTip can render the fixed popover. Null on
      // mouse-leave hides it.
      onHover: (info) => {
        if (typeof window.__gridGraphHover === "function") {
          window.__gridGraphHover(info?.object ? info : null);
        }
      },
    });
  }, [mapReady, substations, constraintsFC, queueData, linesFC, tecFC, repdFC, toggles, handleLayerClick, neighbourhood]);

  /* Push layers to the overlay whenever they change */
  useEffect(() => {
    if (overlayRef.current) overlayRef.current.setProps({ layers: deckLayers });
  }, [deckLayers]);

  /* Active layer count for the panel header */
  const activeCount = GRAPH_TOGGLES.filter(t => toggles[t.id]).length;

  return (
    <div style={{ width: "100%", height: "100%", position: "relative", background: "#eef1f4" }}>
      <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />

      {mapError && (
        <div style={{
          position: "absolute", top: 16, left: "50%", transform: "translateX(-50%)",
          background: "#FBD8D5", color: "#8E1E1E", border: "1px solid #E89A94",
          padding: "8px 14px", borderRadius: 6, fontSize: 12, zIndex: 10,
        }}>
          {mapError}
        </div>
      )}

      {/* ── Overlay toggle panel (top-right) ────────────────────────── */}
      <div style={{
        position: "absolute", top: 12, right: 12, zIndex: 5,
        background: "rgba(255,255,255,0.98)",
        border: `1px solid ${C.border}`,
        borderRadius: 10,
        padding: "12px 14px",
        boxShadow: "0 4px 14px rgba(15,23,42,0.10)",
        fontFamily: "'DM Sans', system-ui, sans-serif",
        minWidth: 220,
      }}>
        <div style={{
          display: "flex", alignItems: "baseline", justifyContent: "space-between",
          marginBottom: 8,
        }}>
          <span style={{
            fontSize: 10, fontWeight: 700, letterSpacing: 0.6,
            color: C.textMuted, textTransform: "uppercase",
          }}>Grid Overlays</span>
          <span style={{
            fontSize: 10, fontFamily: "'JetBrains Mono', monospace",
            color: C.textDim,
          }}>{activeCount}/{GRAPH_TOGGLES.length}</span>
        </div>
        {GRAPH_TOGGLES.map(t => (
          <label
            key={t.id}
            title={t.hint}
            style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "5px 4px", cursor: "pointer",
              borderRadius: 6,
              background: toggles[t.id] ? "rgba(201,166,75,0.08)" : "transparent",
              fontSize: 11, color: C.text,
            }}
          >
            <input
              type="checkbox"
              checked={!!toggles[t.id]}
              onChange={() => toggle(t.id)}
              style={{ accentColor: C.gold }}
            />
            <span style={{
              width: 10, height: 10, borderRadius: 3,
              background: t.swatch, flexShrink: 0, border: "1px solid rgba(0,0,0,0.12)",
            }} />
            <span style={{ fontWeight: toggles[t.id] ? 700 : 500 }}>
              {t.label}
            </span>
          </label>
        ))}
      </div>

      {/* ── Small info strip (bottom-right) ──────────────────────────── */}
      <div style={{
        position: "absolute", bottom: 32, right: 12, zIndex: 4,
        background: "rgba(255,255,255,0.94)",
        border: `1px solid ${C.border}`,
        borderRadius: 6,
        padding: "5px 10px",
        fontSize: 10,
        color: C.textDim,
        fontFamily: "'JetBrains Mono', monospace",
      }}>
        {substations.length.toLocaleString()} subs · {deckLayers.length} layers
      </div>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════
 * Resources tab
 * ═══════════════════════════════════════════════════════════════════ */
function ResourcesView() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const [nged, ltds, neso, dno] = await Promise.allSettled([
          api.nged.headroomStats(),
          api.ltds.stats(),
          api.gu.dnoStatus(),
          api.gu.dnoAdapters(),
        ]);
        setStats({
          nged:  nged.status === "fulfilled" ? nged.value : null,
          ltds:  ltds.status === "fulfilled" ? ltds.value : null,
          neso:  neso.status === "fulfilled" ? neso.value : null,
          dnoAdapters: dno.status === "fulfilled" ? dno.value : null,
        });
      } catch {}
    })();
  }, []);

  const link = (href, label) => (
    <a href={href} target="_blank" rel="noreferrer" style={{ color: C.blue, textDecoration: "none", fontSize: 11 }}>
      {label} ↗
    </a>
  );

  return (
    <div style={{ padding: 28, overflowY: "auto", height: "100%" }}>
      <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800 }}>Data Sources & Licences</h2>
      <p style={{ fontSize: 12, color: C.textDim, marginTop: 4, marginBottom: 22, maxWidth: 700 }}>
        Princeps ingests every major UK grid open-data feed. Underlying licences and source links below.
      </p>

      {stats?.nged && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: C.textDim, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
            Current ingest state
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10 }}>
            <StatCard label="Substations (live)" value={stats.nged.n_substations} />
            <StatCard label="MW demand headroom" value={Math.round((stats.nged.total_demand_headroom_mw || 0) / 1000) + "k"} />
            <StatCard label="MW gen headroom" value={Math.round((stats.nged.total_gen_headroom_mw || 0) / 1000) + "k"} />
            {stats.ltds && <StatCard label="LTDS CIM substations" value={stats.ltds.totals?.substations || 0} />}
            {stats.ltds && <StatCard label="LTDS AC lines" value={stats.ltds.totals?.ac_lines || 0} />}
            {stats.ltds && <StatCard label="LTDS transformers" value={stats.ltds.totals?.transformers || 0} />}
          </div>
        </div>
      )}

      <div style={{ fontSize: 11, fontWeight: 700, color: C.textDim, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
        Primary sources
      </div>
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 16 }}>
        <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
          <tbody>
            <ResRow src="NGED Connected Data" doc="LTDS CIM Stage 1.3 + DNO open data" licence="NGED Open Data" href="https://connecteddata.nationalgrid.co.uk" />
            <ResRow src="UK Power Networks" doc="OpenDataSoft — 100+ datasets" licence="UKPN Open Data" href="https://ukpowernetworks.opendatasoft.com" />
            <ResRow src="SP Energy Networks" doc="LTDS CIM EQ SPD+SPM + open data" licence="SPEN Open Data" href="https://spenergynetworks.opendatasoft.com" />
            <ResRow src="Northern Powergrid" doc="LTDS CIM + open data" licence="NPG Open Data" href="https://northernpowergrid.opendatasoft.com" />
            <ResRow src="Electricity North West" doc="Open data portal" licence="ENWL Open Data" href="https://electricitynorthwest.opendatasoft.com" />
            <ResRow src="NESO (ESO)" doc="FES, TEC, BMRS, DFS, carbon, constraint costs" licence="NESO Open" href="https://api.neso.energy" />
            <ResRow src="Elexon BMRS" doc="Wholesale prices, generation, demand" licence="Elexon Open" href="https://data.elexon.co.uk" />
            <ResRow src="Ofgem" doc="RIIO-T3 Final Determinations Dec 2025" licence="Crown Copyright" href="https://www.ofgem.gov.uk" />
            <ResRow src="NESO NIA2_NESO098" doc="DC Optimisation methodology" licence="Smarter Networks Portal" href="https://smarter.energynetworks.org" />
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: 22, fontSize: 10, color: C.textMuted, fontStyle: "italic", lineHeight: 1.5 }}>
        Princeps aggregates across all 6 UK DNOs + NESO + Elexon + Ofgem. When authenticated access is required (UKPN, SPEN, ENWL),
        Princeps uses a per-DNO API key pattern in its <code>.env</code> configuration.
      </div>
    </div>
  );
}


function StatCard({ label, value }) {
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12 }}>
      <div style={{ fontSize: 22, fontWeight: 800, fontFamily: "'JetBrains Mono', monospace" }}>
        {typeof value === "number" ? value.toLocaleString() : value}
      </div>
      <div style={{ fontSize: 9, color: C.textMuted, marginTop: 2, textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
      </div>
    </div>
  );
}


function ResRow({ src, doc, licence, href }) {
  return (
    <tr style={{ borderBottom: `1px solid ${C.border}` }}>
      <td style={{ padding: "10px 0", fontWeight: 700 }}>{src}</td>
      <td style={{ padding: "10px 10px", color: C.textDim }}>{doc}</td>
      <td style={{ padding: "10px 10px", color: C.textMuted, fontSize: 10 }}>{licence}</td>
      <td style={{ padding: "10px 0", textAlign: "right" }}>
        <a href={href} target="_blank" rel="noreferrer" style={{ color: C.blue, textDecoration: "none", fontSize: 10 }}>
          view ↗
        </a>
      </td>
    </tr>
  );
}
