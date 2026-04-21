/**
 * DnoLegend — bottom-left context pane (320 px) that reacts to useDnoFilter.
 *
 * When the filter is in 'all' mode the pane is collapsed to a single-line
 * hint. When one or more DNOs are active, the pane expands to show:
 *
 *   • DNO accent swatch + display name
 *   • Operator class (DNO | IDNO | TO)
 *   • List of sub-regions (licence_region → display_name)
 *   • Effective-date footnote when meaningful
 *
 * Sub-region info is pulled from ``GET /api/dno/{slug}`` (see dno.py).
 */

import React, { useEffect, useMemo, useRef, useState } from "react";
import palette from "../../data/dno-palette.json";
import useDnoFilter from "../../hooks/useDnoFilter";

// ── Styles ──────────────────────────────────────────────────────────────────
const paneStyle = {
  position: "absolute",
  left:     12,
  bottom:   12,
  width:    320,
  maxHeight: "58vh",
  overflow: "auto",
  background: "rgba(16, 16, 18, 0.82)",
  border:     "1px solid rgba(255, 255, 255, 0.08)",
  borderRadius: 10,
  padding: "10px 12px",
  color: "rgba(255, 255, 255, 0.86)",
  font:  "12px/1.4 ui-sans-serif, system-ui, sans-serif",
  backdropFilter: "blur(8px)",
  WebkitBackdropFilter: "blur(8px)",
  boxShadow: "0 6px 24px rgba(0,0,0,0.30)",
  pointerEvents: "auto",
  zIndex: 3,
};

const headerRow = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  marginBottom: 6,
};

const swatchStyle = (accent) => ({
  width: 12,
  height: 12,
  borderRadius: 3,
  background: accent || "#666",
  boxShadow: "0 0 0 1px rgba(0,0,0,0.4)",
  flex: "none",
});

const titleStyle = {
  fontSize: 13,
  fontWeight: 600,
  color: "rgba(255,255,255,0.94)",
  lineHeight: 1.25,
};

const classPill = (cls) => ({
  display: "inline-block",
  padding: "1px 6px",
  borderRadius: 999,
  fontSize: 10,
  fontWeight: 600,
  letterSpacing: 0.2,
  marginLeft: "auto",
  background: cls === "TO" ? "rgba(107, 63, 160, 0.18)"
            : cls === "IDNO" ? "rgba(46, 139, 139, 0.18)"
            : "rgba(245, 183, 49, 0.18)",
  color:       cls === "TO" ? "#B898DD"
            : cls === "IDNO" ? "#6BC7C7"
            : "#F5B731",
  border: "1px solid rgba(255,255,255,0.08)",
});

const regionLine = {
  padding: "4px 0",
  borderBottom: "1px dashed rgba(255,255,255,0.08)",
  display: "flex",
  justifyContent: "space-between",
  gap: 8,
};

const regionLabel = {
  color: "rgba(255,255,255,0.9)",
  fontSize: 12,
};

const regionMeta = {
  color: "rgba(255,255,255,0.55)",
  fontSize: 11,
  whiteSpace: "nowrap",
};

const hintStyle = {
  color: "rgba(255,255,255,0.55)",
  fontSize: 11,
  fontStyle: "italic",
};

// ── Fetch + cache ──────────────────────────────────────────────────────────
const _detailCache = new Map();  // slug -> Promise<detail>

function fetchDnoDetail(slug) {
  if (_detailCache.has(slug)) return _detailCache.get(slug);
  const p = fetch(`/api/dno/${encodeURIComponent(slug)}`, { credentials: "include" })
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null);
  _detailCache.set(slug, p);
  return p;
}

// ── Component ──────────────────────────────────────────────────────────────
export default function DnoLegend() {
  const { activeDnos, mode } = useDnoFilter();
  const activeList = useMemo(() => Array.from(activeDnos), [activeDnos]);
  const [details, setDetails] = useState({});   // slug -> detail or null

  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);

  // Fetch details for any newly-active slugs.
  useEffect(() => {
    if (!activeList.length) return;
    let cancelled = false;
    (async () => {
      const out = { ...details };
      for (const slug of activeList) {
        if (out[slug] !== undefined) continue;
        const d = await fetchDnoDetail(slug);
        if (cancelled || !mounted.current) return;
        out[slug] = d;
      }
      if (!cancelled) setDetails(out);
    })();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeList.join("|")]);

  // ── Render ────────────────────────────────────────────────────────────
  if (mode === "all" || activeList.length === 0) {
    return (
      <div style={paneStyle} role="status" aria-live="polite">
        <div style={headerRow}>
          <span style={swatchStyle("#3a3a3a")} />
          <div style={titleStyle}>All DNO licence areas</div>
        </div>
        <div style={hintStyle}>
          Click a pill above to focus on one operator. Shift-click to compare
          multiple DNOs side-by-side.
        </div>
      </div>
    );
  }

  return (
    <div style={paneStyle} role="status" aria-live="polite">
      {activeList.map((slug) => {
        const p = palette[slug] || {};
        const detail = details[slug];
        const opClass = (detail?.operator_class || "DNO").toUpperCase();

        // Sub-regions either come from the backend or fall back to pallette label only.
        const subs = detail?.sub_regions || [];

        return (
          <div key={slug} style={{ marginBottom: activeList.length > 1 ? 10 : 0 }}>
            <div style={headerRow}>
              <span style={swatchStyle(p.accent)} />
              <div style={titleStyle}>
                {p.label || detail?.display_name || slug.toUpperCase()}
              </div>
              <span style={classPill(opClass)}>{opClass}</span>
            </div>

            {detail?.licence_region && (
              <div style={{ color: "rgba(255,255,255,0.68)", marginBottom: 6 }}>
                {detail.licence_region}
              </div>
            )}

            {subs.length > 0 ? (
              <div>
                <div style={{
                  textTransform: "uppercase",
                  letterSpacing: 0.4,
                  fontSize: 10,
                  color: "rgba(255,255,255,0.5)",
                  margin: "4px 0 2px",
                }}>
                  Sub-regions · {subs.length}
                </div>
                {subs.map((s) => (
                  <div key={s.dno_slug} style={regionLine}>
                    <span style={regionLabel}>
                      {s.licence_region || s.display_name || s.dno_slug}
                    </span>
                    <span style={regionMeta}>
                      {s.operator_class}
                      {s.effective_from ? ` · from ${s.effective_from}` : ""}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div style={hintStyle}>
                {detail ? "No sub-regions." : "Loading licence details…"}
              </div>
            )}

            {detail?.note && (
              <div style={{ ...hintStyle, marginTop: 6 }}>
                {detail.note}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
