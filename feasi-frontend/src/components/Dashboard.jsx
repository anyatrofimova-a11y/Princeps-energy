import React from "react";
import { useSite } from "../SiteContext";
import AgentVerdict from "./AgentVerdict";
import ErrorBoundary from "./ErrorBoundary";
import AgentPanel from "./AgentPanel";
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

/**
 * Dashboard — vertically scrollable card-based layout replacing 13-tab panel.
 * AgentVerdict pinned at top, cards in logical order below.
 */
export default function Dashboard() {
  const {
    activeTab, panelOpen, selectTab,
    parcelId, samCapacity, samDay,
    agentResult, setAgentResult,
    agentLoading, setAgentLoading: _setAgentLoading,
    selectedLsoa,
    setStabilityData,
  } = useSite();

  // Tab definitions for the strip
  const TABS = [
    { id: "overview", label: "Overview", color: "#00ff88" },
    { id: "solar", label: "Solar", color: "#ff9800" },
    { id: "terrain", label: "Terrain", color: "#2196f3" },
    { id: "bipv", label: "BIPV", color: "#00bcd4" },
    { id: "grid", label: "Grid", color: "#00bcd4" },
    { id: "gridData", label: "Substations", color: "#607d8b" },
    { id: "price", label: "Price", color: "#7c4dff" },
    { id: "storage", label: "Storage", color: "#00bcd4" },
    { id: "planning", label: "Planning", color: "#e91e63" },
    { id: "stability", label: "Stability", color: "#f44336" },
    { id: "tenders", label: "Tenders", color: "#ff9800" },
    { id: "epc", label: "EPC", color: "#1a9850" },
    { id: "analytics", label: "AI Energy", color: "#00e5ff" },
    { id: "agent", label: "Analysis", color: "#7c4dff" },
  ];

  return (
    <div className="right-panel">
      <div className="tab-strip">
        {TABS.map(tab => (
          <button
            key={tab.id}
            className={`tab-btn ${activeTab === tab.id ? "active" : ""}`}
            style={activeTab === tab.id
              ? { background: tab.color, borderColor: tab.color, color: "#fff" }
              : { borderColor: tab.color, color: tab.color }}
            onClick={() => selectTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {panelOpen && (
        <div className="tab-content">
          {/* Agent Verdict — always visible at top when available */}
          <AgentVerdict />

          {/* Overview: Score + Solar + Pricing summary */}
          {activeTab === "overview" && (
            <>
              <ScoreCard />
              <SolarCard />
              <PricingCard />
              <StorageCard />
            </>
          )}

          {activeTab === "solar" && <SolarCard />}
          {activeTab === "terrain" && <TerrainCard />}
          {activeTab === "bipv" && (
            <ErrorBoundary name="BIPV"><BIPVPanel parcelId={parcelId} samCapacity={samCapacity} /></ErrorBoundary>
          )}
          {activeTab === "grid" && <GridContextCard />}
          {activeTab === "gridData" && (
            <ErrorBoundary name="Grid Data"><GridDataPanel parcelId={parcelId} samCapacity={samCapacity} /></ErrorBoundary>
          )}
          {activeTab === "price" && <PricingCard />}
          {activeTab === "storage" && <StorageCard />}
          {activeTab === "planning" && (
            <>
              <PlanningCard />
              <DeferralCard />
              <InventoryCard />
              <EnergySystemCard />
            </>
          )}
          {activeTab === "stability" && <StabilityCard onStabilityData={setStabilityData} />}
          {activeTab === "tenders" && <TendersCard />}
          {activeTab === "epc" && (
            <EPCSummary lsoaId={selectedLsoa} parcelId={parcelId} />
          )}
          {activeTab === "analytics" && (
            <ErrorBoundary name="Analytics"><EnergyAnalyticsCard /></ErrorBoundary>
          )}
          {activeTab === "agent" && (
            <ErrorBoundary name="Agent">
              <AgentPanel
                parcelId={parcelId} samCapacity={samCapacity} samDay={samDay}
                agentResult={agentResult} setAgentResult={setAgentResult}
                agentLoading={agentLoading} setAgentLoading={_setAgentLoading}
              />
            </ErrorBoundary>
          )}
        </div>
      )}
    </div>
  );
}
