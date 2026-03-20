import React from "react";
import { useWorkspace } from "../../contexts/WorkspaceContext";
import { GridModelProvider } from "../../contexts/GridModelContext";
import { useSite } from "../../SiteContext";
import AssetBrowser from "./AssetBrowser";
import CenterCanvas from "./CenterCanvas";
import DetailPanel from "./DetailPanel";
import ExportHub from "../ExportHub";

function WorkspaceContent({ mapContent, dashboardContent }) {
  const { workflowStage } = useSite();

  return (
    <div className="workspace-layout">
      <AssetBrowser />
      <CenterCanvas dashboardView={dashboardContent}>
        {mapContent}
      </CenterCanvas>
      {workflowStage === "act" ? (
        <div className="detail-panel" style={{ display: "flex", flexDirection: "column" }}>
          <ExportHub />
        </div>
      ) : (
        <DetailPanel />
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
