/**
 * ParcelDetailPanel — Right-side inspector for selected UK land parcels.
 *
 * Shows single-parcel detail or multi-select summary. White/light themed
 * panel styled like Glint Solar's professional GIS tool aesthetic.
 *
 * Props:
 *   selectedParcels — array of selected parcel objects
 *   onClose         — callback to close the panel
 *   onCopyToProject — callback(parcels) to copy polygons to a project
 *   onSaveToProject — callback({ projectName, parcels }) to save
 */
import React, { useState } from "react";

function formatDate(d) {
  if (!d) return "--";
  try {
    return new Date(d).toLocaleDateString("en-GB", {
      day: "numeric", month: "short", year: "numeric",
    });
  } catch { return d; }
}

function formatArea(ha) {
  if (ha == null) return "--";
  return ha < 1 ? `${(ha * 10000).toFixed(0)} m2` : `${ha.toFixed(2)} ha`;
}

export default function ParcelDetailPanel({
  selectedParcels = [],
  onClose,
  onCopyToProject,
  onSaveToProject,
}) {
  const [saveModalOpen, setSaveModalOpen] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [expandedDesc, setExpandedDesc] = useState(false);

  if (!selectedParcels || selectedParcels.length === 0) return null;

  const isSingle = selectedParcels.length === 1;
  const parcel = isSingle ? selectedParcels[0] : null;
  const totalArea = selectedParcels.reduce((sum, p) => sum + (p.area_ha || p.area || 0), 0);

  const handleCopy = () => {
    onCopyToProject?.(selectedParcels);
  };

  const handleSave = () => {
    if (!projectName.trim()) return;
    onSaveToProject?.({ projectName: projectName.trim(), parcels: selectedParcels });
    setSaveModalOpen(false);
    setProjectName("");
  };

  return (
    <div className="lp-detail-panel">
      {/* Header */}
      <div className="lp-detail-header">
        <div className="lp-detail-header-left">
          <div className="lp-detail-icon">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#c040ff" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <path d="M3 9h18M9 3v18" />
            </svg>
          </div>
          <span className="lp-detail-title">
            {isSingle ? "Parcel Detail" : `${selectedParcels.length} Parcels Selected`}
          </span>
        </div>
        <button className="lp-detail-close" onClick={onClose}>&times;</button>
      </div>

      {/* Single parcel view */}
      {isSingle && parcel && (
        <div className="lp-detail-body">
          {/* Tenure badge */}
          <div className="lp-section-header">
            <span className="lp-tenure-badge" data-tenure={parcel.tenure?.toLowerCase()}>
              Parcels - {parcel.tenure || "freehold"}
            </span>
          </div>

          {/* Copy button */}
          <button className="lp-copy-btn" onClick={handleCopy}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="9" y="9" width="13" height="13" rx="2" />
              <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
            </svg>
            Copy polygon to project
          </button>

          {/* Detail grid */}
          <div className="lp-detail-grid">
            <div className="lp-detail-row">
              <span className="lp-detail-label">Area</span>
              <span className="lp-detail-value">{formatArea(parcel.area_ha || parcel.area)}</span>
            </div>
            <div className="lp-detail-row">
              <span className="lp-detail-label">Title No</span>
              <span className="lp-detail-value lp-mono">
                {parcel.title_number || parcel.titleNumber || parcel.title_no || "--"}
              </span>
            </div>
            <div className="lp-detail-row">
              <span className="lp-detail-label">Proprietor</span>
              <span className="lp-detail-value">
                {parcel.proprietor || (
                  <span className="lp-detail-muted">Requires HMLR search</span>
                )}
              </span>
            </div>
            <div className="lp-detail-row">
              <span className="lp-detail-label">Tenure</span>
              <span className="lp-detail-value">{parcel.tenure || "Freehold"}</span>
            </div>
            <div className="lp-detail-row">
              <span className="lp-detail-label">Date Proprietor Added</span>
              <span className="lp-detail-value">{formatDate(parcel.date_proprietor_added)}</span>
            </div>
            <div className="lp-detail-row">
              <span className="lp-detail-label">Proprietorship Category</span>
              <span className="lp-detail-value">{parcel.proprietorship_category || "--"}</span>
            </div>
            <div className="lp-detail-row">
              <span className="lp-detail-label">Address</span>
              <span className="lp-detail-value">{parcel.address || "--"}</span>
            </div>
            {parcel.price_paid && (
              <div className="lp-detail-row">
                <span className="lp-detail-label">Price Paid</span>
                <span className="lp-detail-value">
                  {typeof parcel.price_paid === "number"
                    ? `GBP ${parcel.price_paid.toLocaleString()}`
                    : parcel.price_paid}
                </span>
              </div>
            )}
            {parcel.alc_grade && (
              <div className="lp-detail-row">
                <span className="lp-detail-label">ALC Grade</span>
                <span className="lp-detail-value">{parcel.alc_grade}</span>
              </div>
            )}
          </div>

          {/* Save button */}
          <button className="lp-save-btn" onClick={() => setSaveModalOpen(true)}>
            Save to project
          </button>
        </div>
      )}

      {/* Multi-select view */}
      {!isSingle && (
        <div className="lp-detail-body">
          <div className="lp-multi-summary">
            <div className="lp-multi-stat">
              <span className="lp-multi-stat-label">Number of selected</span>
              <span className="lp-multi-stat-value">{selectedParcels.length}</span>
            </div>
            <div className="lp-multi-stat">
              <span className="lp-multi-stat-label">Total area</span>
              <span className="lp-multi-stat-value">{formatArea(totalArea)}</span>
            </div>
          </div>

          <button className="lp-copy-btn" onClick={handleCopy}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="9" y="9" width="13" height="13" rx="2" />
              <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
            </svg>
            Copy all to project
          </button>

          {/* Expandable description */}
          <button
            className="lp-expand-btn"
            onClick={() => setExpandedDesc(!expandedDesc)}
          >
            <svg
              width="12" height="12" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2"
              style={{ transform: expandedDesc ? "rotate(90deg)" : "rotate(0deg)", transition: "transform 0.2s" }}
            >
              <polyline points="9 18 15 12 9 6" />
            </svg>
            Description
          </button>

          {expandedDesc && (
            <div className="lp-multi-list">
              {selectedParcels.map((p, i) => {
                const title = p.title_number || p.titleNumber || p.title_no || `Parcel ${i + 1}`;
                return (
                  <div key={title + i} className="lp-multi-item">
                    <span className="lp-multi-item-title">{title}</span>
                    <span className="lp-multi-item-area">{formatArea(p.area_ha || p.area)}</span>
                    <span className="lp-multi-item-tenure">{p.tenure || "Freehold"}</span>
                  </div>
                );
              })}
            </div>
          )}

          <button className="lp-save-btn" onClick={() => setSaveModalOpen(true)}>
            Save to project
          </button>
        </div>
      )}

      {/* Save modal */}
      {saveModalOpen && (
        <div className="lp-modal-overlay" onClick={() => setSaveModalOpen(false)}>
          <div className="lp-modal" onClick={(e) => e.stopPropagation()}>
            <div className="lp-modal-header">
              <span>Save to Project</span>
              <button className="lp-modal-close" onClick={() => setSaveModalOpen(false)}>&times;</button>
            </div>
            <div className="lp-modal-body">
              <label className="lp-modal-label">Project name</label>
              <input
                className="lp-modal-input"
                type="text"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="Enter project name..."
                autoFocus
              />
              <div className="lp-modal-info">
                {selectedParcels.length} parcel{selectedParcels.length !== 1 ? "s" : ""} &middot; {formatArea(totalArea)}
              </div>
            </div>
            <div className="lp-modal-footer">
              <button className="lp-modal-cancel" onClick={() => setSaveModalOpen(false)}>Cancel</button>
              <button
                className="lp-modal-save"
                onClick={handleSave}
                disabled={!projectName.trim()}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
