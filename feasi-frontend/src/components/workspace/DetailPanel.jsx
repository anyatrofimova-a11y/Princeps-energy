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
import CouncilSearchPanel from "../CouncilSearchPanel";
import PlanningIntelligencePanel from "../PlanningIntelligencePanel";
import BESSPanel from "../BESSPanel";
import FinancialModelPanel from "../FinancialModelPanel";
import SiteProspectorPanel from "../SiteProspectorPanel";
import PPAOriginationPanel from "../PPAOriginationPanel";
import PortfolioPanel from "../PortfolioPanel";
import CableRoutingPanel from "../CableRoutingPanel";
import YieldAssessmentPanel from "../YieldAssessmentPanel";
import ConstructionPanel from "../ConstructionPanel";
import WorkflowPanel from "../WorkflowPanel";
import AssessmentSnapshotPanel from "../AssessmentSnapshotPanel";
import ExportPanel from "../ExportPanel";
import AlertRulesPanel from "../AlertRulesPanel";
import ProspectorV2Panel from "../ProspectorV2Panel";
import TerrainAnalysisPanel from "../TerrainAnalysisPanel";
import ReportsHubPanel from "../ReportsHubPanel";
import ElectricalDesignPanel from "../ElectricalDesignPanel";
import DocumentsPanel from "../DocumentsPanel";

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
  { id: "planning", label: "Planning", workspace: "analyse" },
  { id: "bess", label: "BESS", workspace: "analyse" },
  { id: "financial", label: "Finance", workspace: "analyse" },
  { id: "prospector", label: "Prospect", workspace: "analyse" },
  { id: "council", label: "Council", workspace: "comply" },
  { id: "ppa", label: "PPA", workspace: "design" },
  { id: "workflow", label: "Workflow", workspace: "analyse" },
  { id: "snapshot", label: "Snapshot", workspace: "analyse" },
  { id: "export", label: "Export" },
  { id: "alerts", label: "Alerts" },
  { id: "prospector_v2", label: "Prospect V2", workspace: "analyse" },
  { id: "terrain", label: "Terrain", workspace: "analyse" },
  { id: "reports", label: "Reports", workspace: "design" },
  { id: "electrical", label: "Electrical", workspace: "analyse" },
  { id: "documents", label: "Documents", workspace: "design" },
  { id: "portfolio", label: "Portfolio", workspace: "pipeline" },
  { id: "cablerouting", label: "Cable", workspace: "analyse" },
  { id: "yield", label: "Yield", workspace: "analyse" },
  { id: "construction", label: "Build", workspace: "design" },
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
    planningIntelOpen, setPlanningIntelOpen,
    bessPanelOpen, setBessPanelOpen,
    financialModelOpen, setFinancialModelOpen,
    siteProspectorOpen, setSiteProspectorOpen,
    councilSearchOpen, setCouncilSearchOpen,
    ppaOriginationOpen, setPpaOriginationOpen,
    workflowPanelOpen, setWorkflowPanelOpen,
    assessmentSnapshotOpen, setAssessmentSnapshotOpen,
    exportPanelOpen, setExportPanelOpen,
    alertRulesOpen, setAlertRulesOpen,
    prospectorV2Open, setProspectorV2Open,
    terrainAnalysisOpen, setTerrainAnalysisOpen,
    reportsHubOpen, setReportsHubOpen,
    electricalDesignOpen, setElectricalDesignOpen,
    documentsPanelOpen, setDocumentsPanelOpen,
    portfolioPanelOpen, setPortfolioPanelOpen,
    cableRoutingOpen, setCableRoutingOpen,
    yieldAssessmentOpen, setYieldAssessmentOpen,
    constructionPanelOpen, setConstructionPanelOpen,
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
      if (section === "planning") setPlanningIntelOpen(true);
      if (section === "bess") setBessPanelOpen(true);
      if (section === "financial") setFinancialModelOpen(true);
      if (section === "prospector") setSiteProspectorOpen(true);
      if (section === "council") setCouncilSearchOpen(true);
      if (section === "ppa") setPpaOriginationOpen(true);
      if (section === "workflow") setWorkflowPanelOpen(true);
      if (section === "snapshot") setAssessmentSnapshotOpen(true);
      if (section === "export") setExportPanelOpen(true);
      if (section === "alerts") setAlertRulesOpen(true);
      if (section === "prospector_v2") setProspectorV2Open(true);
      if (section === "terrain") setTerrainAnalysisOpen(true);
      if (section === "reports") setReportsHubOpen(true);
      if (section === "electrical") setElectricalDesignOpen(true);
      if (section === "documents") setDocumentsPanelOpen(true);
      if (section === "portfolio") setPortfolioPanelOpen(true);
      if (section === "cablerouting") setCableRoutingOpen(true);
      if (section === "yield") setYieldAssessmentOpen(true);
      if (section === "construction") setConstructionPanelOpen(true);
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
    : planningIntelOpen ? "planning"
    : bessPanelOpen ? "bess"
    : financialModelOpen ? "financial"
    : siteProspectorOpen ? "prospector"
    : councilSearchOpen ? "council"
    : ppaOriginationOpen ? "ppa"
    : workflowPanelOpen ? "workflow"
    : assessmentSnapshotOpen ? "snapshot"
    : exportPanelOpen ? "export"
    : alertRulesOpen ? "alerts"
    : prospectorV2Open ? "prospector_v2"
    : terrainAnalysisOpen ? "terrain"
    : reportsHubOpen ? "reports"
    : electricalDesignOpen ? "electrical"
    : documentsPanelOpen ? "documents"
    : portfolioPanelOpen ? "portfolio"
    : cableRoutingOpen ? "cablerouting"
    : yieldAssessmentOpen ? "yield"
    : constructionPanelOpen ? "construction"
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
      setPlanningIntelOpen(false);
      setBessPanelOpen(false);
      setFinancialModelOpen(false);
      setSiteProspectorOpen(false);
      setCouncilSearchOpen(false);
      setPpaOriginationOpen(false);
      setWorkflowPanelOpen(false);
      setAssessmentSnapshotOpen(false);
      setExportPanelOpen(false);
      setAlertRulesOpen(false);
      setProspectorV2Open(false);
      setTerrainAnalysisOpen(false);
      setReportsHubOpen(false);
      setElectricalDesignOpen(false);
      setDocumentsPanelOpen(false);
      setPortfolioPanelOpen(false);
      setCableRoutingOpen(false);
      setYieldAssessmentOpen(false);
      setConstructionPanelOpen(false);
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
    if (tabId === "planning") setPlanningIntelOpen(true);
    if (tabId === "bess") setBessPanelOpen(true);
    if (tabId === "financial") setFinancialModelOpen(true);
    if (tabId === "prospector") setSiteProspectorOpen(true);
    if (tabId === "council") setCouncilSearchOpen(true);
    if (tabId === "ppa") setPpaOriginationOpen(true);
    if (tabId === "workflow") setWorkflowPanelOpen(true);
    if (tabId === "snapshot") setAssessmentSnapshotOpen(true);
    if (tabId === "export") setExportPanelOpen(true);
    if (tabId === "alerts") setAlertRulesOpen(true);
    if (tabId === "prospector_v2") setProspectorV2Open(true);
    if (tabId === "terrain") setTerrainAnalysisOpen(true);
    if (tabId === "reports") setReportsHubOpen(true);
    if (tabId === "electrical") setElectricalDesignOpen(true);
    if (tabId === "documents") setDocumentsPanelOpen(true);
    if (tabId === "portfolio") setPortfolioPanelOpen(true);
    if (tabId === "cablerouting") setCableRoutingOpen(true);
    if (tabId === "yield") setYieldAssessmentOpen(true);
    if (tabId === "construction") setConstructionPanelOpen(true);
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
    setPlanningIntelOpen(false);
    setBessPanelOpen(false);
    setFinancialModelOpen(false);
    setSiteProspectorOpen(false);
    setCouncilSearchOpen(false);
    setPpaOriginationOpen(false);
    setWorkflowPanelOpen(false);
    setAssessmentSnapshotOpen(false);
    setExportPanelOpen(false);
    setAlertRulesOpen(false);
    setProspectorV2Open(false);
    setTerrainAnalysisOpen(false);
    setReportsHubOpen(false);
    setElectricalDesignOpen(false);
    setDocumentsPanelOpen(false);
    setPortfolioPanelOpen(false);
    setCableRoutingOpen(false);
    setYieldAssessmentOpen(false);
    setConstructionPanelOpen(false);
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

        {effectiveSection === "planning" && planningIntelOpen && (
          <ErrorBoundary name="PlanningIntelligencePanel">
            <PlanningIntelligencePanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "bess" && bessPanelOpen && (
          <ErrorBoundary name="BESSPanel">
            <BESSPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "financial" && financialModelOpen && (
          <ErrorBoundary name="FinancialModelPanel">
            <FinancialModelPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "prospector" && siteProspectorOpen && (
          <ErrorBoundary name="SiteProspectorPanel">
            <SiteProspectorPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "council" && councilSearchOpen && (
          <ErrorBoundary name="CouncilSearchPanel">
            <CouncilSearchPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "ppa" && ppaOriginationOpen && (
          <ErrorBoundary name="PPAOriginationPanel">
            <PPAOriginationPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "workflow" && workflowPanelOpen && (
          <ErrorBoundary name="WorkflowPanel">
            <WorkflowPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "snapshot" && assessmentSnapshotOpen && (
          <ErrorBoundary name="AssessmentSnapshotPanel">
            <AssessmentSnapshotPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "export" && exportPanelOpen && (
          <ErrorBoundary name="ExportPanel">
            <ExportPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "alerts" && alertRulesOpen && (
          <ErrorBoundary name="AlertRulesPanel">
            <AlertRulesPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "prospector_v2" && prospectorV2Open && (
          <ErrorBoundary name="ProspectorV2Panel">
            <ProspectorV2Panel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "portfolio" && portfolioPanelOpen && (
          <ErrorBoundary name="PortfolioPanel">
            <PortfolioPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "cablerouting" && cableRoutingOpen && (
          <ErrorBoundary name="CableRoutingPanel">
            <CableRoutingPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "yield" && yieldAssessmentOpen && (
          <ErrorBoundary name="YieldAssessmentPanel">
            <YieldAssessmentPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "construction" && constructionPanelOpen && (
          <ErrorBoundary name="ConstructionPanel">
            <ConstructionPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "terrain" && terrainAnalysisOpen && (
          <ErrorBoundary name="TerrainAnalysisPanel">
            <TerrainAnalysisPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "reports" && reportsHubOpen && (
          <ErrorBoundary name="ReportsHubPanel">
            <ReportsHubPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "electrical" && electricalDesignOpen && (
          <ErrorBoundary name="ElectricalDesignPanel">
            <ElectricalDesignPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}

        {effectiveSection === "documents" && documentsPanelOpen && (
          <ErrorBoundary name="DocumentsPanel">
            <DocumentsPanel onClose={closeDeepDive} embedded />
          </ErrorBoundary>
        )}
      </div>
    </div>
  );
}
