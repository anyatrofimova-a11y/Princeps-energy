import React, { useState, useCallback } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

const TECHNOLOGIES = ["solar", "wind", "bess", "hybrid"];

const SCORE_COLORS = {
  high: "#24a148",
  medium: "#F5B731",
  low: "#da1e28",
};

function scoreColor(score) {
  if (score >= 70) return SCORE_COLORS.high;
  if (score >= 40) return SCORE_COLORS.medium;
  return SCORE_COLORS.low;
}

function fmtMw(v) { return v != null ? `${v.toFixed(1)} MW` : "--"; }
function fmtGbp(v) {
  if (v == null) return "--";
  if (v >= 1e6) return `£${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `£${(v / 1e3).toFixed(0)}k`;
  return `£${v.toFixed(0)}`;
}

export default function ProspectorV2Panel({ onClose, embedded }) {
  const { setPickedLocation, setLayers } = useSite();
  const [technology, setTechnology] = useState("solar");
  const [minCapacity, setMinCapacity] = useState(5);
  const [maxGridDist, setMaxGridDist] = useState(10);
  const [region, setRegion] = useState("south_west");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [selectedSub, setSelectedSub] = useState(null);
  const [subDetail, setSubDetail] = useState(null);
  const [subLoading, setSubLoading] = useState(false);

  const quickScan = useCallback(async () => {
    setLoading(true);
    setResults(null);
    setSelectedSub(null);
    setSubDetail(null);
    try {
      const res = await api.prospectorV2.heatmap({
        technology,
        region,
        min_capacity_mw: minCapacity,
        max_grid_distance_km: maxGridDist,
      });
      setResults(res);
      // Enable heatmap layer
      setLayers(prev => ({ ...prev, geeflowOpportunities: true }));
    } catch (e) {
      console.warn("[ProspectorV2] Scan failed:", e);
    } finally {
      setLoading(false);
    }
  }, [technology, region, minCapacity, maxGridDist, setLayers]);

  const inspectSubstation = useCallback(async (sub) => {
    setSelectedSub(sub);
    setSubLoading(true);
    try {
      const detail = await api.prospectorV2.substationDetail(sub.id || sub.name);
      setSubDetail(detail);
    } catch (e) {
      console.warn("[ProspectorV2] Substation detail failed:", e);
      setSubDetail(null);
    } finally {
      setSubLoading(false);
    }
  }, []);

  const flyToSite = useCallback((site) => {
    if (site.lat && site.lon) {
      setPickedLocation({ lat: site.lat, lon: site.lon });
    }
  }, [setPickedLocation]);

  const candidates = results?.candidates || results?.sites || [];
  const substations = results?.substations || [];

  return (
    <div className="p2-panel">
      {!embedded && (
        <div className="p2-header">
          <span className="p2-title">Site Prospector V2</span>
          <button className="p2-close" onClick={onClose}>&times;</button>
        </div>
      )}

      <div className="p2-body">
        {/* Filters */}
        <div className="p2-section">
          <div className="p2-chips">
            {TECHNOLOGIES.map(t => (
              <button key={t} className={`p2-chip${technology === t ? " active" : ""}`}
                onClick={() => setTechnology(t)}>{t}</button>
            ))}
          </div>

          <div className="p2-row">
            <div className="p2-field">
              <label className="p2-label">Region</label>
              <select className="p2-select" value={region} onChange={e => setRegion(e.target.value)}>
                <option value="south_west">South West</option>
                <option value="south_east">South East</option>
                <option value="east_midlands">East Midlands</option>
                <option value="west_midlands">West Midlands</option>
                <option value="east_anglia">East Anglia</option>
                <option value="north_west">North West</option>
                <option value="north_east">North East</option>
                <option value="scotland">Scotland</option>
                <option value="wales">Wales</option>
              </select>
            </div>
            <div className="p2-field">
              <label className="p2-label">Min Capacity (MW)</label>
              <input className="p2-input" type="number" value={minCapacity}
                onChange={e => setMinCapacity(+e.target.value)} min={1} max={500} />
            </div>
            <div className="p2-field">
              <label className="p2-label">Max Grid Dist (km)</label>
              <input className="p2-input" type="number" value={maxGridDist}
                onChange={e => setMaxGridDist(+e.target.value)} min={1} max={50} />
            </div>
          </div>

          <button className="p2-btn-primary" onClick={quickScan} disabled={loading}>
            {loading ? "Scanning..." : "Quick Scan"}
          </button>
        </div>

        {/* Substations */}
        {substations.length > 0 && (
          <div className="p2-section">
            <div className="p2-section-title">Substations ({substations.length})</div>
            <div className="p2-sub-list">
              {substations.slice(0, 8).map((sub, i) => (
                <button key={i} className={`p2-sub-btn${selectedSub?.id === sub.id ? " active" : ""}`}
                  onClick={() => inspectSubstation(sub)}>
                  <span className="p2-sub-name">{sub.name || `Sub ${i + 1}`}</span>
                  <span className="p2-sub-cap">{fmtMw(sub.headroom_mw || sub.capacity_mw)}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Substation detail */}
        {selectedSub && (
          <div className="p2-section p2-sub-detail">
            <div className="p2-section-title">{selectedSub.name || "Substation"}</div>
            {subLoading ? (
              <div className="p2-loading">Loading detail...</div>
            ) : subDetail ? (
              <div className="p2-detail-grid">
                <div className="p2-detail-row"><span>Capacity</span><span>{fmtMw(subDetail.capacity_mw)}</span></div>
                <div className="p2-detail-row"><span>Headroom</span><span>{fmtMw(subDetail.headroom_mw)}</span></div>
                <div className="p2-detail-row"><span>Queue Depth</span><span>{subDetail.queue_depth ?? "--"} projects</span></div>
                <div className="p2-detail-row"><span>Connection Cost</span><span>{fmtGbp(subDetail.connection_cost_gbp)}</span></div>
                <div className="p2-detail-row"><span>Voltage</span><span>{subDetail.voltage_kv ? `${subDetail.voltage_kv} kV` : "--"}</span></div>
                {subDetail.nearby_projects != null && (
                  <div className="p2-detail-row"><span>Nearby Projects</span><span>{subDetail.nearby_projects}</span></div>
                )}
              </div>
            ) : (
              <div className="p2-empty">No detail available</div>
            )}
          </div>
        )}

        {/* Results table */}
        {candidates.length > 0 && (
          <div className="p2-section">
            <div className="p2-section-title">Candidate Sites ({candidates.length})</div>
            <div className="p2-results-table">
              <div className="p2-table-header">
                <span>Site</span><span>Score</span><span>Capacity</span><span>Grid</span><span></span>
              </div>
              {candidates.map((site, i) => (
                <div key={i} className="p2-table-row">
                  <span className="p2-site-name">{site.name || site.label || `Site ${i + 1}`}</span>
                  <span className="p2-score" style={{ color: scoreColor(site.score || 0) }}>
                    {site.score != null ? site.score.toFixed(0) : "--"}
                  </span>
                  <span>{fmtMw(site.capacity_mw)}</span>
                  <span>{site.grid_distance_km != null ? `${site.grid_distance_km.toFixed(1)} km` : "--"}</span>
                  <button className="p2-btn-sm" onClick={() => flyToSite(site)}>Fly to</button>
                </div>
              ))}
            </div>
          </div>
        )}

        {results && candidates.length === 0 && (
          <div className="p2-empty">No candidate sites found. Try broadening filters.</div>
        )}
      </div>
    </div>
  );
}
