import React, { useState, useCallback } from "react";
import { useGridModel } from "../../contexts/GridModelContext";
import { useWorkspace } from "../../contexts/WorkspaceContext";
import { useSite } from "../../SiteContext";
import StatusBadge from "./StatusBadge";

function PropertyRow({ label, value, unit }) {
  if (value == null || value === "") return null;
  return (
    <div className="gpi-row">
      <span className="gpi-row-label">{label}</span>
      <span className="gpi-row-value">
        {value}{unit && <span className="gpi-row-unit">{unit}</span>}
      </span>
    </div>
  );
}

function Section({ title, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="gpi-section">
      <button className="gpi-section-header" onClick={() => setOpen(!open)}>
        <span>{title}</span>
        <svg
          width="10" height="10" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2"
          style={{ transform: open ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.15s" }}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      {open && <div className="gpi-section-body">{children}</div>}
    </div>
  );
}

export default function GridPropertyInspector() {
  const { selectedAsset, selectedSubstation, cimData, clearSelection } = useGridModel();
  const { navigateToIntent, setActiveViewMode } = useWorkspace();
  const { runAgent, parcelId, samCapacity, samDay, workflowResults } = useSite();
  const [agentLoading, setAgentLoading] = useState(false);

  const handleRunAnalysis = useCallback(async (intent) => {
    if (!parcelId) return;
    setAgentLoading(true);
    try {
      await runAgent(parcelId, intent, samCapacity, samDay);
    } finally {
      setAgentLoading(false);
    }
  }, [runAgent, parcelId, samCapacity, samDay]);

  const handleViewOnMap = useCallback(() => {
    setActiveViewMode("explore");
  }, [setActiveViewMode]);

  const handleViewCircuit = useCallback(() => {
    setActiveViewMode("circuit");
  }, [setActiveViewMode]);

  if (!selectedAsset) {
    return (
      <div className="grid-property-inspector">
        <div className="gpi-empty">
          <div className="gpi-empty-icon">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83" />
            </svg>
          </div>
          <div className="gpi-empty-title">Select an asset</div>
          <div className="gpi-empty-hint">Click a substation in the tree, map, or network view</div>
        </div>
      </div>
    );
  }

  const asset = selectedAsset;
  const gridResult = workflowResults?.grid_study;
  const connResult = workflowResults?.grid_connection;

  return (
    <div className="grid-property-inspector">
      {/* Header */}
      <div className="gpi-header">
        <div className="gpi-header-top">
          <h3 className="gpi-title">{asset.name || "Unknown Asset"}</h3>
          <button className="gpi-close" onClick={clearSelection} title="Deselect">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="gpi-header-badges">
          <StatusBadge status={asset.type || asset.assetType} label={asset.type || asset.assetType} />
          {asset.demandRag && <StatusBadge status={asset.demandRag} label={`Demand: ${asset.demandRag}`} />}
          {asset.genRag && <StatusBadge status={asset.genRag} label={`Gen: ${asset.genRag}`} />}
        </div>
      </div>

      <div className="gpi-body">
        {/* Identity */}
        <Section title="Identity">
          <PropertyRow label="Name" value={asset.name} />
          <PropertyRow label="ID" value={asset.id} />
          <PropertyRow label="Type" value={asset.type || asset.assetType} />
          {asset.voltageKv && <PropertyRow label="Voltage" value={asset.voltageKv} unit="kV" />}
          {asset.gsp && <PropertyRow label="GSP" value={asset.gsp} />}
          {asset.dno && <PropertyRow label="DNO" value={asset.dno} />}
        </Section>

        {/* Capacity */}
        {(asset.demandHeadroomMw != null || asset.genHeadroomMw != null) && (
          <Section title="Capacity">
            <PropertyRow label="Demand Headroom" value={asset.demandHeadroomMw?.toFixed(1)} unit="MW" />
            <PropertyRow label="Gen Headroom" value={asset.genHeadroomMw?.toFixed(1)} unit="MW" />
            {asset.constraint && <PropertyRow label="Constraint" value={asset.constraint} />}
            {asset.supplyType && <PropertyRow label="Supply Type" value={asset.supplyType} />}
          </Section>
        )}

        {/* Location */}
        {(asset.lat || asset.licenceArea) && (
          <Section title="Location">
            <PropertyRow label="Licence Area" value={asset.licenceArea} />
            <PropertyRow label="Local Authority" value={asset.localAuthority} />
            {asset.lat && <PropertyRow label="Coordinates" value={`${asset.lat.toFixed(4)}, ${asset.lon.toFixed(4)}`} />}
          </Section>
        )}

        {/* CIM Topology stats */}
        {cimData?.stats && (
          <Section title="Topology">
            <PropertyRow label="Assets" value={cimData.stats.assetCount} />
            <PropertyRow label="Busbars" value={cimData.stats.busbarCount} />
            {cimData.stats.totalMva > 0 && <PropertyRow label="Total MVA" value={cimData.stats.totalMva} unit="MVA" />}
            {cimData.stats.totalMw > 0 && <PropertyRow label="Total Load" value={cimData.stats.totalMw} unit="MW" />}
          </Section>
        )}

        {/* Agent results (if any exist for this context) */}
        {(gridResult || connResult) && (
          <Section title="Analysis Results">
            {gridResult && (
              <div className="gpi-agent-result">
                <div className="gpi-agent-result-header">
                  <span>Grid Study</span>
                  <StatusBadge status={gridResult.verdict} />
                </div>
                {gridResult.confidence > 0 && (
                  <PropertyRow label="Confidence" value={`${Math.round(gridResult.confidence * 100)}%`} />
                )}
              </div>
            )}
            {connResult && (
              <div className="gpi-agent-result">
                <div className="gpi-agent-result-header">
                  <span>Grid Connection</span>
                  <StatusBadge status={connResult.verdict} />
                </div>
              </div>
            )}
          </Section>
        )}

        {/* Actions */}
        <Section title="Actions">
          <div className="gpi-actions">
            <button className="gpi-action-btn" onClick={handleViewOnMap}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
              </svg>
              View on Map
            </button>
            <button className="gpi-action-btn" onClick={handleViewCircuit}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
              </svg>
              View Circuit
            </button>
            <button
              className="gpi-action-btn gpi-action-btn--primary"
              onClick={() => handleRunAnalysis("grid_connection")}
              disabled={agentLoading || !parcelId}
            >
              {agentLoading ? "Analysing..." : "Run Connection Analysis"}
            </button>
            <button
              className="gpi-action-btn"
              onClick={() => handleRunAnalysis("demand_forecast")}
              disabled={agentLoading || !parcelId}
            >
              Forecast Demand
            </button>
          </div>
        </Section>
      </div>
    </div>
  );
}
