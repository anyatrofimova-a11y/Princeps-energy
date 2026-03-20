import React, { useEffect, lazy, Suspense } from "react";
import { useSite } from "../../SiteContext";
import { useWorkspace, INTENT_DETAIL_MAP } from "../../contexts/WorkspaceContext";
import FloatingCards from "../FloatingCards";
import ErrorBoundary from "../ErrorBoundary";
import GridConnectionPanel from "../GridConnectionPanel";
import DemandForecastPanel from "../DemandForecastPanel";
import AdvancedGridPanel from "../AdvancedGridPanel";
import ConnectionStrategyPanel from "../ConnectionStrategyPanel";
import DispatchPanel from "../DispatchPanel";
import RouteToMarketPanel from "../RouteToMarketPanel";
import SustainabilityPanel from "../SustainabilityPanel";
import InvestmentPanel from "../InvestmentPanel";
import DataCentrePanel from "../DataCentrePanel";

const GridPropertyInspector = lazy(() => import("../grid/GridPropertyInspector"));

const DETAIL_TABS = [
  { id: "cards", label: "Overview" },
  { id: "connection", label: "Connection", workspace: "analyse" },
  { id: "demand", label: "Demand", workspace: "analyse" },
  { id: "advanced", label: "Advanced", workspace: "analyse" },
  { id: "strategy", label: "Strategy", workspace: "design" },
  { id: "dispatch", label: "Dispatch", workspace: "design" },
  { id: "rtm", label: "Route", workspace: "design" },
  { id: "sustainability", label: "Sustain.", workspace: "design" },
  { id: "investment", label: "Invest", workspace: "comply" },
  { id: "datacentre", label: "DC", workspace: "analyse" },
];

