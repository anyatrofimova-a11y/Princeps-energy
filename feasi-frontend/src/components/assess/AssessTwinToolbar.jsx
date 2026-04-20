import React, { useEffect, useRef, useState } from "react";

/**
 * AssessTwinToolbar — slim 40px bar docked top-right of <AssessProjectTwin />.
 *
 * Props:
 *   layers:          { [key]: bool }
 *   onToggleLayer:   (key) => void
 *   onSetAllLayers:  (bool) => void
 *   cameraPreset:    "plan" | "oblique" | "side" | "orbit"
 *   onCameraPreset:  (preset) => void
 *   onExportPNG:     () => void
 *   onOpenFullTwin:  () => void
 */

const LAYER_LABELS = [
  { key: "satellite",   label: "Satellite base" },
  { key: "terrain",     label: "Terrain (NASADEM)" },
  { key: "landuse",     label: "Land-use (DynamicWorld)" },
  { key: "buildable",   label: "Buildable mask" },
  { key: "polygon",     label: "Project polygon" },
  { key: "substation",  label: "POC substation + line" },
  { key: "grid_lines",  label: "Grid lines (5 km)" },
];

const CAMERA_BUTTONS = [
  { key: "plan",    label: "Plan",     title: "Top-down" },
  { key: "oblique", label: "Oblique",  title: "45° view" },
  { key: "side",    label: "Side",     title: "Horizon level" },
  { key: "orbit",   label: "Orbit",    title: "Auto-rotate" },
];

export default function AssessTwinToolbar({
  layers = {},
  onToggleLayer,
  onSetAllLayers,
  cameraPreset = "oblique",
  onCameraPreset,
  onExportPNG,
  onOpenFullTwin,
}) {
  const [layerMenuOpen, setLayerMenuOpen] = useState(false);
  const wrapRef = useRef(null);

  useEffect(() => {
    if (!layerMenuOpen) return undefined;
    const handler = (e) => {
      if (!wrapRef.current?.contains(e.target)) setLayerMenuOpen(false);
    };
    window.addEventListener("mousedown", handler);
    return () => window.removeEventListener("mousedown", handler);
  }, [layerMenuOpen]);

  const activeCount = LAYER_LABELS.filter(({ key }) => layers[key]).length;

  return (
    <div className="att-wrap" ref={wrapRef}>
      <div className="att-group">
        <button
          type="button"
          className={"att-btn" + (layerMenuOpen ? " att-btn-active" : "")}
          onClick={() => setLayerMenuOpen((v) => !v)}
          title="Toggle map layers"
        >
          <span className="att-btn-label">Layers</span>
          <span className="att-btn-count">{activeCount}/{LAYER_LABELS.length}</span>
        </button>

        {layerMenuOpen && (
          <div className="att-menu" role="menu">
            <div className="att-menu-head">
              <button type="button" className="att-menu-mini" onClick={() => onSetAllLayers?.(true)}>All on</button>
              <button type="button" className="att-menu-mini" onClick={() => onSetAllLayers?.(false)}>All off</button>
            </div>
            {LAYER_LABELS.map(({ key, label }) => (
              <label key={key} className="att-menu-row">
                <input
                  type="checkbox"
                  checked={!!layers[key]}
                  onChange={() => onToggleLayer?.(key)}
                />
                <span>{label}</span>
              </label>
            ))}
          </div>
        )}
      </div>

      <div className="att-sep" />

      <div className="att-group" role="group" aria-label="Camera preset">
        {CAMERA_BUTTONS.map(({ key, label, title }) => (
          <button
            key={key}
            type="button"
            className={"att-cam" + (cameraPreset === key ? " att-cam-active" : "")}
            onClick={() => onCameraPreset?.(key)}
            title={title}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="att-sep" />

      <div className="att-group">
        <button
          type="button"
          className="att-btn"
          onClick={onExportPNG}
          title="Export current view as PNG"
        >
          Export PNG
        </button>
        <button
          type="button"
          className="att-btn att-btn-link"
          onClick={onOpenFullTwin}
          title="Open the full grid twin"
        >
          Open full twin <span className="att-btn-arrow">↗</span>
        </button>
      </div>

      <style>{`
        .att-wrap {
          position: absolute;
          top: 10px;
          right: 10px;
          z-index: 20;
          display: flex;
          align-items: stretch;
          height: 40px;
          background: #FBF8F2;
          border: 1px solid rgba(245, 183, 49, 0.55);
          border-radius: 8px;
          box-shadow: 0 2px 8px rgba(20, 18, 10, 0.12);
          padding: 0 4px;
          font-family: "DM Sans", -apple-system, BlinkMacSystemFont, sans-serif;
        }
        .att-group {
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 0 4px;
          position: relative;
        }
        .att-sep {
          width: 1px;
          margin: 6px 2px;
          background: rgba(20, 18, 10, 0.10);
        }
        .att-btn, .att-cam {
          background: transparent;
          border: 1px solid transparent;
          border-radius: 6px;
          padding: 0 10px;
          height: 30px;
          font-size: 11.5px;
          font-weight: 600;
          color: #2A2317;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          gap: 6px;
          letter-spacing: 0.2px;
          transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
          white-space: nowrap;
        }
        .att-btn:hover, .att-cam:hover {
          background: rgba(245, 183, 49, 0.12);
          border-color: rgba(245, 183, 49, 0.35);
        }
        .att-btn-active, .att-cam-active {
          background: rgba(245, 183, 49, 0.22);
          border-color: #F5B731;
          color: #6B4A0A;
        }
        .att-btn-count {
          font-family: "JetBrains Mono", ui-monospace, Menlo, monospace;
          font-size: 10px;
          color: #7A6A4A;
          background: rgba(245, 183, 49, 0.12);
          padding: 1px 5px;
          border-radius: 4px;
        }
        .att-btn-link { color: #6B4A0A; }
        .att-btn-arrow { font-size: 12px; }
        .att-menu {
          position: absolute;
          top: calc(100% + 6px);
          right: 0;
          min-width: 220px;
          background: #FBF8F2;
          border: 1px solid rgba(245, 183, 49, 0.55);
          border-radius: 8px;
          box-shadow: 0 6px 18px rgba(20, 18, 10, 0.18);
          padding: 6px;
          z-index: 30;
        }
        .att-menu-head {
          display: flex;
          gap: 4px;
          padding: 2px 4px 6px 4px;
          border-bottom: 1px solid rgba(20, 18, 10, 0.08);
          margin-bottom: 4px;
        }
        .att-menu-mini {
          flex: 1;
          background: transparent;
          border: 1px solid rgba(20, 18, 10, 0.12);
          border-radius: 4px;
          font-size: 10.5px;
          font-weight: 600;
          color: #2A2317;
          padding: 3px 6px;
          cursor: pointer;
          font-family: inherit;
        }
        .att-menu-mini:hover {
          background: rgba(245, 183, 49, 0.15);
          border-color: rgba(245, 183, 49, 0.4);
        }
        .att-menu-row {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 5px 6px;
          font-size: 12px;
          color: #2A2317;
          cursor: pointer;
          border-radius: 4px;
        }
        .att-menu-row:hover { background: rgba(245, 183, 49, 0.10); }
        .att-menu-row input { accent-color: #F5B731; }
      `}</style>
    </div>
  );
}
