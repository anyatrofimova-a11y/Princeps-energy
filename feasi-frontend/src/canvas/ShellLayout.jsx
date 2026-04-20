/**
 * ShellLayout — L1 scaffolding for the Unified Canvas.
 *
 * Layout:
 *   ┌─────────────────────────────────────────────────────────┐
 *   │ Top bar (48px): title · class pill · export menu        │
 *   ├───────┬──────────────────────────────────────┬──────────┤
 *   │ Left  │ Centre (UnifiedCanvas)               │ Right    │
 *   │ 280   │                                      │ 400      │
 *   │       │                                      │ CardStack│
 *   ├───────┴──────────────────────────────────────┴──────────┤
 *   │ Bottom rail (140px, collapsible): ChatRail              │
 *   └─────────────────────────────────────────────────────────┘
 *
 * All sizes use react-resizable-panels. Left + right panels are min-collapsible.
 * The component owns:
 *   - drawMode            (view | draw | modify)
 *   - featureCollection   (the currently drawn GeoJSON)
 *   - selectedPolygon     (last completed polygon, fed to cards)
 *   - project asset class (from project, or locally overridden)
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Group as PanelGroup, Panel, Separator as PanelResizeHandle } from "react-resizable-panels";

import "./theme.css";
import UnifiedCanvas from "./UnifiedCanvas.jsx";
import ChatRail from "./ChatRail.jsx";
import CommandPalette from "./CommandPalette.jsx";
import { capabilitiesByGroup, ASSET_CLASSES } from "./capabilities.js";
import api from "../services/api.js";

function useProject(projectId) {
  const [project, setProject] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!projectId) { setProject(null); return; }
    let cancelled = false;
    setLoading(true);

    // Try the spec endpoint first, then fall back to the existing v1 API.
    (async () => {
      let data = null;
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}`);
        if (r.ok) data = await r.json();
      } catch (_) {}
      if (!data) {
        try { data = await api.projects.get(projectId); } catch (_) {}
      }
      if (!cancelled) {
        setProject(data);
        setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [projectId]);

  return { project, loading, setProject };
}

function useRecentProjects() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.projects.list({ limit: 20 });
        if (cancelled) return;
        const list = Array.isArray(data) ? data : data?.items || data?.projects || [];
        setItems(list);
      } catch (_) {
        if (!cancelled) setItems([]);
      }
    })();
    return () => { cancelled = true; };
  }, []);
  return items;
}

export default function ShellLayout() {
  const { projectId } = useParams();
  const { project, setProject } = useProject(projectId);
  const recent = useRecentProjects();

  // Local overrides (fall back until the backend has an asset_class column).
  const [localAssetClass, setLocalAssetClass] = useState(null);
  const assetClass =
    localAssetClass ||
    project?.asset_class ||
    project?.technology || // legacy column: "solar" | "wind" | ...
    "solar";

  const effectiveAssetClass = ASSET_CLASSES.includes(assetClass)
    ? assetClass
    : "solar";

  const [drawMode, setDrawMode] = useState("view");
  const [fc, setFc] = useState({ type: "FeatureCollection", features: [] });
  const [selectedPolygon, setSelectedPolygon] = useState(null);
  const [cmdOpen, setCmdOpen] = useState(false);

  const chatRef = useRef(null);

  const cards = capabilitiesByGroup(effectiveAssetClass, "verdict");

  const handleAssetClass = useCallback(
    (cls) => {
      setLocalAssetClass(cls);
      if (!projectId) return;
      // Optimistic UI + fire-and-forget PATCH. Both endpoints are attempted.
      setProject((p) => (p ? { ...p, asset_class: cls } : p));
      fetch(`/api/projects/${encodeURIComponent(projectId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asset_class: cls }),
      }).catch(() => {});
    },
    [projectId, setProject]
  );

  const handleExportGeoJSON = useCallback(() => {
    const feat = selectedPolygon || (fc.features.length ? fc : null);
    if (!feat) return;
    const payload = selectedPolygon
      ? { type: "FeatureCollection", features: [selectedPolygon] }
      : fc;
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/geo+json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${projectId || "canvas"}-polygon.geojson`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [fc, selectedPolygon, projectId]);

  const openChat = useCallback(() => {
    // Wait a tick so the panel is open before focusing.
    setTimeout(() => chatRef.current?.focus?.(), 50);
  }, []);

  return (
    <div className="princeps-canvas">
      {/* Top bar */}
      <div className="pc-topbar">
        <span className="pc-topbar-title">
          {project?.name || project?.title || (projectId ? `Project ${projectId}` : "Untitled canvas")}
        </span>

        <span className="pc-topbar-pill gold">
          <span className={`pc-swatch ${effectiveAssetClass}`} />
          {effectiveAssetClass}
        </span>

        <select
          className="pc-class-select"
          value={effectiveAssetClass}
          onChange={(e) => handleAssetClass(e.target.value)}
          aria-label="Asset class"
        >
          {ASSET_CLASSES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>

        <div className="pc-topbar-spacer" />

        <button type="button" onClick={() => setCmdOpen(true)} title="Command menu (⌘K)">
          ⌘K
        </button>
        <button type="button" onClick={handleExportGeoJSON} disabled={!selectedPolygon}>
          Export
        </button>
      </div>

      {/* Main grid */}
      <div style={{ flex: 1, minHeight: 0 }}>
        <PanelGroup orientation="vertical" style={{ height: "100%" }}>
          <Panel defaultSize={72} minSize={40}>
            <PanelGroup orientation="horizontal" style={{ height: "100%" }}>
              <Panel defaultSize={18} minSize={0} maxSize={30} collapsible>
                <aside className="pc-left">
                  <div className="pc-left-header">Projects</div>
                  <div className="pc-project-list">
                    {recent.length === 0 && (
                      <div style={{ padding: "8px 10px", fontSize: 12, color: "var(--ink-soft)" }}>
                        No recent projects.
                      </div>
                    )}
                    {recent.map((p) => {
                      const id = p.project_id || p.id;
                      const name = p.name || p.title || id;
                      const sub = p.technology || p.asset_class || "";
                      return (
                        <a
                          key={id}
                          href={`/canvas/${encodeURIComponent(id)}`}
                          className={`pc-project-item ${String(id) === String(projectId) ? "active" : ""}`}
                          style={{ display: "block", textDecoration: "none" }}
                        >
                          <div>{name}</div>
                          {sub && <div className="pc-project-item-sub">{sub}</div>}
                        </a>
                      );
                    })}
                  </div>
                </aside>
              </Panel>

              <PanelResizeHandle className="pc-resize-handle-vertical" />

              <Panel defaultSize={56} minSize={30}>
                <UnifiedCanvas
                  onSelect={setSelectedPolygon}
                  drawMode={drawMode}
                  onDrawModeChange={setDrawMode}
                  featureCollection={fc}
                  onFeatureCollectionChange={setFc}
                />
              </Panel>

              <PanelResizeHandle className="pc-resize-handle-vertical" />

              <Panel defaultSize={26} minSize={0} maxSize={40} collapsible>
                <aside className="pc-right">
                  {cards.length === 0 && (
                    <div className="pc-card-empty">
                      No cards registered for <strong>{effectiveAssetClass}</strong> yet.
                    </div>
                  )}
                  {cards.map(({ id, component: Card }) => (
                    <Card
                      key={id}
                      polygon={selectedPolygon}
                      projectId={projectId || null}
                      assetClass={effectiveAssetClass}
                    />
                  ))}
                </aside>
              </Panel>
            </PanelGroup>
          </Panel>

          <PanelResizeHandle className="pc-resize-handle-horizontal" />

          <Panel
            defaultSize={28}
            minSize={0}
            maxSize={60}
            collapsible
            collapsedSize={4}
          >
            <ChatRail
              ref={chatRef}
              projectId={projectId || null}
              assetClass={effectiveAssetClass}
              polygon={selectedPolygon}
            />
          </Panel>
        </PanelGroup>
      </div>

      <CommandPalette
        open={cmdOpen}
        onOpenChange={setCmdOpen}
        onDrawMode={setDrawMode}
        onAssetClass={handleAssetClass}
        onOpenChat={openChat}
        onExportGeoJSON={handleExportGeoJSON}
      />
    </div>
  );
}
