/**
 * CommandPalette — cmdk-powered, keyboard-first.
 *
 * Shortcuts:
 *   ⌘K / Ctrl+K   — toggle open
 *   Esc           — close
 *
 * Commands (L1):
 *   Draw polygon                → switches EditableGeoJsonLayer to DrawPolygonMode
 *   View mode                   → switches to ViewMode
 *   Modify polygon              → switches to ModifyMode
 *   Switch to solar/wind/bess/dc/hybrid
 *   Open chat                   → focuses ChatRail input
 *   Export GeoJSON              → downloads currently-drawn polygon
 */
import React, { useEffect } from "react";
import { Command } from "cmdk";
import { ASSET_CLASSES } from "./capabilities.js";

export default function CommandPalette({
  open,
  onOpenChange,
  onDrawMode,      // (mode) => void
  onAssetClass,    // (cls) => void
  onOpenChat,      // () => void
  onExportGeoJSON, // () => void
}) {
  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        onOpenChange(!open);
      } else if (e.key === "Escape" && open) {
        onOpenChange(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onOpenChange]);

  if (!open) return null;

  const run = (fn) => () => {
    try {
      fn();
    } finally {
      onOpenChange(false);
    }
  };

  return (
    <div className="pc-cmdk-root" onClick={() => onOpenChange(false)}>
      <div onClick={(e) => e.stopPropagation()} className="pc-cmdk">
        <Command label="Canvas command menu">
          <Command.Input autoFocus placeholder="Type a command…" />
          <Command.List>
            <Command.Empty>No matching commands.</Command.Empty>

            <Command.Group heading="Tools">
              <Command.Item onSelect={run(() => onDrawMode?.("draw"))}>
                Draw polygon
              </Command.Item>
              <Command.Item onSelect={run(() => onDrawMode?.("modify"))}>
                Modify polygon
              </Command.Item>
              <Command.Item onSelect={run(() => onDrawMode?.("view"))}>
                View mode
              </Command.Item>
              <Command.Item onSelect={run(() => onExportGeoJSON?.())}>
                Export GeoJSON
              </Command.Item>
            </Command.Group>

            <Command.Group heading="Asset class">
              {ASSET_CLASSES.map((cls) => (
                <Command.Item
                  key={cls}
                  value={`switch to ${cls}`}
                  onSelect={run(() => onAssetClass?.(cls))}
                >
                  <span className={`pc-swatch ${cls}`} />
                  Switch to {cls}
                </Command.Item>
              ))}
            </Command.Group>

            <Command.Group heading="Chat">
              <Command.Item onSelect={run(() => onOpenChat?.())}>
                Open chat
              </Command.Item>
            </Command.Group>
          </Command.List>
        </Command>
      </div>
    </div>
  );
}
