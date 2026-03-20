import React, { createContext, useContext, useState, useCallback, useEffect } from "react";
import { useWorkspace } from "./WorkspaceContext";
import api from "../services/api";

const GridModelContext = createContext(null);

export function GridModelProvider({ children }) {
  const { activeWorkspace } = useWorkspace();

  // Selected assets
  const [selectedSubstation, setSelectedSubstation] = useState(null);
  const [selectedAsset, setSelectedAsset] = useState(null);

  // Data stores
  const [substations, setSubstations] = useState([]);
  const [cimData, setCimData] = useState(null);
  const [loading, setLoading] = useState(false);

  // Filters (shared across tree, map, table)
  const [filters, setFilters] = useState({
    voltage: "",        // "" | "400" | "275" | "132" | "33" | "11"
    licenceArea: "",
    constraint: "",     // "" | "Thermal" | "Voltage" | "Fault Level"
    search: "",
  });

  // AI insights feed (populated by agent results)
  const [insights, setInsights] = useState([]);

  // Load substations when entering grid workspace
  useEffect(() => {
    if (activeWorkspace !== "grid") return;
    if (substations.length > 0) return; // already loaded
    setLoading(true);
    api.nom.geojson({ view: "connected", map_type: "primary_generation" }).then(data => {
      if (data?.features) {
        const subs = data.features.map(f => ({
          id: f.properties.substation_number || f.id,
          name: f.properties.substation_name || f.properties.name || "Unknown",
          type: f.properties.substation_type || "Primary",
          voltageKv: f.properties.voltage_kv,
          licenceArea: f.properties.licence_area,
          localAuthority: f.properties.local_authority,
          lat: f.geometry?.coordinates?.[1],
          lon: f.geometry?.coordinates?.[0],
          demandHeadroomMw: f.properties.demand_connected_headroom_mw,
          genHeadroomMw: f.properties.generation_connected_headroom_mw,
          demandRag: f.properties.demand_connected_rag,
          genRag: f.properties.generation_connected_rag,
          supplyType: f.properties.supply_type,
          constraint: f.properties.demand_constraint,
          gsp: f.properties.gsp,
          dno: f.properties.dno,
        }));
        setSubstations(subs);

        // Auto-generate AI insights from data
        const constrained = subs.filter(s => s.demandRag === "Red" || s.genRag === "Red");
        const amber = subs.filter(s => s.demandRag === "Amber" || s.genRag === "Amber");
        const newInsights = [];
        if (constrained.length > 0) {
          newInsights.push({
            type: "warning",
            text: `${constrained.length} substations at capacity (Red RAG)`,
            action: () => setFilters(f => ({ ...f, constraint: "" })),
          });
        }
        if (amber.length > 0) {
          newInsights.push({
            type: "caution",
            text: `${amber.length} substations approaching constraint`,
            action: null,
          });
        }
        newInsights.push({
          type: "info",
          text: `${subs.length} substations loaded`,
          action: null,
        });
        setInsights(newInsights);
      }
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [activeWorkspace]); // eslint-disable-line react-hooks/exhaustive-deps

  // Load CIM topology when substation selected
  const loadCimData = useCallback(async (subId) => {
    if (!subId) { setCimData(null); return; }
    try {
      const data = await api.grid.circuit(subId, 3);
      setCimData(data);
    } catch { setCimData(null); }
  }, []);

  useEffect(() => {
    if (selectedSubstation?.id) {
      loadCimData(selectedSubstation.id);
    } else {
      setCimData(null);
    }
  }, [selectedSubstation, loadCimData]);

  // Filter substations
  const filteredSubstations = substations.filter(s => {
    if (filters.voltage && String(s.voltageKv) !== filters.voltage) return false;
    if (filters.licenceArea && s.licenceArea !== filters.licenceArea) return false;
    if (filters.constraint && s.constraint !== filters.constraint) return false;
    if (filters.search) {
      const q = filters.search.toLowerCase();
      const match = (s.name || "").toLowerCase().includes(q)
        || (s.id || "").toLowerCase().includes(q)
        || (s.gsp || "").toLowerCase().includes(q);
      if (!match) return false;
    }
    return true;
  });

  // Select a substation (from tree, map, table, or graph)
  const selectSubstation = useCallback((sub) => {
    setSelectedSubstation(sub);
    setSelectedAsset(sub ? { ...sub, assetType: "substation" } : null);
  }, []);

  // Select any asset (transformer, line, busbar)
  const selectAsset = useCallback((asset) => {
    setSelectedAsset(asset);
  }, []);

  // Clear selection
  const clearSelection = useCallback(() => {
    setSelectedSubstation(null);
    setSelectedAsset(null);
    setCimData(null);
  }, []);

  const updateFilter = useCallback((key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }));
  }, []);

  const value = {
    selectedSubstation, selectSubstation,
    selectedAsset, selectAsset,
    substations, filteredSubstations,
    cimData, loading,
    filters, updateFilter, setFilters,
    insights,
    clearSelection,
  };

  return <GridModelContext.Provider value={value}>{children}</GridModelContext.Provider>;
}

export function useGridModel() {
  const ctx = useContext(GridModelContext);
  if (!ctx) throw new Error("useGridModel must be used within GridModelProvider");
  return ctx;
}

export default GridModelContext;
