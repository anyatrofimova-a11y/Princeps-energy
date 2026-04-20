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
import api from "../../services/api";
import { useSite } from "../../SiteContext";
import GridAssetDrawer from "./GridAssetDrawer";

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

const VOLTAGE_BUCKETS = [400, 275, 132, 66, 33, 22, 11];
const DNOS = ["UKPN", "NGED", "SSEN", "SPEN", "ENWL", "NPG"];

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
  pill: (active, colour = C.gold) => ({
    padding: "3px 9px",
    fontSize: 10,
    fontWeight: 700,
    background: active ? colour : "transparent",
    color: active ? "#fff" : C.textDim,
    border: `1px solid ${active ? colour : C.border}`,
    borderRadius: 10,
    cursor: "pointer",
    fontFamily: "inherit",
    letterSpacing: 0.3,
    transition: "all 0.12s",
  }),
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
  const { pickedLocation, setPickedLocation } = useSite();

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
        const nearest = VOLTAGE_BUCKETS.reduce((p, c) =>
          Math.abs(c - (s.voltage_kv || 0)) < Math.abs(p - (s.voltage_kv || 0)) ? c : p
        );
        if (!voltageFilter.has(nearest)) return false;
      }
      if (dnoFilter.size > 0 && !dnoFilter.has(s.dno)) return false;
      if (q && !(s.name || "").toLowerCase().includes(q)) return false;
      return true;
    });
  }, [substations, search, voltageFilter, dnoFilter]);

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
  };

  const hasFilters = voltageFilter.size > 0 || dnoFilter.size > 0 || search;
  const resetFilters = () => {
    setVoltageFilter(new Set()); setDnoFilter(new Set()); setSearch("");
  };

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
                {VOLTAGE_BUCKETS.map(v => (
                  <button
                    key={v}
                    style={S.pill(voltageFilter.has(v), C.gold)}
                    onClick={() => toggleVoltage(v)}
                  >
                    {v}kV
                  </button>
                ))}
              </div>
            </div>
            <div style={S.filterBlock}>
              <span style={S.filterLabel}>DNO</span>
              <div style={S.pillRow}>
                {DNOS.map(d => (
                  <button
                    key={d}
                    style={S.pill(dnoFilter.has(d), C.goldDark)}
                    onClick={() => toggleDno(d)}
                  >
                    {d}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <VirtualList
            items={filtered}
            selection={selection}
            onSelect={handleRowClick}
            loading={loading}
          />
        </aside>

        {/* CENTER — active sub-view; map is the hero when active */}
        <div style={S.center}>
          {activeTab === "browse"    && <BrowseView substations={substations} filtered={filtered} onSelect={handleRowClick} />}
          {activeTab === "map"       && mapContent}
          {activeTab === "graph"     && <GraphView substations={filtered} selection={selection} onSelect={handleRowClick} />}
          {activeTab === "table"     && <TableView substations={filtered} onSelect={handleRowClick} />}
          {activeTab === "resources" && <ResourcesView />}
        </div>

        {/* RIGHT — full-height drawer shell (clearly-marked slots for BOT-Z3) */}
        {selection && (
          <GridAssetDrawer
            selection={selection}
            onClose={() => setSelection(null)}
          />
        )}
      </div>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════
 * Hand-rolled virtualized list (avoids adding react-window as a dep)
 * ═══════════════════════════════════════════════════════════════════ */
function VirtualList({ items, selection, onSelect, loading }) {
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
    return <div style={{ padding: 20, color: C.textMuted, fontSize: 12, textAlign: "center" }}>No matches</div>;
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
 * Graph tab — GEOGRAPHIC projection view.
 * Substations rendered at their real lat/lon (Mercator-ish).
 * The UK outline emerges from the substation density.
 * Coloured by DNO by default; fallback to headroom RAG.
 * ═══════════════════════════════════════════════════════════════════ */
const DNO_COLOURS = {
  UKPN:  "#3b82f6",
  NGED:  "#10b981",
  SSEN:  "#a855f7",
  SPEN:  "#f59e0b",
  ENWL:  "#06b6d4",
  NPG:   "#ef4444",
};

function GraphView({ substations, selection, onSelect }) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [hover, setHover] = useState(null);
  const [colourBy, setColourBy] = useState("dno"); // 'dno' | 'rag'

  // Resize
  useEffect(() => {
    const update = () => {
      const el = containerRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      setSize({ w: r.width, h: r.height });
      const c = canvasRef.current;
      if (c) {
        const dpr = window.devicePixelRatio || 1;
        c.width = r.width * dpr;
        c.height = r.height * dpr;
        c.style.width = r.width + "px";
        c.style.height = r.height + "px";
        c.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0);
      }
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  // Projection: scale UK bounding box (lat 49.8-59 / lon -8 to 2) to canvas
  const projected = useMemo(() => {
    if (!substations.length || !size.w) return [];
    const withCoords = substations.filter(s => s.lat != null && s.lon != null);
    // UK-focused bounds
    const minLat = 49.8, maxLat = 59.0, minLon = -8.5, maxLon = 2.0;
    const pad = 30;
    const latRange = maxLat - minLat, lonRange = maxLon - minLon;
    const aspect = (lonRange * Math.cos(54 * Math.PI / 180)) / latRange;
    let usableW = size.w - pad * 2;
    let usableH = size.h - pad * 2;
    if (usableW / usableH > aspect) usableW = usableH * aspect;
    else usableH = usableW / aspect;
    const offsetX = (size.w - usableW) / 2;
    const offsetY = (size.h - usableH) / 2;
    return withCoords.map(s => {
      const x = offsetX + ((s.lon - minLon) / lonRange) * usableW;
      const y = offsetY + ((maxLat - s.lat) / latRange) * usableH;
      return { ...s, _x: x, _y: y };
    });
  }, [substations, size]);

  // Draw
  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, size.w, size.h);

    // Background
    ctx.fillStyle = "#f1f5f9";
    ctx.fillRect(0, 0, size.w, size.h);

    // Faint grid lines
    ctx.strokeStyle = "rgba(148,163,184,0.15)";
    ctx.lineWidth = 1;
    for (let x = 50; x < size.w; x += 80) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, size.h); ctx.stroke();
    }
    for (let y = 50; y < size.h; y += 80) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(size.w, y); ctx.stroke();
    }

    // Draw points
    for (const s of projected) {
      const r = Math.max(1.5, Math.min(5, 2 + (s.voltage_kv || 0) / 100));
      const colour = colourBy === "dno"
        ? (DNO_COLOURS[s.dno] || "#94a3b8")
        : (s.colour || "#94a3b8");
      ctx.beginPath();
      ctx.arc(s._x, s._y, r, 0, Math.PI * 2);
      ctx.fillStyle = colour;
      ctx.globalAlpha = 0.75;
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    // Highlight hover
    if (hover) {
      ctx.beginPath();
      ctx.arc(hover._x, hover._y, 8, 0, Math.PI * 2);
      ctx.strokeStyle = "#0f172a";
      ctx.lineWidth = 2;
      ctx.stroke();
    }
  }, [projected, size, hover, colourBy]);

  const handleMove = (e) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    let best = null;
    let bestD = 8;
    for (const s of projected) {
      const d = Math.hypot(s._x - mx, s._y - my);
      if (d < bestD) { best = s; bestD = d; }
    }
    setHover(best);
  };

  const handleClick = () => {
    if (hover) onSelect(hover);
  };

  const dnoCounts = useMemo(() => {
    const m = {};
    for (const s of projected) m[s.dno || "OTHER"] = (m[s.dno || "OTHER"] || 0) + 1;
    return m;
  }, [projected]);

  return (
    <div ref={containerRef} style={{ width: "100%", height: "100%", position: "relative", background: "#f1f5f9" }}>
      <canvas
        ref={canvasRef}
        style={{ display: "block", cursor: hover ? "pointer" : "default" }}
        onMouseMove={handleMove}
        onMouseLeave={() => setHover(null)}
        onClick={handleClick}
      />

      {/* Info overlay (top-left) */}
      <div style={{
        position: "absolute", top: 14, left: 14,
        background: "rgba(255,255,255,0.96)",
        padding: "10px 14px", borderRadius: 8, fontSize: 11,
        boxShadow: "0 1px 4px rgba(15,23,42,0.12)",
        border: `1px solid ${C.border}`,
      }}>
        <div style={{ fontWeight: 800, fontSize: 13, marginBottom: 4 }}>
          UK Grid Topology
        </div>
        <div style={{ color: C.textDim, fontSize: 10 }}>
          {projected.length.toLocaleString()} substations · geographic projection
        </div>
        <div style={{ marginTop: 8, display: "flex", gap: 4 }}>
          <button
            style={{
              ...S.pill(colourBy === "dno", C.purple),
              fontSize: 9,
            }}
            onClick={() => setColourBy("dno")}
          >By DNO</button>
          <button
            style={{
              ...S.pill(colourBy === "rag", C.blue),
              fontSize: 9,
            }}
            onClick={() => setColourBy("rag")}
          >By headroom</button>
        </div>
      </div>

      {/* DNO legend (bottom-left) */}
      {colourBy === "dno" && (
        <div style={{
          position: "absolute", bottom: 14, left: 14,
          background: "rgba(255,255,255,0.96)",
          padding: "10px 14px", borderRadius: 8, fontSize: 10,
          boxShadow: "0 1px 4px rgba(15,23,42,0.12)",
          border: `1px solid ${C.border}`,
          display: "flex", gap: 14, flexWrap: "wrap", maxWidth: 560,
        }}>
          {Object.entries(DNO_COLOURS).map(([dno, colour]) => (
            <div key={dno} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 10, height: 10, borderRadius: 5, background: colour }} />
              <span style={{ fontWeight: 700 }}>{dno}</span>
              <span style={{ color: C.textDim, fontFamily: "'JetBrains Mono', monospace" }}>
                {(dnoCounts[dno] || 0).toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Hover tooltip */}
      {hover && (
        <div style={{
          position: "absolute",
          top: hover._y - 50,
          left: hover._x + 12,
          background: "rgba(15,23,42,0.96)",
          color: "#fff",
          padding: "8px 12px",
          borderRadius: 6,
          fontSize: 11,
          pointerEvents: "none",
          maxWidth: 240,
          boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
        }}>
          <div style={{ fontWeight: 700, marginBottom: 3 }}>
            {hover.name || hover.external_id || "Unnamed"}
          </div>
          <div style={{ fontSize: 10, color: "#94a3b8" }}>
            {hover.dno} · {Math.round(hover.voltage_kv)} kV
            {hover.site_type && ` · ${hover.site_type}`}
          </div>
          {hover.headroom_mw != null && (
            <div style={{ fontSize: 10, color: "#10b981", marginTop: 3, fontFamily: "'JetBrains Mono', monospace" }}>
              {Math.round(hover.headroom_mw)} MW headroom
            </div>
          )}
        </div>
      )}
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
