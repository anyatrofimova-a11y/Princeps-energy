/**
 * DatasetsCatalog — Magritte dataset registry catalogue.
 *
 * Surfaces every connector registered in the backend `princeps_datasets`
 * table. One row per dataset: slug, title, license, last refresh,
 * row-count and a health pill (green / yellow / red / unknown). The
 * refresh button POSTs to /api/datasets/{slug}/refresh and the table
 * polls until the row's last_refreshed_at advances.
 *
 * Mounted at /v2/datasets inside the AppShell wrapper (see main.jsx).
 *
 * This page deliberately uses inline styles + the Princeps design
 * tokens (cream / gold / DM Sans / JetBrains Mono) rather than a
 * styling lib so it survives the codebase's mixed CSS state.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";

const C = {
  cream:        "#FBF8F2",
  ink:          "#0F1318",
  body:         "#3A3F46",
  muted:        "#6B7280",
  border:       "#E7DFC8",
  borderSoft:   "rgba(245,183,49,0.18)",
  gold:         "#F5B731",
  goldDeep:     "#C8951E",
  goldSurface:  "rgba(245,183,49,0.10)",
  green:        "#1F8A4C",
  greenSurface: "rgba(31,138,76,0.12)",
  amber:        "#B5750C",
  amberSurface: "rgba(245,183,49,0.16)",
  red:          "#B91C1C",
  redSurface:   "rgba(185,28,28,0.10)",
  greySurface:  "rgba(107,114,128,0.10)",
  shadow:       "0 1px 2px rgba(15,19,24,0.04), 0 8px 24px rgba(15,19,24,0.06)",
};

const FONT_DISPLAY = "'DM Sans', -apple-system, system-ui, sans-serif";
const FONT_MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace";

const HEALTH_TONE = {
  green:   { dot: C.green,   bg: C.greenSurface, label: "Healthy" },
  yellow:  { dot: C.amber,   bg: C.amberSurface, label: "Stale" },
  red:     { dot: C.red,     bg: C.redSurface,   label: "Failing" },
  unknown: { dot: C.muted,   bg: C.greySurface,  label: "Unknown" },
};

function formatRelative(iso) {
  if (!iso) return "—";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return "—";
  const ageMs = Date.now() - dt.getTime();
  const ageH = ageMs / 3_600_000;
  if (ageH < 1) return `${Math.max(0, Math.round(ageMs / 60_000))} min ago`;
  if (ageH < 24) return `${Math.round(ageH)} h ago`;
  return `${Math.round(ageH / 24)} d ago`;
}

function formatRows(n) {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function HealthPill({ status, error }) {
  const tone = HEALTH_TONE[status] || HEALTH_TONE.unknown;
  return (
    <span
      title={error || tone.label}
      style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        padding: "3px 10px 3px 8px", borderRadius: 999,
        background: tone.bg, color: C.ink, fontSize: 11, fontWeight: 600,
        fontFamily: FONT_DISPLAY, letterSpacing: 0.1,
      }}
    >
      <span style={{
        width: 8, height: 8, borderRadius: 999, background: tone.dot,
      }} />
      {tone.label}
    </span>
  );
}

export default function DatasetsCatalog() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [pendingSlug, setPendingSlug] = useState(null);

  const fetchDatasets = useCallback(async () => {
    try {
      const r = await fetch("/api/datasets", { credentials: "include" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setRows(Array.isArray(data?.datasets) ? data.datasets : []);
      setError(null);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchDatasets(); }, [fetchDatasets]);

  const refreshDataset = useCallback(async (slug) => {
    setPendingSlug(slug);
    try {
      const r = await fetch(`/api/datasets/${slug}/refresh`, {
        method: "POST", credentials: "include",
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      // Poll the catalogue every 1.5s for up to 30s — when the row's
      // last_refreshed_at advances, the refresh has landed. Worst case
      // this just refetches without any change.
      let prev = rows.find((d) => d.slug === slug)?.last_refreshed_at || null;
      for (let i = 0; i < 20; i++) {
        await new Promise((res) => setTimeout(res, 1500));
        const r2 = await fetch("/api/datasets", { credentials: "include" });
        if (r2.ok) {
          const d2 = await r2.json();
          const next = (d2?.datasets || []).find((d) => d.slug === slug);
          if (next && next.last_refreshed_at !== prev) {
            setRows(d2.datasets || []);
            return;
          }
        }
      }
      // Fall through — refetch once at the end so we don't leave the UI
      // wedged with `pendingSlug` if the run is unusually long.
      await fetchDatasets();
    } catch (e) {
      console.error("refresh failed", e);
      alert(`Refresh failed: ${e.message || e}`);
    } finally {
      setPendingSlug(null);
    }
  }, [rows, fetchDatasets]);

  const sorted = useMemo(() => {
    return [...rows].sort((a, b) => {
      // Failing first, then yellow, green, unknown — same order the user
      // wants to triage in.
      const order = { red: 0, yellow: 1, green: 2, unknown: 3 };
      const ra = order[a.health_status] ?? 3;
      const rb = order[b.health_status] ?? 3;
      if (ra !== rb) return ra - rb;
      return (a.title || "").localeCompare(b.title || "");
    });
  }, [rows]);

  return (
    <div style={{
      minHeight: "100vh", background: C.cream, color: C.ink,
      fontFamily: FONT_DISPLAY, padding: "32px 40px",
    }}>
      <header style={{ marginBottom: 24 }}>
        <h1 style={{
          fontSize: 22, fontWeight: 600, margin: "0 0 4px",
          letterSpacing: -0.2,
        }}>
          Datasets
        </h1>
        <p style={{ fontSize: 13, color: C.body, margin: 0, maxWidth: 640 }}>
          Magritte connector registry. One row per typed connector, one
          source of truth for freshness. License-blocked sources never
          enter this catalogue.
        </p>
      </header>

      {loading && (
        <div style={{ fontSize: 13, color: C.muted }}>Loading catalogue…</div>
      )}
      {error && (
        <div style={{
          padding: 12, borderRadius: 8, background: C.redSurface, color: C.red,
          fontSize: 13, marginBottom: 16,
        }}>
          Failed to load datasets: {error}
        </div>
      )}
      {!loading && !error && sorted.length === 0 && (
        <div style={{
          padding: 32, borderRadius: 12, background: "white",
          border: `1px solid ${C.border}`, boxShadow: C.shadow,
          color: C.muted, fontSize: 14, textAlign: "center",
        }}>
          No datasets registered yet. Connector subclasses register
          themselves at app boot — re-deploy or restart the API to pick up
          new sources.
        </div>
      )}

      {!loading && sorted.length > 0 && (
        <div style={{
          background: "white", border: `1px solid ${C.border}`, borderRadius: 12,
          boxShadow: C.shadow, overflow: "hidden",
        }}>
          <table style={{
            width: "100%", borderCollapse: "collapse", fontSize: 13,
          }}>
            <thead>
              <tr style={{
                background: C.goldSurface, color: C.ink, textAlign: "left",
              }}>
                <th style={thStyle}>Slug</th>
                <th style={thStyle}>Title</th>
                <th style={thStyle}>License</th>
                <th style={thStyle}>Cadence</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Rows</th>
                <th style={thStyle}>Last refreshed</th>
                <th style={thStyle}>Health</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Refresh</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((d) => {
                const isPending = pendingSlug === d.slug;
                return (
                  <tr key={d.slug} style={{ borderTop: `1px solid ${C.border}` }}>
                    <td style={tdStyle}>
                      <code style={{ fontFamily: FONT_MONO, fontSize: 12 }}>
                        {d.slug}
                      </code>
                    </td>
                    <td style={tdStyle}>
                      <div style={{ fontWeight: 600 }}>{d.title}</div>
                      {d.source_url && (
                        <a
                          href={d.source_url} target="_blank" rel="noreferrer"
                          style={{
                            fontSize: 11, color: C.goldDeep, textDecoration: "none",
                            fontFamily: FONT_MONO,
                          }}
                        >
                          {(() => {
                            try { return new URL(d.source_url).hostname; }
                            catch { return d.source_url; }
                          })()}
                        </a>
                      )}
                    </td>
                    <td style={tdStyle}>
                      <span style={{
                        fontFamily: FONT_MONO, fontSize: 11, color: C.body,
                      }}>{d.license || "—"}</span>
                    </td>
                    <td style={tdStyle}>{d.refresh_cadence || "—"}</td>
                    <td style={{ ...tdStyle, textAlign: "right",
                                 fontFamily: FONT_MONO }}>
                      {formatRows(d.last_row_count)}
                    </td>
                    <td style={{ ...tdStyle, fontFamily: FONT_MONO,
                                 fontSize: 11, color: C.body }}>
                      {formatRelative(d.last_refreshed_at)}
                    </td>
                    <td style={tdStyle}>
                      <HealthPill
                        status={d.health_status}
                        error={d.last_refresh_error}
                      />
                    </td>
                    <td style={{ ...tdStyle, textAlign: "right" }}>
                      <button
                        onClick={() => refreshDataset(d.slug)}
                        disabled={isPending || !d.runnable}
                        title={
                          d.runnable
                            ? "Trigger Connector.ingest()"
                            : "No connector class registered for this slug"
                        }
                        style={{
                          padding: "5px 12px", borderRadius: 6,
                          border: `1px solid ${C.borderSoft}`,
                          background: isPending ? C.greySurface : C.gold,
                          color: isPending ? C.muted : C.ink,
                          fontSize: 11, fontWeight: 600, fontFamily: FONT_DISPLAY,
                          cursor: isPending || !d.runnable ? "default" : "pointer",
                          opacity: !d.runnable ? 0.4 : 1,
                        }}
                      >
                        {isPending ? "Refreshing…" : "Refresh"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const thStyle = {
  padding: "10px 12px", fontSize: 11, fontWeight: 600,
  textTransform: "uppercase", letterSpacing: 0.4,
  color: C.body,
};

const tdStyle = {
  padding: "10px 12px", verticalAlign: "top", color: C.ink,
};
