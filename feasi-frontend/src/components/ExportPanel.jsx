import React, { useState, useCallback } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

const FORMATS = [
  { id: "kml",     label: "KML",     ext: ".kml",     desc: "Site boundaries, parcels, routes — Google Earth compatible", icon: "M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" },
  { id: "geojson", label: "GeoJSON", ext: ".geojson", desc: "Spatial data for GIS tools and web mapping", icon: "M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z" },
  { id: "dxf",     label: "DXF",     ext: ".dxf",     desc: "CAD-ready site layouts for AutoCAD / Civil 3D", icon: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z" },
  { id: "pdf",     label: "PDF",     ext: ".pdf",     desc: "Assessment reports, financial summaries", icon: "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z" },
  { id: "xlsx",    label: "XLSX",    ext: ".xlsx",    desc: "Financial model, yield data, grid analysis", icon: "M3 3h18v18H3zM3 9h18M3 15h18M9 3v18M15 3v18" },
  { id: "usd",     label: "USD",     ext: ".usd",     desc: "3D model export for digital twin viewers", icon: "M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z" },
  { id: "csv",     label: "CSV",     ext: ".csv",     desc: "Raw data tables — demand, generation, pricing", icon: "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zM8 13h2M8 17h2M12 13h4M12 17h4" },
  { id: "png",     label: "PNG",     ext: ".png",     desc: "Map screenshots and chart exports", icon: "M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14" },
];

export default function ExportPanel({ onClose, embedded }) {
  const { parcelId, explain } = useSite();
  const [exporting, setExporting] = useState({});
  const [recentExports, setRecentExports] = useState([]);
  const [batchFormats, setBatchFormats] = useState(new Set());

  const exportFormat = useCallback(async (formatId) => {
    setExporting(prev => ({ ...prev, [formatId]: true }));
    try {
      const res = await api.exports.generate({
        format: formatId,
        site_id: parcelId,
        site_name: explain?.location_name || parcelId,
      });
      const fmt = FORMATS.find(f => f.id === formatId);
      setRecentExports(prev => [{
        id: `exp-${Date.now()}`,
        format: formatId,
        label: fmt?.label,
        date: new Date().toISOString(),
        url: res?.download_url || null,
        size: res?.size_bytes || null,
      }, ...prev].slice(0, 10));
    } catch (e) {
      console.warn("[Export] Failed:", e);
    } finally {
      setExporting(prev => ({ ...prev, [formatId]: false }));
    }
  }, [parcelId, explain]);

  const toggleBatch = useCallback((fmtId) => {
    setBatchFormats(prev => {
      const next = new Set(prev);
      next.has(fmtId) ? next.delete(fmtId) : next.add(fmtId);
      return next;
    });
  }, []);

  const exportBatch = useCallback(async () => {
    for (const fmtId of batchFormats) {
      await exportFormat(fmtId);
    }
    setBatchFormats(new Set());
  }, [batchFormats, exportFormat]);

  return (
    <div className="ex-panel">
      {!embedded && (
        <div className="ex-header">
          <span className="ex-title">Export Hub</span>
          <button className="ex-close" onClick={onClose}>&times;</button>
        </div>
      )}

      <div className="ex-body">
        {/* Format grid */}
        <div className="ex-formats">
          {FORMATS.map(f => (
            <div key={f.id} className="ex-format-card">
              <div className="ex-format-top">
                <div className="ex-format-icon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d={f.icon} />
                  </svg>
                </div>
                <div className="ex-format-info">
                  <span className="ex-format-label">{f.label}</span>
                  <span className="ex-format-desc">{f.desc}</span>
                </div>
              </div>
              <div className="ex-format-actions">
                <button className="ex-btn-export" onClick={() => exportFormat(f.id)}
                  disabled={exporting[f.id]}>
                  {exporting[f.id] ? "Exporting..." : "Export"}
                </button>
                <label className="ex-batch-check">
                  <input type="checkbox" checked={batchFormats.has(f.id)}
                    onChange={() => toggleBatch(f.id)} />
                </label>
              </div>
            </div>
          ))}
        </div>

        {/* Batch export */}
        {batchFormats.size > 0 && (
          <button className="ex-btn-primary" onClick={exportBatch}>
            Export All ({batchFormats.size} formats)
          </button>
        )}

        {/* Recent exports */}
        {recentExports.length > 0 && (
          <div className="ex-section">
            <div className="ex-section-title">Recent Exports</div>
            {recentExports.map(exp => (
              <div key={exp.id} className="ex-recent-row">
                <span className="ex-recent-fmt">{exp.label}</span>
                <span className="ex-recent-date">
                  {new Date(exp.date).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
                </span>
                {exp.url ? (
                  <a className="ex-btn-sm" href={exp.url} download>Download</a>
                ) : (
                  <span className="ex-recent-pending">Processing</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
