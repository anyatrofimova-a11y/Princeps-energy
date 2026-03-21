import React, { lazy, Suspense } from "react";
import { useWorkspace } from "../../contexts/WorkspaceContext";
import { GridModelProvider } from "../../contexts/GridModelContext";
import { useSite } from "../../SiteContext";
import AssetBrowser from "./AssetBrowser";
import CenterCanvas from "./CenterCanvas";
import DetailPanel from "./DetailPanel";

const ExportHub = lazy(() => import("../ExportHub"));
const ProjectPipeline = lazy(() => import("../ProjectPipeline"));

function WorkspaceContent({ mapContent, dashboardContent }) {
  const { workflowStage } = useSite();
  const { detailOpen } = useWorkspace();

  return (
    <div className="workspace-layout">
      <AssetBrowser />
      <CenterCanvas dashboardView={dashboardContent}>
        {mapContent}
      </CenterCanvas>
      {detailOpen && (
        <Suspense fallback={null}>
          {workflowStage === "act" ? (
            <div className="detail-panel">
              <ExportHub />
            </div>
          ) : (
            <DetailPanel />
          )}
        </Suspense>
      )}
    </div>
  );
}

export default function WorkspaceRouter({ mapContent, dashboardContent }) {
  const { activeWorkspace } = useWorkspace();
  const { setPickedLocation } = useSite();

  // Pipeline is a dedicated full-content workspace (no map, no panels)
  if (activeWorkspace === "pipeline") {
    return (
      <Suspense fallback={<div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--cds-text-helper)" }}>Loading pipeline...</div>}>
        <ProjectPipeline
          onSelectProject={(p) => {
            if (p.lat && p.lon) setPickedLocation({ lat: p.lat, lon: p.lon });
          }}
        />
      </Suspense>
    );
  }

  // Wrap analyse workspace in GridModelProvider
  if (activeWorkspace === "analyse") {
    return (
      <GridModelProvider>
        <WorkspaceContent mapContent={mapContent} dashboardContent={dashboardContent} />
      </GridModelProvider>
    );
  }

  return <WorkspaceContent mapContent={mapContent} dashboardContent={dashboardContent} />;
}