export default function DetailPanel() {
  const { detailOpen, setDetailOpen, toggleDetail, detailSection, setDetailSection, activeWorkspace } = useWorkspace();
  const {
    activeIntent,
    setGridHighlightSub,
    gridConnectionOpen, setGridConnectionOpen,
    demandForecastOpen, setDemandForecastOpen,
    advancedGridOpen, setAdvancedGridOpen,
    connectionStrategyOpen, setConnectionStrategyOpen,
    dispatchOpen, setDispatchOpen,
    rtmOpen, setRtmOpen,
    sustainabilityOpen, setSustainabilityOpen,
    investmentOpen, setInvestmentOpen,
    dcPanelOpen, setDcPanelOpen,
    dashboardOpen,
    setLayers,
  } = useSite();

  // When activeIntent changes, auto-open the corresponding detail section
  useEffect(() => {
    if (!activeIntent) return;
    const section = INTENT_DETAIL_MAP[activeIntent];
    if (section) {
      setDetailSection(section);
      setDetailOpen(true);
      if (section === "connection") { setGridConnectionOpen(true); setLayers(p => ({ ...p, gridCapacity: true })); }
      if (section === "demand") { setDemandForecastOpen(true); setLayers(p => ({ ...p, demandGsps: true })); }
      if (section === "advanced") setAdvancedGridOpen(true);
      if (section === "strategy") setConnectionStrategyOpen(true);
      if (section === "dispatch") setDispatchOpen(true);
      if (section === "rtm") setRtmOpen(true);
      if (section === "sustainability") setSustainabilityOpen(true);
      if (section === "investment") setInvestmentOpen(true);
      if (section === "datacentre") { setDcPanelOpen(true); setLayers(p => ({ ...p, dcCapacity: true })); }
    }
  }, [activeIntent]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!detailOpen) {
    return (
      <button className="detail-toggle-btn collapsed" onClick={toggleDetail} title="Open detail panel">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M15 18l-6-6 6-6" />
        </svg>
      </button>
    );
  }

  // Filter tabs relevant to current workspace
  const visibleTabs = DETAIL_TABS.filter(t => !t.workspace || t.workspace === activeWorkspace);

  // Check if any deep-dive panel is open (via old mechanism)
  const activeDeepDive = gridConnectionOpen ? "connection"
    : demandForecastOpen ? "demand"
    : advancedGridOpen ? "advanced"
    : connectionStrategyOpen ? "strategy"
    : dispatchOpen ? "dispatch"
    : rtmOpen ? "rtm"
    : sustainabilityOpen ? "sustainability"
    : investmentOpen ? "investment"
    : dcPanelOpen ? "datacentre"
    : null;

  const effectiveSection = activeDeepDive || detailSection;

  const handleTabClick = (tabId) => {
    setDetailSection(tabId);
    // Close all deep-dive panels when switching
    if (tabId === "cards") {
      setGridConnectionOpen(false);
      setDemandForecastOpen(false);
      setAdvancedGridOpen(false);
      setConnectionStrategyOpen(false);
      setDispatchOpen(false);
      setRtmOpen(false);
      setSustainabilityOpen(false);
      setInvestmentOpen(false);
      setDcPanelOpen(false);
    }
    // Open the relevant panel
    if (tabId === "connection") setGridConnectionOpen(true);
    if (tabId === "demand") setDemandForecastOpen(true);
    if (tabId === "advanced") setAdvancedGridOpen(true);
    if (tabId === "strategy") setConnectionStrategyOpen(true);
    if (tabId === "dispatch") setDispatchOpen(true);
    if (tabId === "rtm") setRtmOpen(true);
    if (tabId === "sustainability") setSustainabilityOpen(true);
    if (tabId === "investment") setInvestmentOpen(true);
    if (tabId === "datacentre") setDcPanelOpen(true);
  };

  const closeDeepDive = () => {
    setDetailSection("cards");
    setGridConnectionOpen(false);
    setDemandForecastOpen(false);
    setAdvancedGridOpen(false);
    setConnectionStrategyOpen(false);
    setDispatchOpen(false);
    setRtmOpen(false);
    setSustainabilityOpen(false);
    setInvestmentOpen(false);
    setDcPanelOpen(false);
  };

  return (
    <div className="detail-panel">
      <div className="dp-header">
        {visibleTabs.length > 1 && (
          <div className="dp-tabs">
            {visibleTabs.map((t) => (
              <button
                key={t.id}
                className={`dp-tab${effectiveSection === t.id ? " active" : ""}`}
                onClick={() => handleTabClick(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}
        <button className="dp-close" onClick={toggleDetail} title="Collapse">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M9 18l6-6-6-6" />
          </svg>
        </button>
      </div>

      <div className="dp-body">
        {effectiveSection === "cards" && !dashboardOpen && activeWorkspace === "analyse" && (
          <Suspense fallback={null}>
            <GridPropertyInspector />
          </Suspense>
        )}
        {effectiveSection === "cards" && !dashboardOpen && activeWorkspace !== "grid" && <FloatingCards />}

        {effectiveSection === "connection" && gridConnectionOpen && (
          <ErrorBoundary name="GridConnectionPanel">
            <GridConnectionPanel
              onClose={closeDeepDive}
              onHighlightSubstation={setGridHighlightSub}
              embedded
            />
          </ErrorBoundary>
        )}

        {effectiveSection === "demand" && demandForecastOpen && (
          <ErrorBoundary name="DemandForecastPanel">
            <DemandForecastPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "advanced" && advancedGridOpen && (
          <ErrorBoundary name="AdvancedGridPanel">
            <AdvancedGridPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "strategy" && connectionStrategyOpen && (
          <ErrorBoundary name="ConnectionStrategyPanel">
            <ConnectionStrategyPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "dispatch" && dispatchOpen && (
          <ErrorBoundary name="DispatchPanel">
            <DispatchPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "rtm" && rtmOpen && (
          <ErrorBoundary name="RouteToMarketPanel">
            <RouteToMarketPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "sustainability" && sustainabilityOpen && (
          <ErrorBoundary name="SustainabilityPanel">
            <SustainabilityPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "investment" && investmentOpen && (
          <ErrorBoundary name="InvestmentPanel">
            <InvestmentPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "datacentre" && dcPanelOpen && (
          <ErrorBoundary name="DataCentrePanel">
            <DataCentrePanel onClose={closeDeepDive} />
          </ErrorBoundary>
        )}
      </div>
    </div>
  );
}
