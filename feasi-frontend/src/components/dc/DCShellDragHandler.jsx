/**
 * DCShellDragHandler — drag-with-snap logic for the DC shell/cooling group.
 *
 * Not a visual component — exports a `makeShellDragHandlers` hook factory that
 * returns { onDragStart, onDrag, onDragEnd, status, pointerLonLat } wired to
 * setLat/setLon with a buildable-mask constraint.
 *
 *   status: "idle" | "ok" | "warn" | "blocked"
 *     ok      — pointer inside buildable mask
 *     warn    — inside parcel but inside a restriction
 *     blocked — outside parcel entirely
 *
 *   On dragEnd:
 *     ok      — commit at final pointer
 *     warn    — commit (user override — restriction is a warning, not a hard
 *                block, because BOT-G data may be incomplete)
 *     blocked — revert to the last valid position captured at dragStart
 *
 * Separating this logic out keeps DCDesignTwin.jsx focused on rendering.
 */
import { useRef, useState, useCallback } from "react";

export default function useShellDragHandlers({
  lat,
  lon,
  setLat,
  setLon,
  mapRef,
  isBuildable,
  parcelContains,
  restrictionAt,
}) {
  const stateRef = useRef({
    active: false,
    startLonLat: null,
    startPointerLonLat: null,
    lastValidLonLat: null,
  });
  const [status, setStatus] = useState("idle");
  const [pointerLonLat, setPointerLonLat] = useState(null);
  const [pointerHint, setPointerHint] = useState(null);

  const onDragStart = useCallback((info, event) => {
    if (!info?.coordinate) return;
    event?.stopPropagation?.();
    stateRef.current = {
      active: true,
      startLonLat: [lon, lat],
      startPointerLonLat: info.coordinate,
      lastValidLonLat: [lon, lat],
    };
    if (mapRef?.current) { try { mapRef.current.dragPan.disable(); } catch { /* noop */ } }
    setStatus(isBuildable(lon, lat) ? "ok" : parcelContains(lon, lat) ? "warn" : "blocked");
    setPointerLonLat([lon, lat]);
  }, [lat, lon, mapRef, isBuildable, parcelContains]);

  const onDrag = useCallback((info, event) => {
    const st = stateRef.current;
    if (!st.active || !info?.coordinate) return;
    event?.stopPropagation?.();
    const [pLon0, pLat0] = st.startPointerLonLat;
    const dLon = info.coordinate[0] - pLon0;
    const dLat = info.coordinate[1] - pLat0;
    const newLon = st.startLonLat[0] + dLon;
    const newLat = st.startLonLat[1] + dLat;

    const inside = isBuildable(newLon, newLat);
    const inParcel = parcelContains(newLon, newLat);
    const next = inside ? "ok" : inParcel ? "warn" : "blocked";
    setStatus(next);
    setPointerLonLat([newLon, newLat]);

    if (next === "ok") {
      st.lastValidLonLat = [newLon, newLat];
      setPointerHint(null);
    } else if (next === "warn") {
      const r = restrictionAt(newLon, newLat);
      setPointerHint(r ? `In ${r.class.replace("restricted_", "")} zone (${r.name})` : "Inside restriction");
    } else {
      setPointerHint("Outside parcel — will snap back");
    }

    // Live-update the site centroid only for ok/warn. For blocked we freeze the
    // shell at the last valid position so the user sees it "resist" the edge.
    if (next !== "blocked") {
      setLat(newLat);
      setLon(newLon);
    }
  }, [isBuildable, parcelContains, restrictionAt, setLat, setLon]);

  const onDragEnd = useCallback(() => {
    const st = stateRef.current;
    const map = mapRef?.current;
    try { map?.dragPan.enable(); } catch { /* noop */ }

    if (status === "blocked" && st.lastValidLonLat) {
      setLon(st.lastValidLonLat[0]);
      setLat(st.lastValidLonLat[1]);
      setPointerHint("Snapped back to last valid position");
      setTimeout(() => setPointerHint(null), 1800);
    }
    stateRef.current = {
      active: false,
      startLonLat: null,
      startPointerLonLat: null,
      lastValidLonLat: null,
    };
    setTimeout(() => setStatus("idle"), 200);
    setPointerLonLat(null);
  }, [mapRef, setLat, setLon, status]);

  return {
    onDragStart,
    onDrag,
    onDragEnd,
    status,
    pointerLonLat,
    pointerHint,
    isActive: () => stateRef.current.active,
  };
}

/** Constraint outline colours keyed by status. deck.gl [r,g,b,a] */
export const DRAG_STATUS_COLORS = {
  idle:    [88, 28, 135, 255],    // purple (default shell edge)
  ok:      [34, 197, 94, 255],    // green
  warn:    [245, 158, 11, 255],   // amber
  blocked: [239, 68, 68, 255],    // red
};
