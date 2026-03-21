import React from "react";
import { useSite } from "../SiteContext";
import AgentVerdict from "./AgentVerdict";
import ErrorBoundary from "./ErrorBoundary";

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
import HomeRetrofitCard from "./cards/HomeRetrofitCard";
import VisionCard from "./cards/VisionCard";
import CIMCircuitCard from "./cards/CIMCircuitCard";
import AssetTrackerCard from "./cards/AssetTrackerCard";
import REPDTrackerCard from "./cards/REPDTrackerCard";
import TECQueueCard from "./cards/TECQueueCard";
import GridUpgradeCard from "./cards/GridUpgradeCard";
import RegulatoryRAGCard from "./cards/RegulatoryRAGCard";
import AlertsCard from "./cards/AlertsCard";
import GridConnectionCard from "./cards/GridConnectionCard";
import FinancialCard from "./cards/FinancialCard";
import GridDataPanel from "./GridDataPanel";
import AgentPanel from "./AgentPanel";

// Study sub-step -> card names
const STUDY_CARD_MAP = {
  feasibility:        ["ScoreCard", "SolarCard", "FinancialCard", "TerrainCard", "GridContextCard", "PlanningCard", "AssetTrackerCard", "REPDTrackerCard", "VisionCard"],
  grid_study:         ["GridContextCard", "GridEfficiencyCard", "CIMCircuitCard", "NGEDOpportunityCard", "AssetTrackerCard", "TECQueueCard", "GridUpgradeCard", "StabilityCard", "GridDataPanel"],
  financial:          ["FinancialCard", "PricingCard", "DeferralCard", "StorageCard", "BESSOptimizerCard", "EnergyAnalyticsCard"],
  environmental:      ["SatelliteCard", "LandClassifierCard", "PlanningCard", "TerrainCard", "VisionCard"],
  planning:           ["PlanningCard", "DeferralCard", "InventoryCard", "EnergySystemCard", "AssetTrackerCard", "REPDTrackerCard"],
  satellite_analysis: ["SatelliteCard", "LandClassifierCard", "TerrainCard", "VisionCard"],
  legacy_compliance:  ["LegacyAssetCard", "ProcurementCard", "InventoryCard"],
  procurement:        ["ProcurementCard", "TendersCard", "InventoryCard"],
  grid_connection:    ["GridConnectionCard", "GridContextCard", "GridEfficiencyCard", "TECQueueCard", "GridUpgradeCard", "StabilityCard"],
  grid_efficiency:    ["GridEfficiencyCard", "CIMCircuitCard", "GridContextCard", "NGEDOpportunityCard", "TECQueueCard", "GridUpgradeCard", "StabilityCard"],
  site_prospecting:   ["SiteProspectorCard", "ScoreCard", "SatelliteCard", "TerrainCard", "AssetTrackerCard"],
  bess_optimisation:  ["BESSOptimizerCard", "StorageCard", "GridContextCard", "PricingCard"],
  bess:               ["BESSOptimizerCard", "StorageCard", "GridContextCard", "PricingCard"],
  home_retrofit:      ["HomeRetrofitCard", "LandClassifierCard", "VisionCard"],
  regulatory_intelligence: ["REPDTrackerCard", "TECQueueCard", "GridUpgradeCard", "RegulatoryRAGCard", "AlertsCard"],
};

const PLAN_CARDS = ["PlanningCard", "InventoryCard", "EnergySystemCard", "DeferralCard"];
const ACT_CARDS = ["LegacyAssetCard", "ProcurementCard", "TendersCard", "SiteProspectorCard", "REPDTrackerCard", "TECQueueCard", "AlertsCard"];

const CARD_COMPONENTS = {
  ScoreCard, SolarCard, TerrainCard, GridContextCard, PricingCard,
  StorageCard, EnergySystemCard, PlanningCard, DeferralCard, InventoryCard,
  TendersCard, StabilityCard, EnergyAnalyticsCard, NGEDOpportunityCard,
  SatelliteCard, LegacyAssetCard, ProcurementCard, GridEfficiencyCard,
  SiteProspectorCard, BESSOptimizerCard, LandClassifierCard,
  HomeRetrofitCard, VisionCard, CIMCircuitCard, AssetTrackerCard,
  REPDTrackerCard, TECQueueCard, GridUpgradeCard, RegulatoryRAGCard, AlertsCard,
  GridConnectionCard, FinancialCard, GridDataPanel, AgentPanel,
};

const INTENT_LABELS = {
  feasibility: "Feasibility", grid_study: "Grid Study", grid_connection: "Grid Connection",
  financial: "Financial", environmental: "Environmental", planning: "Planning",
  satellite_analysis: "Satellite", bess_optimisation: "BESS", grid_efficiency: "Grid Efficiency",
  legacy_compliance: "Legacy", procurement: "Procurement", site_prospecting: "Prospecting",
  regulatory_intelligence: "Regulatory",
};

export default function FloatingCards() {
  const {
    workflowStage, studySubStep, activeIntent,
    parcelId, samCapacity, samDay,
    agentResult, setAgentResult,
    agentLoading,
    selectedLsoa, setStabilityData,
    workflowResults, workflowRunning, workflowProgress,
  } = useSite();

  if (workflowStage === "site") return null;

  // Determine card list — prefer activeIntent when viewing workflow results
  let cardNames;
  const effectiveStep = (workflowResults[activeIntent] && activeIntent) || studySubStep;

  if (workflowStage === "study") {
    cardNames = STUDY_CARD_MAP[effectiveStep] || STUDY_CARD_MAP.feasibility;
  } else if (workflowStage === "plan") {
    cardNames = PLAN_CARDS;
  } else if (workflowStage === "act") {
    cardNames = ACT_CARDS;
  } else {
    cardNames = STUDY_CARD_MAP.feasibility;
  }

  const renderCard = (name) => {
    const Comp = CARD_COMPONENTS[name];
    if (!Comp) return null;
    if (name === "StabilityCard") return <Comp key={name} onStabilityData={setStabilityData} />;
    if (name === "GridDataPanel") return <Comp key={name} parcelId={parcelId} samCapacity={samCapacity} />;
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

  const hasWorkflow = Object.keys(workflowResults).length > 0;

  return (
    <div className="floating-cards">
      {/* Workflow step indicator */}
      {(workflowRunning || hasWorkflow) && workflowStage === "study" && (
        <div className="fc-wf-indicator">
          <span className="fc-wf-label">
            {workflowRunning
              ? `Workflow: ${INTENT_LABELS[workflowProgress?.intent] || "..."} (${workflowProgress?.step || 0}/${workflowProgress?.total || "?"})`
              : `Viewing: ${INTENT_LABELS[activeIntent] || activeIntent}`}
          </span>
          {workflowRunning && <span className="fc-wf-spinner" />}
        </div>
      )}

      {parcelId && <AgentVerdict />}

      {cardNames.map((name) => (
        <ErrorBoundary key={name} name={name}>
          <div className="floating-card">
            {renderCard(name)}
          </div>
        </ErrorBoundary>
      ))}
    </div>
  );
}
