/**
 * GridModelExplorer — Princeps Grid Model Explorer.
 *
 * A Squid-equivalent surface over the NGED LTDS CIM data ingested into
 * Postgres. Substation search left, busbar-level React Flow circuit
 * centre, asset details right.
 *
 * Wires the left search → GridModelContext.selectSubstation; the context
 * auto-loads CIM data via api.grid.circuit() which now hits the
 * /api/ltds/substations/{mrid}/circuit endpoint. GridCircuitView reads
 * cimData from the same context.
 */

import React, { useEffect, useState } from "react";
import { GridModelProvider, useGridModel } from "../../contexts/GridModelContext";
import { WorkspaceProvider } from "../../contexts/WorkspaceContext";
import { SiteProvider } from "../../SiteContext";
import GridCircuitView from "../../components/grid/GridCircuitView";
import api from "../../services/api";
import "./grid-model-explorer.css";

const REGION_LABELS = {
  east_midlands: "East Midlands",
  west_midlands: "West Midlands",
  south_west: "South West",
  south_wales: "South Wales",
};

function VoltageBadge({ kv }) {
  const n = Number(kv) || 0;
  const colour =
    n >= 400 ? "#B54EB2" :
    n >= 275 ? "#C73030" :
    n >= 132 ? "#B59F10" :
    n >= 66  ? "#55B555" :
    n >= 25  ? "#6E97B8" :
               "#7A7A85";
  return (
    <span className="gme-kv" style={{ background: colour }}>
      {n ? `${n} kV` : "—"}
    </span>
  );
}

function AssetCountChip({ label, count }) {
  return (
    <div className="gme-chip">
      <div className="gme-chip-label">{label}</div>
      <div className="gme-chip-count">{count ?? "—"}</div>
    </div>
  );
}

