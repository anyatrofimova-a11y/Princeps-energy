import React, { lazy, Suspense } from "react";
import { useWorkspace } from "../../contexts/WorkspaceContext";
import { GridModelProvider } from "../../contexts/GridModelContext";
import { useSite } from "../../SiteContext";
import AssetBrowser from "./AssetBrowser";
import CenterCanvas from "./CenterCanvas";
import DetailPanel from "./DetailPanel";

const ExportHub = lazy(() => import("../ExportHub"));

function WorkspaceContent({ mapContent, dashboardContent }) {
  const { workflowStage } = useSite();
  const { detailOpen } = useWorkspace();

  return (
    <div className="workspace-layout">
      <AssetBrowser />
      <CenterCanvas dashboardView={dashboardContent}>
        {mapContent}
      </CenterCanvas>
      {/* Detail panel: only shows when explicitly opened (Ctrl+D) — not by default */}
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

  // Wrap grid workspace in GridModelProvider for shared state across all grid views
  if (activeWorkspace === "analyse") {
    return (
      <GridModelProvider>
        <WorkspaceContent mapContent={mapContent} dashboardContent={dashboardContent} />
      </GridModelProvider>
    );
  }

  return <WorkspaceContent mapContent={mapContent} dashboardContent={dashboardContent} />;
}
