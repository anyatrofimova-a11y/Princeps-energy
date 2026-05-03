import React, { useEffect, useState, useCallback } from "react";

/**
 * SearchZone — "one-click PV/BESS risk check" button.
 *
 * Pattern from the Rémi Bégaud LinkedIn demo (Apr 2026): the user defines
 * a search zone, the system scans every available spatial layer, returns
 * a manifest of what's in the zone, and animates the constraint reveal.
 *
 * Interaction model:
 *   1. User clicks the button → enters "draw" mode (cursor = crosshair).
 *   2. Two clicks on the map define two opposite corners of the bbox.
 *   3. Component dispatches `princeps:scan-zone` with the bbox.
 *   4. MapView handles the bbox drawing + the actual /api/scan/zone call
 *      + the layer reveal animation + corridor + union fetches.
 *   5. SearchZone updates its badge with "found N layers" once the scan
 *      result event comes back via `princeps:scan-result`.
 *
 * Tiny on purpose — the heavy lifting lives in MapView so the map ref
 * doesn't need to leak through props.
 */
export default function SearchZone() {
  const [mode, setMode] = useState("idle"); // idle | drawing | scanning | done
  const [summary, setSummary] = useState(null);

  const start = useCallback(() => {
    setMode("drawing");
    setSummary(null);
    window.dispatchEvent(new CustomEvent("princeps:scan-zone", { detail: { phase: "start" } }));
  }, []);

  const cancel = useCallback(() => {
    setMode("idle");
    window.dispatchEvent(new CustomEvent("princeps:scan-zone", { detail: { phase: "cancel" } }));
  }, []);

  useEffect(() => {
    const onPhase = (e) => {
      const phase = e.detail?.phase;
      if (phase === "drawing-complete") setMode("scanning");
      if (phase === "cancel") setMode("idle");
    };
    const onResult = (e) => {
      const r = e.detail || {};
      const groups = r.groups || [];
      const totalActive = groups.reduce((a, g) => a + (g.with_features || 0), 0);
      const totalAvail  = groups.reduce((a, g) => a + (g.available || 0), 0);
      setSummary({ totalActive, totalAvail, groups });
      setMode("done");
    };
    window.addEventListener("princeps:scan-zone", onPhase);
    window.addEventListener("princeps:scan-result", onResult);
    return () => {
      window.removeEventListener("princeps:scan-zone", onPhase);
      window.removeEventListener("princeps:scan-result", onResult);
    };
  }, []);

  const labelByMode = {
    idle:     "Scan area",
    drawing:  "Click two corners…",
    scanning: "Scanning layers…",
    done:     summary
      ? `${summary.totalActive}/${summary.totalAvail} layers — re-scan`
      : "Scan area",
  };

  return (
    <div className="sz-root">
      <button
        type="button"
        className={`sz-btn sz-btn-${mode}`}
        onClick={mode === "drawing" || mode === "scanning" ? cancel : start}
        title="One-click constraint + grid scan over a drawn area"
      >
        <span className="sz-icon" aria-hidden>⌖</span>
        <span className="sz-label">{labelByMode[mode]}</span>
      </button>
      {mode === "done" && summary && (
        <div className="sz-summary">
          {summary.groups
            .filter((g) => g.with_features > 0)
            .slice(0, 4)
            .map((g) => (
              <span key={g.group} className="sz-chip">
                {g.group.replace(/^\d+\s*-\s*/, "")} · {g.with_features}
              </span>
            ))}
        </div>
      )}
    </div>
  );
}
