import React, { useState, useCallback } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

const EXPORT_CATEGORIES = [
  {
    id: "reports",
    label: "Reports & Documents",
    icon: "M9 12h6M9 16h6M17 21H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
    items: [
      { id: "pdf_report", label: "Site Assessment Report", desc: "Full PDF with verdict, scores, maps, financials", format: "PDF", primary: true },
      { id: "dc_report", label: "Data Centre Report", desc: "15-dimension DC suitability assessment", format: "PDF" },
      { id: "data_room", label: "Data Room Bundle", desc: "Complete document pack for investor/lender review", format: "ZIP" },
    ],
  },
  {
    id: "financial",
    label: "Financial Models",
    icon: "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
    items: [
      { id: "xlsx_financial", label: "Financial Input Pack", desc: "Pre-populated Excel: yield, grid costs, CAPEX benchmarks, constraint summary", format: "XLSX", primary: true },
      { id: "csv_yield", label: "Hourly Yield Data", desc: "8,760 hourly generation values from PvWatts simulation", format: "CSV" },
      { id: "csv_demand", label: "Demand Forecast Data", desc: "FES 4-pathway demand projections for nearest GSP", format: "CSV" },
    ],
  },
  {
    id: "gis",
    label: "GIS & Spatial Data",
    icon: "M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l5.447 2.724A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7",
    items: [
      { id: "geojson_site", label: "Site Boundary GeoJSON", desc: "Site perimeter, constraint zones, grid routes as GeoJSON", format: "GeoJSON", primary: true },
      { id: "shapefile", label: "Shapefile Export", desc: "QGIS/ArcGIS-compatible shapefile with all layers", format: "SHP" },
      { id: "kml", label: "Google Earth KML", desc: "Site location with verdict overlay for Google Earth", format: "KML" },
    ],
  },
  {
    id: "grid",
    label: "Grid Connection",
    icon: "M13 10V3L4 14h7v7l9-11h-7z",
    items: [
      { id: "g99_pack", label: "G99 Application Pack", desc: "Pre-filled G99 form data: coords, capacity, voltage, fault level, SLD", format: "PDF", primary: true },
      { id: "grid_study", label: "Grid Study Export", desc: "Power flow results, N-1 contingency, thermal limits", format: "XLSX" },
      { id: "connection_cost", label: "Connection Cost Estimate", desc: "P10/P50/P90 cost bands with per-km rates by voltage", format: "PDF" },
    ],
  },
  {
    id: "design",
    label: "Design & Simulation",
    icon: "M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6z",
    items: [
      { id: "pvsyst_weather", label: "PVsyst Weather File", desc: "TMY-format weather data for direct PVsyst import", format: "TMY" },
      { id: "bom_xlsx", label: "Bill of Materials", desc: "Component list with quantities, specs, cost estimates", format: "XLSX" },
      { id: "layout_json", label: "3D Layout Data", desc: "Component positions, orientations, cable routes as JSON", format: "JSON" },
    ],
  },
  {
    id: "integrate",
    label: "Integrations",
    icon: "M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z",
    items: [
      { id: "crm_push", label: "Push to Salesforce", desc: "Create/update Opportunity with verdict, yield, grid cost", format: "API", comingSoon: true },
      { id: "hubspot_push", label: "Push to HubSpot", desc: "Create Deal with feasibility summary", format: "API", comingSoon: true },
      { id: "sharepoint", label: "Upload to SharePoint", desc: "Export document pack to project folder", format: "API", comingSoon: true },
    ],
  },
];

