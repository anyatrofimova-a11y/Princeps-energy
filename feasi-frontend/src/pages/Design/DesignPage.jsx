import React from "react";
import { useParams, useNavigate } from "react-router-dom";
import Sidebar from "../../components/shell/Sidebar";
import TwinLazy from "../../components/twin3d/TwinLazy";
import useDesignProject from "../../hooks/useDesignProject";

/**
 * DesignPage — full-screen 3D Site Twin at /design/:projectId.
 *
 * Layout:
 *   ┌─────────┬──────────────────────────────────────┐
 *   │ Sidebar │ Header (32px) — project title · tech │
 *   │ (240)   ├──────────────────────────────────────┤
 *   │         │                                      │
 *   │         │   <TwinLazy mode="oblique">          │
 *   │         │                                      │
 *   └─────────┴──────────────────────────────────────┘
 *
 * Loads project shape the same way ShellLayout does (spec endpoint first,
 * fall back to api.projects.get). Passes polygon_wkt + tech + capacity_mw
 * through to TwinLazy. Header has a back-button to return to the workspace.
 */
export default function DesignPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();

  // Project context — handles the real fetch + normalisation + fallbacks.
  // `project.lat`/`project.lon` are always non-null here (dev-shim path
  // synthesises Slough coords so the twin always mounts somewhere real).
  const { project, loading: loadingProject, notFound } = useDesignProject(projectId);

  const tech = project?.tech || project?.technology || "bess";
  const capacity = project?.capacity_mw || 50;
  const polygon = project?.polygon_wkt || null;
  const lat = project?.lat ?? null;
  const lon = project?.lon ?? null;
  const cooling = project?.cooling_type || "hybrid";
  // Point-of-connection (grid substation) — used by intelligent DC layout
  // to anchor the transformer yard on the correct polygon edge.
  const pocLat = project?.poc_lat ?? project?.poc_latitude ?? project?.substation_lat ?? null;
  const pocLon = project?.poc_lon ?? project?.poc_longitude ?? project?.substation_lon ?? null;
  // Public-road access point — anchors gatehouse + office/NOC.
  const roadLat = project?.road_lat ?? project?.access_road_lat ?? null;
  const roadLon = project?.road_lon ?? project?.access_road_lon ?? null;

  return (
    <div className="dp-root">
      <Sidebar />

      <main className="dp-main">
        <header className="dp-head">
          <button
            type="button"
            className="dp-back"
            onClick={() => navigate(-1)}
            aria-label="Back"
            title="Back"
          >←</button>
          <h1 className="dp-title">
            {loadingProject ? "Loading…" : (project?.name || projectId || "Site Twin")}
            {notFound && <span className="dp-stub-tag">dev stub</span>}
          </h1>
          <span className="dp-tech">{String(tech).toUpperCase()}</span>
          <span className="dp-cap">{capacity} MW</span>
          <div className="dp-spacer" />
          <button
            type="button"
            className="dp-link"
            onClick={() => navigate(`/?project=${encodeURIComponent(projectId || "")}`)}
          >Workspace →</button>
        </header>

        <section className="dp-twin-wrap">
          {project && (
            <TwinLazy
              key={projectId}
              projectId={projectId}
              polygon_wkt={polygon}
              tech={tech}
              capacity_mw={capacity}
              lat={lat}
              lon={lon}
              cooling_type={cooling}
              tier={project?.tier ?? 3}
              redundancy={project?.redundancy ?? "N+1"}
              poc_lat={pocLat}
              poc_lon={pocLon}
              road_lat={roadLat}
              road_lon={roadLon}
              mode="oblique"
              onError={(err) => {
                // eslint-disable-next-line no-console
                console.warn("[DesignPage] twin mount failed:", err?.message);
              }}
            />
          )}
        </section>
      </main>

      <style>{`
        .dp-root {
          display: flex;
          width: 100vw; height: 100vh;
          overflow: hidden;
          background: #F7F8FA;
          font-family: "DM Sans", -apple-system, sans-serif;
        }
        .dp-main {
          flex: 1;
          display: flex;
          flex-direction: column;
          min-width: 0;
        }
        .dp-head {
          display: flex;
          align-items: center;
          gap: 14px;
          padding: 10px 22px;
          background: #FFFFFF;
          border-bottom: 1px solid #E8E5DF;
          height: 48px;
          flex-shrink: 0;
        }
        .dp-back {
          width: 28px; height: 28px;
          border: 1px solid #E8E5DF; background: #fff;
          border-radius: 6px; cursor: pointer;
          color: #1a1a1a; font-size: 14px; font-weight: 600;
        }
        .dp-back:hover { border-color: #C9A64B; color: #B5912F; }
        .dp-title {
          margin: 0;
          font-size: 15px;
          font-weight: 700;
          color: #0F1318;
          letter-spacing: -0.01em;
        }
        .dp-stub-tag {
          display: inline-block;
          margin-left: 8px;
          padding: 1px 6px;
          background: rgba(201, 166, 75, 0.12);
          color: #B5912F;
          border: 1px solid rgba(201, 166, 75, 0.35);
          border-radius: 4px;
          font-family: "JetBrains Mono", monospace;
          font-size: 9px;
          font-weight: 700;
          letter-spacing: 0.04em;
          text-transform: uppercase;
          vertical-align: middle;
        }
        .dp-tech, .dp-cap {
          font-family: "JetBrains Mono", monospace;
          font-size: 10px;
          font-weight: 700;
          letter-spacing: 0.04em;
          color: #6B6560;
          background: #F7F8FA;
          border: 1px solid #E8E5DF;
          padding: 3px 8px;
          border-radius: 5px;
        }
        .dp-spacer { flex: 1; }
        .dp-link {
          background: transparent;
          border: 1px solid #C9A64B;
          color: #B5912F;
          font-family: inherit;
          font-size: 12px;
          font-weight: 700;
          padding: 5px 12px;
          border-radius: 6px;
          cursor: pointer;
        }
        .dp-link:hover { background: #C9A64B; color: #fff; }

        .dp-twin-wrap {
          position: relative;
          flex: 1;
          min-height: 0;
          background: #0F1318;
          overflow: hidden;
        }
      `}</style>
    </div>
  );
}
