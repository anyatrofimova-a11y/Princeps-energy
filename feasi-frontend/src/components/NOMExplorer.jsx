import React, { useState, useEffect, useCallback } from "react";
import api from "../services/api";
import NOMMap from "./NOMMap";

const MAP_TYPES = [
  { value: "primary_generation", label: "Primary (Generation)" },
  { value: "primary_demand", label: "Primary (Demand)" },
  { value: "bsp_generation", label: "BSP (Generation)" },
  { value: "bsp_demand", label: "BSP (Demand)" },
];

export default function NOMExplorer({ onExit, onAnalyseSubstation }) {
  // Filter state
  const [mapType, setMapType] = useState("primary_generation");
  const [view, setView] = useState("connected");
  const [supplyType, setSupplyType] = useState("");
  const [constraint, setConstraint] = useState("");
  const [licenceArea, setLicenceArea] = useState("");
  const [localAuthority, setLocalAuthority] = useState("");
  const [search, setSearch] = useState("");

  // Data state
  const [geojsonData, setGeojsonData] = useState(null);
  const [resultCount, setResultCount] = useState(0);
  const [selectedSubNumber, setSelectedSubNumber] = useState(null);
  const [selectedSub, setSelectedSub] = useState(null);
  const [licenceAreas, setLicenceAreas] = useState([]);
  const [localAuthorities, setLocalAuthorities] = useState([]);
  const [summary, setSummary] = useState(null);

  // Fetch reference data on mount
  useEffect(() => {
    api.nom.licenceAreas().then(d => { if (d) setLicenceAreas(d); });
    api.nom.localAuthorities().then(d => { if (d) setLocalAuthorities(d); });
    api.nom.summary().then(d => { if (d) setSummary(d); });
  }, []);

  // Build filter params
  const buildParams = useCallback(() => {
    const p = { view, map_type: mapType };
    if (supplyType) p.supply_type = supplyType;
    if (constraint) p.constraint = constraint;
    if (licenceArea) p.licence_area = licenceArea;
    if (localAuthority) p.local_authority = localAuthority;
    if (search) p.search = search;
    return p;
  }, [mapType, view, supplyType, constraint, licenceArea, localAuthority, search]);

  // Fetch GeoJSON whenever filters change
  useEffect(() => {
    const params = buildParams();
    api.nom.geojson(params).then(data => {
      if (data) {
        setGeojsonData(data);
        setResultCount(data.features ? data.features.length : 0);
      }
    });
  }, [buildParams]);

  // Fetch detail when substation selected
  useEffect(() => {
    if (!selectedSubNumber) {
      setSelectedSub(null);
      return;
    }
    api.nom.detail(selectedSubNumber).then(d => {
      if (d) setSelectedSub(d);
    });
  }, [selectedSubNumber]);

  const handleSelectSubstation = useCallback((subNumber) => {
    setSelectedSubNumber(subNumber);
  }, []);

  const handleAnalyse = () => {
    if (selectedSub && onAnalyseSubstation) {
      onAnalyseSubstation(selectedSub);
    }
  };

  const ragBadge = (rag) => (
    <span className={`nom-rag-badge ${rag?.toLowerCase()}`}>{rag}</span>
  );

  const headroomColor = (val) => {
    if (val >= 10) return "#4caf50";
    if (val >= 3) return "#ff9800";
    return "#f44336";
  };

  return (
    <div className="nom-explorer">
      {/* ── Left Panel: Filters ── */}
      <div className="nom-left-panel">
        <div className="nom-left-header">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="3" />
            <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83" />
          </svg>
          Network Opportunity Map
        </div>

        <div className="nom-left-body">
          {/* Map type */}
          <div className="nom-filter-group">
            <span className="nom-filter-label">Map Type</span>
            <select className="nom-filter-select" value={mapType} onChange={e => setMapType(e.target.value)}>
              {MAP_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>

          {/* Connected / Contracted toggle */}
          <div className="nom-filter-group">
            <span className="nom-filter-label">View</span>
            <div className="nom-toggle-group">
              <button className={`nom-toggle-btn ${view === "connected" ? "active" : ""}`}
                onClick={() => setView("connected")}>Connected</button>
              <button className={`nom-toggle-btn ${view === "contracted" ? "active" : ""}`}
                onClick={() => setView("contracted")}>Contracted</button>
            </div>
          </div>

          {/* Supply type */}
          <div className="nom-filter-group">
            <span className="nom-filter-label">Supply Type</span>
            <select className="nom-filter-select" value={supplyType} onChange={e => setSupplyType(e.target.value)}>
              <option value="">Show all</option>
              <option value="Demand">Demand</option>
              <option value="Generation">Generation</option>
              <option value="Mixed">Mixed</option>
            </select>
          </div>

          {/* Demand constraint */}
          <div className="nom-filter-group">
            <span className="nom-filter-label">Demand Constraint</span>
            <select className="nom-filter-select" value={constraint} onChange={e => setConstraint(e.target.value)}>
              <option value="">Show all</option>
              <option value="Thermal">Thermal</option>
              <option value="Voltage">Voltage</option>
              <option value="Fault Level">Fault Level</option>
            </select>
          </div>

          {/* Licence area */}
          <div className="nom-filter-group">
            <span className="nom-filter-label">Licence Area</span>
            <select className="nom-filter-select" value={licenceArea} onChange={e => setLicenceArea(e.target.value)}>
              <option value="">Show all</option>
              {licenceAreas.map(a => (
                <option key={a.name} value={a.name}>{a.name} ({a.count})</option>
              ))}
            </select>
          </div>

          {/* Local authority */}
          <div className="nom-filter-group">
            <span className="nom-filter-label">Local Authority</span>
            <select className="nom-filter-select" value={localAuthority} onChange={e => setLocalAuthority(e.target.value)}>
              <option value="">Show all</option>
              {localAuthorities.map(la => (
                <option key={la} value={la}>{la}</option>
              ))}
            </select>
          </div>

          {/* Search */}
          <div className="nom-filter-group">
            <span className="nom-filter-label">Search</span>
            <div className="nom-search">
              <span className="nom-search-icon">&#x1F50D;</span>
              <input
                type="text"
                placeholder="Name or sub number..."
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </div>
          </div>

          {/* Result count */}
          <div className="nom-result-count">
            Showing <strong>{resultCount}</strong> substations
            {summary && <> of {summary.total}</>}
          </div>

          {/* Back button */}
          <button className="nom-back-btn" onClick={onExit}>
            &larr; Back to Princeps
          </button>
        </div>
      </div>

      {/* ── Center: Map ── */}
      <NOMMap
        geojsonData={geojsonData}
        selectedSub={selectedSub}
        onSelectSubstation={handleSelectSubstation}
      />

      {/* ── Right Panel: Substation Details ── */}
      <div className="nom-right-panel">
        {selectedSub ? (
          <>
            <div className="nom-right-header">
              <span className="nom-right-title">Substation Details</span>
              <button className="nom-close-btn" onClick={() => setSelectedSubNumber(null)}>&times;</button>
            </div>
            <div className="nom-right-body">
              {/* Name & badges */}
              <div className="nom-sub-header">
                <div className="nom-sub-name">{selectedSub.substation_name}</div>
                <div className="nom-sub-meta">
                  <span className={`nom-sub-badge ${selectedSub.substation_type.toLowerCase()}`}>
                    {selectedSub.substation_type}
                  </span>
                  <span style={{ color: "var(--text-dim)" }}>{selectedSub.substation_number}</span>
                </div>
              </div>

              {/* Demand headroom */}
              <div className="nom-section-label">Demand Headroom</div>
              <div className="nom-headroom-grid">
                <div className="nom-headroom-card">
                  <div className="nom-headroom-label">Connected</div>
                  <div className="nom-headroom-value" style={{ color: headroomColor(selectedSub.demand_connected_headroom_mw) }}>
                    {selectedSub.demand_connected_headroom_mw} MW
                    {ragBadge(selectedSub.demand_connected_rag)}
                  </div>
                </div>
                <div className="nom-headroom-card">
                  <div className="nom-headroom-label">Contracted</div>
                  <div className="nom-headroom-value" style={{ color: headroomColor(selectedSub.demand_contracted_headroom_mw) }}>
                    {selectedSub.demand_contracted_headroom_mw} MW
                    {ragBadge(selectedSub.demand_contracted_rag)}
                  </div>
                </div>
              </div>

              {/* Generation headroom */}
              <div className="nom-section-label">Generation Headroom</div>
              <div className="nom-headroom-grid">
                <div className="nom-headroom-card">
                  <div className="nom-headroom-label">Connected</div>
                  <div className="nom-headroom-value" style={{ color: headroomColor(selectedSub.generation_connected_headroom_mw) }}>
                    {selectedSub.generation_connected_headroom_mw} MW
                    {ragBadge(selectedSub.generation_connected_rag)}
                  </div>
                </div>
                <div className="nom-headroom-card">
                  <div className="nom-headroom-label">Contracted</div>
                  <div className="nom-headroom-value" style={{ color: headroomColor(selectedSub.generation_contracted_headroom_mw) }}>
                    {selectedSub.generation_contracted_headroom_mw} MW
                    {ragBadge(selectedSub.generation_contracted_rag)}
                  </div>
                </div>
              </div>

              {/* Info rows */}
              <div className="nom-section-label">Details</div>
              <div className="nom-info-row">
                <span className="nom-info-label">GSP</span>
                <span className="nom-info-value">{selectedSub.gsp}</span>
              </div>
              <div className="nom-info-row">
                <span className="nom-info-label">Licence Area</span>
                <span className="nom-info-value">{selectedSub.licence_area}</span>
              </div>
              <div className="nom-info-row">
                <span className="nom-info-label">DNO</span>
                <span className="nom-info-value">{selectedSub.dno}</span>
              </div>
              <div className="nom-info-row">
                <span className="nom-info-label">Local Authority</span>
                <span className="nom-info-value">{selectedSub.local_authority}</span>
              </div>
              <div className="nom-info-row">
                <span className="nom-info-label">Supply Type</span>
                <span className="nom-info-value">{selectedSub.supply_type}</span>
              </div>
              <div className="nom-info-row">
                <span className="nom-info-label">Constraint</span>
                <span className="nom-info-value">{selectedSub.demand_constraint}</span>
              </div>
              <div className="nom-info-row">
                <span className="nom-info-label">Coordinates</span>
                <span className="nom-info-value">{selectedSub.lat}, {selectedSub.lon}</span>
              </div>
              <div className="nom-info-row">
                <span className="nom-info-label">BNG</span>
                <span className="nom-info-value">E {selectedSub.easting} N {selectedSub.northing}</span>
              </div>

              {/* Description */}
              <div className="nom-description">{selectedSub.description}</div>

              {/* Analyse button */}
              <button className="nom-analyse-btn" onClick={handleAnalyse}>
                Analyse Connection
              </button>
            </div>
          </>
        ) : (
          <div className="nom-empty">
            <div className="nom-empty-icon">&#x26A1;</div>
            <div>Select a substation on the map to view details</div>
            <div style={{ fontSize: 10, marginTop: 4 }}>
              Click any circle marker to inspect headroom and RAG ratings
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
