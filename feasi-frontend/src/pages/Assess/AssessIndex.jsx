import React, { Suspense, lazy } from "react";

const AssessProjectTwin = lazy(() => import("../../components/assess/AssessProjectTwin"));

/**
 * AssessIndex — standalone Princeps shell for the Assess surface.
 *
 * The main Assess tab lives inside the verb-based workspace (see
 * components/workspace/AssessTab.jsx). This page exists so that the twin
 * can be hit as a dedicated route (e.g. /assess?project=<id>) or as a
 * permalink from chat/reports without requiring the full workspace shell.
 *
 * Visual: Princeps light-gold chrome (ivory surface, gold accents, DM Sans).
 */
export default function AssessIndex({ projectId: projectIdProp = null, project = null }) {
  const params = typeof window !== "undefined"
    ? new URLSearchParams(window.location.search)
    : null;
  const projectId = projectIdProp
    || project?.project_id
    || project?.id
    || params?.get("project")
    || null;

  return (
    <div className="assess-index">
      <header className="ai-head">
        <div className="ai-eyebrow">Princeps · Assess</div>
        <h1 className="ai-title">Project Twin</h1>
        <p className="ai-lede">
          Focused 3D context — terrain, land-use, buildable mask, nearest grid.
          Toggle layers, change camera, export PNG. {projectId && (
            <span className="ai-pid">project: <code>{projectId}</code></span>
          )}
        </p>
      </header>

      <main className="ai-main">
        <Suspense fallback={<div className="ai-loading">Loading project twin…</div>}>
          <AssessProjectTwin
            projectId={projectId}
            polygon_wkt={project?.polygon_wkt || null}
            tech={project?.workload_type || project?.tech || null}
            capacity_mw={project?.capacity_mw || null}
          />
        </Suspense>
      </main>

      <style>{`
        .assess-index {
          min-height: 100vh;
          background: #F7F8FA;
          font-family: "DM Sans", -apple-system, BlinkMacSystemFont, sans-serif;
          color: #0F1318;
        }
        .ai-head {
          padding: 32px 40px 16px 40px;
          border-bottom: 1px solid #E8EAED;
          background: #FBF8F2;
        }
        .ai-eyebrow {
          font-size: 11px; font-weight: 700;
          letter-spacing: 1.4px; text-transform: uppercase;
          color: #6B4A0A; margin-bottom: 6px;
        }
        .ai-title {
          font-size: 28px; font-weight: 600;
          margin: 0 0 8px 0;
          letter-spacing: -0.5px;
        }
        .ai-lede {
          font-size: 13.5px; line-height: 1.55;
          color: #4B5563;
          max-width: 720px; margin: 0;
        }
        .ai-pid {
          margin-left: 8px;
          font-family: "JetBrains Mono", ui-monospace, Menlo, monospace;
          font-size: 11px;
          color: #6B4A0A;
          background: rgba(245, 183, 49, 0.12);
          padding: 2px 6px; border-radius: 4px;
        }
        .ai-main {
          padding: 24px 40px 40px 40px;
        }
        .ai-loading {
          height: 600px;
          display: flex; align-items: center; justify-content: center;
          color: #4B5563;
          font-family: "JetBrains Mono", ui-monospace, Menlo, monospace;
          font-size: 12px;
          background: #FBF8F2;
          border: 1px solid rgba(245, 183, 49, 0.25);
          border-radius: 12px;
        }
      `}</style>
    </div>
  );
}
