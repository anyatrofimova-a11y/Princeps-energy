import React, { useState, useCallback, useRef, useEffect } from "react";
import { useSite } from "../SiteContext";
import { ChatSection } from "./ChatPanel";
import AgentVerdict from "./AgentVerdict";
import AgentPanel from "./AgentPanel";
import ErrorBoundary from "./ErrorBoundary";
import EPCSummary from "./EPCSummary";
import BIPVPanel from "./BIPVPanel";
import GridDataPanel from "./GridDataPanel";

import ScoreCard from "./cards/ScoreCard";
import SolarCard from "./cards/SolarCard";
import TerrainCard from "./cards/TerrainCard";
import GridContextCard from "./cards/GridContextCard";
import PricingCard from "./cards/PricingCard";
import StorageCard from "./cards/StorageCard";
import EnergySystemCard from "./cards/EnergySystemCard";
import PlanningCard from "./cards/PlanningCard";
import DeferralCard from "./cards/DeferralCard";
import InventoryCard from "./cards/InventoryCard";
import TendersCard from "./cards/TendersCard";
import StabilityCard from "./cards/StabilityCard";
import EnergyAnalyticsCard from "./cards/EnergyAnalyticsCard";
import NGEDOpportunityCard from "./cards/NGEDOpportunityCard";
import SatelliteCard from "./cards/SatelliteCard";
import LegacyAssetCard from "./cards/LegacyAssetCard";
import ProcurementCard from "./cards/ProcurementCard";
import GridEfficiencyCard from "./cards/GridEfficiencyCard";
import SiteProspectorCard from "./cards/SiteProspectorCard";
import BESSOptimizerCard from "./cards/BESSOptimizerCard";
import LandClassifierCard from "./cards/LandClassifierCard";
import RetrofitCard from "./cards/RetrofitCard";

// Intent -> contextual cards mapping
const INTENT_CARD_MAP = {
  overview:           ["ScoreCard", "SolarCard", "PricingCard", "StorageCard"],
  feasibility:        ["ScoreCard", "SolarCard", "TerrainCard", "GridContextCard", "PlanningCard"],
  grid_study:         ["GridContextCard", "GridEfficiencyCard", "NGEDOpportunityCard", "StabilityCard", "GridDataPanel"],
  financial:          ["PricingCard", "DeferralCard", "StorageCard", "BESSOptimizerCard", "EnergyAnalyticsCard"],
  environmental:      ["SatelliteCard", "LandClassifierCard", "PlanningCard", "TerrainCard"],
  planning:           ["PlanningCard", "DeferralCard", "InventoryCard", "EnergySystemCard"],
  satellite_analysis: ["SatelliteCard", "LandClassifierCard", "TerrainCard"],
  legacy_compliance:  ["LegacyAssetCard", "ProcurementCard", "InventoryCard"],
  procurement:        ["ProcurementCard", "TendersCard", "InventoryCard"],
  grid_efficiency:    ["GridEfficiencyCard", "GridContextCard", "NGEDOpportunityCard", "StabilityCard"],
  site_prospecting:   ["SiteProspectorCard", "ScoreCard", "SatelliteCard", "TerrainCard"],
  infrastructure_retrofit: ["RetrofitCard", "LegacyAssetCard", "GridEfficiencyCard", "GridContextCard"],
  bess:               ["BESSOptimizerCard", "StorageCard", "GridContextCard", "PricingCard"],
};

// Component registry by name
const CARD_COMPONENTS = {
  ScoreCard, SolarCard, TerrainCard, GridContextCard, PricingCard,
  StorageCard, EnergySystemCard, PlanningCard, DeferralCard, InventoryCard,
  TendersCard, StabilityCard, EnergyAnalyticsCard, NGEDOpportunityCard,
  SatelliteCard, LegacyAssetCard, ProcurementCard, GridEfficiencyCard,
  SiteProspectorCard, BESSOptimizerCard, LandClassifierCard, RetrofitCard,
  GridDataPanel, BIPVPanel, EPCSummary, AgentPanel,
};

// All cards grouped by category for "All Cards" view
const ALL_CARD_GROUPS = [
  { label: "Site Analysis", cards: ["ScoreCard", "SolarCard", "TerrainCard"] },
  { label: "Grid & Storage", cards: ["GridContextCard", "GridEfficiencyCard", "NGEDOpportunityCard", "StabilityCard", "GridDataPanel", "BESSOptimizerCard", "StorageCard"] },
  { label: "Financial", cards: ["PricingCard", "DeferralCard", "EnergyAnalyticsCard", "EnergySystemCard"] },
  { label: "Planning & Land", cards: ["PlanningCard", "SatelliteCard", "LandClassifierCard", "InventoryCard"] },
  { label: "Specialist", cards: ["LegacyAssetCard", "ProcurementCard", "TendersCard", "SiteProspectorCard", "RetrofitCard", "BIPVPanel"] },
  { label: "Agent", cards: ["AgentPanel"] },
];

