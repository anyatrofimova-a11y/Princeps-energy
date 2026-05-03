/**
 * DesignViewModeTabs — Plan / Oblique / Construction / Drone mode switcher.
 *
 * Keyboard shortcuts: ⌘1 … ⌘4 (Ctrl+1…4 on non-mac).
 *
 * The tabs themselves are pure — they call back to DesignCanvas with a mode
 * key and the DesignCanvas's existing mapRef is driven via an effect hook
 * exported below (applyViewModeToMap). Construction mode surfaces a month
 * scrubber; Drone mode exposes a "stop" toggle for the 60s bearing orbit.
 */
import React, { useCallback, useEffect, useRef } from "react";

export const VIEW_MODES = [
  { key: "plan",         label: "Plan",         shortcut: "⌘1", hint: "Top-down orthographic" },
  { key: "oblique",      label: "Oblique",      shortcut: "⌘2", hint: "Glint-style 3D tilt" },
  { key: "construction", label: "Construction", shortcut: "⌘3", hint: "Phase-by-month scrubber" },
  { key: "drone",        label: "Drone",        shortcut: "⌘4", hint: "Orbiting camera" },
];

export const VIEW_MODE_CAMERA = {
  plan:         { pitch: 0,  bearing: 0,   zoom: 17.4 },
  oblique:      { pitch: 55, bearing: 0,   zoom: 17.0 },
  construction: { pitch: 35, bearing: 0,   zoom: 17.2 },
  drone:        { pitch: 60, bearing: 0,   zoom: 16.8 },
};

/**
 * Imperatively ease a Mapbox map to the camera for a given view mode.
 * Safe on null maps; returns a cleanup function (for drone orbit).
 */
export function applyViewModeToMap(map, mode, { onOrbitTick } = {}) {
  if (!map || map._removed) return () => {};
  const cam = VIEW_MODE_CAMERA[mode];
  if (!cam) return () => {};
  try {
    map.easeTo({ pitch: cam.pitch, bearing: cam.bearing, zoom: cam.zoom, duration: 900 });
  } catch { /* map not loaded yet */ }

  if (mode !== "drone") return () => {};

  // Drone orbit — 60s full rotation.
  let raf;
  let startTs = null;
  const step = (ts) => {
    if (!map || map._removed) return;
    if (startTs == null) startTs = ts;
    const elapsed = (ts - startTs) / 1000; // seconds
    const bearing = (elapsed / 60) * 360 % 360;
    try { map.setBearing(bearing); } catch { /* ignore */ }
    if (onOrbitTick) onOrbitTick(bearing);
    raf = requestAnimationFrame(step);
  };
  raf = requestAnimationFrame(step);
  return () => { if (raf) cancelAnimationFrame(raf); };
}

export default function DesignViewModeTabs({
  mode = "plan",
  onChange = () => {},
  // Construction mode scrubber
  constructionMonth = 0,
  onConstructionMonthChange = () => {},
  constructionMonthsMax = 18,
  // Drone orbit toggle
  droneOrbiting = true,
  onDroneOrbitingChange = () => {},
}) {
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  // ⌘1–⌘4 shortcuts.
  useEffect(() => {
    const handler = (e) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      const idx = Number(e.key);
      if (!Number.isFinite(idx) || idx < 1 || idx > VIEW_MODES.length) return;
      const target = VIEW_MODES[idx - 1];
      if (!target) return;
      e.preventDefault();
      onChangeRef.current(target.key);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const switchMode = useCallback((m) => onChange(m), [onChange]);

  const phaseLabel = (() => {
    if (constructionMonth < 6) return "Phase 1 · Shell + civils";
    if (constructionMonth < 12) return "Phase 2 · Equipment install";
    return "Phase 3 · Commissioning";
  })();

  return (
    <div className="dc-vm-bar" role="tablist" aria-label="Design view mode">
      {VIEW_MODES.map((vm) => (
        <button
          key={vm.key}
          type="button"
          role="tab"
          aria-selected={mode === vm.key}
          className={"dc-vm-tab" + (mode === vm.key ? " dc-vm-tab-active" : "")}
          onClick={() => switchMode(vm.key)}
          title={`${vm.hint}  (${vm.shortcut})`}
        >
          <span className="dc-vm-tab-label">{vm.label}</span>
          <span className="dc-vm-tab-kbd">{vm.shortcut}</span>
        </button>
      ))}

      {mode === "construction" && (
        <div className="dc-vm-construction" aria-label="Construction month scrubber">
          <span className="dc-vm-month-label">Month {constructionMonth} / {constructionMonthsMax}</span>
          <input
            type="range"
            min="0"
            max={constructionMonthsMax}
            step="1"
            value={constructionMonth}
            onChange={(e) => onConstructionMonthChange(Number(e.target.value))}
            className="dc-vm-month-range"
          />
          <span className="dc-vm-month-phase">{phaseLabel}</span>
        </div>
      )}

      {mode === "drone" && (
        <div className="dc-vm-drone" aria-label="Drone orbit controls">
          <button
            type="button"
            className={"dc-vm-drone-btn" + (droneOrbiting ? " dc-vm-drone-btn-on" : "")}
            onClick={() => onDroneOrbitingChange(!droneOrbiting)}
            title={droneOrbiting ? "Stop orbit" : "Start orbit"}
          >
            {droneOrbiting ? "■ Stop" : "▶ Orbit"}
          </button>
          <span className="dc-vm-drone-hint">60s bearing 0→360</span>
        </div>
      )}
    </div>
  );
}