function GridModelExplorerInner() {
  const { selectedSubstation, selectSubstation, cimData } = useGridModel();
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [neighbours, setNeighbours] = useState([]);

  // Debounced search
  useEffect(() => {
    if (query.length < 2) {
      setSuggestions([]);
      return;
    }
    const id = setTimeout(async () => {
      try {
        const results = await api.grid.circuitSearch(query);
        setSuggestions((results || []).slice(0, 20));
      } catch {
        setSuggestions([]);
      }
    }, 250);
    return () => clearTimeout(id);
  }, [query]);

  // Fetch neighbours when a substation is selected via context
  useEffect(() => {
    const subId = selectedSubstation?.id;
    if (!subId) { setNeighbours([]); return; }
    let cancelled = false;
    (async () => {
      try {
        const url = `/api/ltds/substations/${encodeURIComponent(subId)}/connections`;
        const r = await fetch(url);
        if (!r.ok) { if (!cancelled) setNeighbours([]); return; }
        const data = await r.json();
        if (!cancelled) setNeighbours(data.neighbours || []);
      } catch {
        if (!cancelled) setNeighbours([]);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedSubstation?.id]);

  function handleSelect(sub) {
    setQuery(sub.name);
    setSuggestions([]);
    selectSubstation({
      id: sub.id,
      name: sub.name,
      voltageKv: sub.voltage_kv,
      region: sub.region,
    });
  }

  const summary = cimData?.substation;
  const assets = cimData?.assets;

  return (
    <div className="gme-shell">
      {/* ── Left: search + suggestions ─────────────────────────────── */}
      <aside className="gme-left">
        <div className="gme-brand">
          <strong>PRINCEPS</strong> · Grid Model Explorer
        </div>
        <div className="gme-search-wrap">
          <input
            type="text"
            placeholder="Search 2,059 NGED substations…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="gme-search"
            autoFocus
          />
          {suggestions.length > 0 && (
            <ul className="gme-suggestions">
              {suggestions.map((s) => (
                <li key={s.id} onClick={() => handleSelect(s)}>
                  <VoltageBadge kv={s.voltage_kv} />
                  <span className="gme-suggest-name">{s.name}</span>
                  <span className="gme-suggest-region">
                    {REGION_LABELS[s.region] || s.region}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="gme-help">
          NGED LTDS CIM (Open Data Licence v1.0).
          <br />
          Try: <em>Tavistock</em>, <em>Newton Abbot</em>, <em>Pyworthy</em>.
        </div>

        {neighbours.length > 0 && (
          <div className="gme-neighbours">
            <div className="gme-section-title">
              Connections ({neighbours.length})
            </div>
            <ul>
              {neighbours.slice(0, 12).map((n, i) => (
                <li key={i}>
                  <span className="gme-neighbour-line">{n.ac_name}</span>
                  <span className="gme-neighbour-far">{n.neighbour_name}</span>
                  {n.length_m != null && (
                    <span className="gme-neighbour-len">
                      {(Number(n.length_m) / 1000).toFixed(2)} km
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </aside>

      {/* ── Centre: React Flow circuit diagram ─────────────────────── */}
      <main className="gme-centre">
        {!selectedSubstation && (
          <div className="gme-empty">
            <h2>Princeps Grid Model</h2>
            <p>
              NGED LTDS CIM ingested:{" "}
              <strong>2,059 substations</strong> ·{" "}
              <strong>19,889 busbars</strong> ·{" "}
              <strong>5,085 AC line segments</strong> ·{" "}
              <strong>2,584 transformers</strong> ·{" "}
              <strong>72,587 terminals</strong>.
            </p>
            <p className="gme-empty-hint">
              Search a substation on the left to load its busbar-level
              circuit diagram.
            </p>
          </div>
        )}
        {selectedSubstation && <GridCircuitView />}
      </main>

      {/* ── Right: substation details ──────────────────────────────── */}
      <aside className="gme-right">
        {!summary && (
          <div className="gme-empty-right">No substation selected.</div>
        )}
        {summary && (
          <>
            <div className="gme-detail-head">
              <h3>{summary.name}</h3>
              <div className="gme-detail-tags">
                {summary.psr_type && (
                  <span className="gme-tag">{summary.psr_type}</span>
                )}
                {summary.dno && <span className="gme-tag">{summary.dno}</span>}
                {summary.licence_area && (
                  <span className="gme-tag">{summary.licence_area}</span>
                )}
              </div>
            </div>

            {Array.isArray(summary.voltage_levels) && summary.voltage_levels.length > 0 && (
              <div className="gme-section">
                <div className="gme-section-title">Voltage levels</div>
                {summary.voltage_levels.map((v) => (
                  <div className="gme-voltage-row" key={v.mrid}>
                    <VoltageBadge kv={v.voltage_kv} />
                    <span>{v.name}</span>
                  </div>
                ))}
              </div>
            )}

            <div className="gme-section">
              <div className="gme-section-title">Asset counts</div>
              <div className="gme-chips">
                <AssetCountChip label="Busbars"           count={assets?.busbars} />
                <AssetCountChip label="Transformers"      count={assets?.transformers} />
                <AssetCountChip label="Switches"          count={assets?.switches} />
                <AssetCountChip label="Generators"        count={assets?.generators} />
                <AssetCountChip label="Loads"             count={assets?.loads} />
                <AssetCountChip label="Equiv. injections" count={assets?.equivalent_injections} />
                <AssetCountChip label="Incoming lines"    count={assets?.ac_lines_incoming} />
                <AssetCountChip label="Connectivity"      count={assets?.connectivity_nodes} />
                <AssetCountChip label="Terminals"         count={assets?.terminals} />
              </div>
            </div>

            {Array.isArray(cimData?.transformer_ends) && cimData.transformer_ends.length > 0 && (
              <div className="gme-section">
                <div className="gme-section-title">Transformer windings</div>
                <table className="gme-table">
                  <thead>
                    <tr>
                      <th>End</th><th>Rated U (kV)</th><th>Rated S (MVA)</th>
                      <th>R (Ω)</th><th>X (Ω)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cimData.transformer_ends.map((t) => (
                      <tr key={t.mrid}>
                        <td>{t.end_number}</td>
                        <td>{t.rated_u_kv ?? "—"}</td>
                        <td>{t.rated_s_mva ?? "—"}</td>
                        <td>{t.r_ohm ?? "—"}</td>
                        <td>{t.x_ohm ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {cimData?.attribution && (
              <div className="gme-attribution">{cimData.attribution}</div>
            )}
          </>
        )}
      </aside>
    </div>
  );
}

export default function GridModelExplorer() {
  return (
    <SiteProvider>
      <WorkspaceProvider>
        <GridModelProvider>
          <GridModelExplorerInner />
        </GridModelProvider>
      </WorkspaceProvider>
    </SiteProvider>
  );
}