const INTENT_LABELS = {
  overview: "Overview",
  feasibility: "Feasibility",
  grid_study: "Grid Study",
  financial: "Financial",
  environmental: "Environmental",
  planning: "Planning",
  satellite_analysis: "Satellite / DL",
  legacy_compliance: "Legacy / Compliance",
  procurement: "Procurement",
  grid_efficiency: "Grid Efficiency",
  site_prospecting: "Site Prospecting",
  bess: "BESS",
  infrastructure_retrofit: "Infra Retrofit",
};

export default function CommandPanel({ onMapLayer, onZoomTo }) {
  const {
    activeIntent, commandCollapsed, setCommandCollapsed,
    parcelId, samCapacity, samDay,
    agentResult, setAgentResult,
    agentLoading,
    selectedLsoa, setStabilityData,
  } = useSite();

  const [showAll, setShowAll] = useState(false);
  const [cardsFlex, setCardsFlex] = useState(55);
  const dividerRef = useRef(null);
  const panelRef = useRef(null);

  // Drag-to-resize divider
  const handleDividerMouseDown = useCallback((e) => {
    e.preventDefault();
    const panel = panelRef.current;
    if (!panel) return;

    const startY = e.clientY;
    const panelRect = panel.getBoundingClientRect();
    const startFlex = cardsFlex;

    const onMove = (ev) => {
      const dy = ev.clientY - startY;
      const pct = (dy / panelRect.height) * 100;
      const newFlex = Math.max(15, Math.min(85, startFlex + pct));
      setCardsFlex(newFlex);
    };

    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }, [cardsFlex]);

  if (commandCollapsed) {
    return (
      <div className="command-area command-collapsed">
        <button className="command-expand-btn" onClick={() => setCommandCollapsed(false)} title="Expand panel">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 18 9 12 15 6" /></svg>
        </button>
      </div>
    );
  }

  // Determine which cards to render
  const cardNames = showAll ? null : (INTENT_CARD_MAP[activeIntent] || INTENT_CARD_MAP.overview);

  const renderCard = (name) => {
    const Comp = CARD_COMPONENTS[name];
    if (!Comp) return null;
    // Some components need special props
    if (name === "StabilityCard") return <Comp key={name} onStabilityData={setStabilityData} />;
    if (name === "GridDataPanel") return <Comp key={name} parcelId={parcelId} samCapacity={samCapacity} />;
    if (name === "BIPVPanel") return <Comp key={name} parcelId={parcelId} samCapacity={samCapacity} />;
    if (name === "EPCSummary") return <Comp key={name} lsoaId={selectedLsoa} parcelId={parcelId} />;
    if (name === "AgentPanel") {
      return (
        <Comp
          key={name}
          parcelId={parcelId} samCapacity={samCapacity} samDay={samDay}
          agentResult={agentResult} setAgentResult={setAgentResult}
          agentLoading={agentLoading} setAgentLoading={() => {}}
        />
      );
    }
    return <Comp key={name} />;
  };

  return (
    <div className="command-area command-panel" ref={panelRef}>
      {/* Header */}
      <div className="command-header">
        <span className="command-intent-label">{INTENT_LABELS[activeIntent] || "Overview"}</span>
        <button
          className={`command-toggle-btn${showAll ? " active" : ""}`}
          onClick={() => setShowAll((p) => !p)}
        >
          {showAll ? "Context" : "All Cards"}
        </button>
        <button className="command-collapse-btn" onClick={() => setCommandCollapsed(true)} title="Collapse">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 18 15 12 9 6" /></svg>
        </button>
      </div>

      {/* Cards section */}
      <div className="command-cards" style={{ flex: `${cardsFlex} 0 0` }}>
        <AgentVerdict />

        {!showAll && cardNames && cardNames.map((name) => (
          <ErrorBoundary key={name} name={name}>
            {renderCard(name)}
          </ErrorBoundary>
        ))}

        {showAll && ALL_CARD_GROUPS.map((group) => (
          <div key={group.label} className="command-card-group">
            <div className="command-group-label">{group.label}</div>
            {group.cards.map((name) => (
              <ErrorBoundary key={name} name={name}>
                {renderCard(name)}
              </ErrorBoundary>
            ))}
          </div>
        ))}

        {!parcelId && !showAll && (
          <div className="command-empty">
            Pick a site on the map or select an intent to begin analysis.
          </div>
        )}
      </div>

      {/* Resize divider */}
      <div
        className="command-divider"
        ref={dividerRef}
        onMouseDown={handleDividerMouseDown}
      />

      {/* Chat section */}
      <div className="command-chat" style={{ flex: `${100 - cardsFlex} 0 0` }}>
        <ChatSection onMapLayer={onMapLayer} onZoomTo={onZoomTo} />
      </div>
    </div>
  );
}