export default function ExportHub() {
  const {
    explain, pickedLocation, parcelId, agentResult,
    samCapacity, solarYield, gridContext, geeflowData,
  } = useSite();

  const [activeCategory, setActiveCategory] = useState("reports");
  const [exporting, setExporting] = useState(null);

  const lat = explain?.lat ?? pickedLocation?.lat;
  const lon = explain?.lon ?? pickedLocation?.lon;
  const name = explain?.location_name || parcelId || "Site";

  const handleExport = useCallback(async (itemId) => {
    if (exporting) return;
    setExporting(itemId);
    try {
      switch (itemId) {
        case "pdf_report": {
          const blob = await api.reports.siteAssessment(lat, lon, name, samCapacity / 1000 || 50);
          downloadBlob(blob, `princeps-report-${slug(name)}.pdf`);
          break;
        }
        case "dc_report": {
          const blob = await api.reports.dcReport?.(lat, lon, name, 100);
          if (blob) downloadBlob(blob, `princeps-dc-report-${slug(name)}.pdf`);
          break;
        }
        case "xlsx_financial": {
          const data = buildFinancialPack();
          downloadJson(data, `princeps-financial-${slug(name)}.json`);
          break;
        }
        case "csv_yield": {
          const data = solarYield?.monthly_energy_kwh || [];
          const csv = "month,energy_kwh\n" + data.map((v, i) => `${i + 1},${v}`).join("\n");
          downloadText(csv, `princeps-yield-${slug(name)}.csv`);
          break;
        }
        case "geojson_site": {
          const geojson = {
            type: "FeatureCollection",
            features: [{
              type: "Feature",
              geometry: { type: "Point", coordinates: [lon, lat] },
              properties: {
                name, parcel_id: parcelId,
                verdict: agentResult?.verdict,
                confidence: agentResult?.confidence,
                score: explain?.score_total,
                grid_distance_km: gridContext?.nearest_substation?.distance_km,
                grid_headroom_mw: gridContext?.nearest_substation?.headroom_mw,
              },
            }],
          };
          downloadJson(geojson, `princeps-site-${slug(name)}.geojson`);
          break;
        }
        case "g99_pack": {
          const g99 = buildG99Data();
          downloadJson(g99, `princeps-g99-${slug(name)}.json`);
          break;
        }
        case "layout_json": {
          // Export layout from localStorage or context
          downloadJson({ site: name, lat, lon, note: "Layout data — use 3D editor to populate" }, `princeps-layout-${slug(name)}.json`);
          break;
        }
        default:
          alert(`Export "${itemId}" — coming soon`);
      }
    } catch (err) {
      console.error("Export failed:", err);
      alert("Export failed — see console.");
    } finally {
      setExporting(null);
    }
  }, [exporting, lat, lon, name, samCapacity, parcelId, agentResult, explain, gridContext, solarYield]);

  function buildFinancialPack() {
    return {
      site: { name, lat, lon, parcel_id: parcelId, area_ha: explain?.area_ha },
      verdict: { verdict: agentResult?.verdict, confidence: agentResult?.confidence },
      yield: {
        annual_energy_kwh: solarYield?.annual_energy_kwh,
        capacity_factor_pct: solarYield?.capacity_factor_pct,
        monthly_kwh: solarYield?.monthly_energy_kwh,
      },
      grid: {
        nearest_substation: gridContext?.nearest_substation?.name,
        distance_km: gridContext?.nearest_substation?.distance_km,
        voltage_kv: gridContext?.nearest_substation?.voltage_kv,
        headroom_mw: gridContext?.nearest_substation?.headroom_mw,
      },
      geeflow: {
        land_use: geeflowData?.extractions?.land_use?.dominant_class,
        developable_pct: geeflowData?.extractions?.land_use?.developable_pct,
        slope_mean_deg: geeflowData?.extractions?.terrain?.slope?.mean_deg,
        elevation_m: geeflowData?.extractions?.terrain?.elevation?.mean_m,
        ghi_kwh_m2: geeflowData?.extractions?.solar_resource?.annual_ghi_kwh_m2,
      },
      capacity_kw: samCapacity,
      exported_at: new Date().toISOString(),
      platform: "Princeps",
    };
  }

  function buildG99Data() {
    return {
      application_type: "G99",
      site: { name, lat, lon, postcode: explain?.postcode || "" },
      generation: {
        technology: "Solar PV",
        capacity_kw: samCapacity,
        phases: 3,
        inverter_type: "Grid-following",
      },
      connection: {
        proposed_voltage_kv: gridContext?.nearest_substation?.voltage_kv || 33,
        nearest_substation: gridContext?.nearest_substation?.name,
        distance_km: gridContext?.nearest_substation?.distance_km,
        headroom_mw: gridContext?.nearest_substation?.headroom_mw,
      },
      dno: explain?.dno || "",
      note: "Pre-filled from Princeps AI assessment. Verify all fields before submission.",
      exported_at: new Date().toISOString(),
    };
  }

  const activeCat = EXPORT_CATEGORIES.find(c => c.id === activeCategory);

  return (
    <div className="export-hub">
      <div className="export-hub-header">
        <h3 className="export-hub-title">Export & Integrate</h3>
        <span className="export-hub-site">{name}</span>
      </div>

      <div className="export-hub-body">
        {/* Category tabs */}
        <div className="export-hub-tabs">
          {EXPORT_CATEGORIES.map(cat => (
            <button
              key={cat.id}
              className={`export-hub-tab${activeCategory === cat.id ? " active" : ""}`}
              onClick={() => setActiveCategory(cat.id)}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d={cat.icon} />
              </svg>
              <span>{cat.label}</span>
            </button>
          ))}
        </div>

        {/* Export items */}
        <div className="export-hub-items">
          {activeCat?.items.map(item => (
            <div key={item.id} className={`export-hub-item${item.primary ? " primary" : ""}${item.comingSoon ? " coming-soon" : ""}`}>
              <div className="export-hub-item-info">
                <div className="export-hub-item-label">{item.label}</div>
                <div className="export-hub-item-desc">{item.desc}</div>
              </div>
              <div className="export-hub-item-actions">
                <span className="export-hub-format">{item.format}</span>
                {item.comingSoon ? (
                  <span className="export-hub-soon">Soon</span>
                ) : (
                  <button
                    className="export-hub-btn"
                    onClick={() => handleExport(item.id)}
                    disabled={exporting === item.id || !lat}
                  >
                    {exporting === item.id ? (
                      <span className="export-hub-spinner" />
                    ) : (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" /></svg>
                    )}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function slug(s) { return (s || "site").replace(/[^\w-]/g, "-").slice(0, 30); }
function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}
function downloadJson(obj, filename) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" });
  downloadBlob(blob, filename);
}
function downloadText(text, filename) {
  const blob = new Blob([text], { type: "text/csv" });
  downloadBlob(blob, filename);
}
