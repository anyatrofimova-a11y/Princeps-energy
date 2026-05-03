/**
 * useDesignProject — load a project record for the Site Designer 3D route,
 * extract coordinate + sizing context, and synthesise a buildable-area
 * polygon if the project has no explicit red-line.
 *
 * Purpose
 * -------
 * The `/design/:projectId` route previously mounted TwinLazy with only the
 * project's `polygon_wkt`. For projects ingested from REPD/TEC the polygon
 * is frequently null, so the 3D centroid fell back to the London default
 * ([-0.1276, 51.5074] — Trafalgar Square). This hook fixes that by:
 *
 *   1. Fetching `/api/v1/projects/{id}` (canonical) with a shim fallback
 *      if the record cannot be found (standalone dev mounts).
 *   2. Normalising the field names that downstream components expect
 *      (tech, capacity_mw, cooling_type, tier, lat, lon, dno, stage).
 *   3. Synthesising a ~300 × 300 m WGS-84 polygon around (lat, lon) when
 *      no explicit polygon_wkt is available so TwinRoot centroid logic
 *      lands on the project site, not the London fallback.
 *
 * Usage
 * -----
 *   const { project, loading, notFound } = useDesignProject(projectId);
 *
 * The returned `project` always has `.lat` and `.lon` set (even on the
 * dev-shim path so the twin still renders somewhere sensible).
 */
import { useEffect, useState } from "react";
import api from "../services/api";

const DEFAULT_BOX_METRES = 300;
const DEG_PER_M_LAT = 1 / 111_320;
function degPerMLon(lat) { return 1 / (111_320 * Math.cos((lat * Math.PI) / 180)); }

/** Synthesise a closed WKT polygon ring around (lat, lon) at the given
 *  half-size in metres. Used when the project has no explicit red-line. */
function buildBoxWkt(lat, lon, halfSizeM = DEFAULT_BOX_METRES / 2) {
  if (lat == null || lon == null) return null;
  const dLon = halfSizeM * degPerMLon(lat);
  const dLat = halfSizeM * DEG_PER_M_LAT;
  const ring = [
    [lon - dLon, lat - dLat],
    [lon + dLon, lat - dLat],
    [lon + dLon, lat + dLat],
    [lon - dLon, lat + dLat],
    [lon - dLon, lat - dLat],
  ];
  const pts = ring.map(([x, y]) => `${x} ${y}`).join(", ");
  return `POLYGON((${pts}))`;
}

/** Map arbitrary tech strings onto the 4-value TwinRoot vocabulary. */
function normaliseTech(raw) {
  const t = String(raw || "").toLowerCase().trim();
  if (!t) return "bess";
  if (t === "data_centre" || t === "datacentre" || t === "dc" || t === "data_center") return "dc";
  if (t === "battery" || t === "storage" || t === "bess") return "bess";
  if (t === "solar" || t === "pv") return "solar";
  if (t === "wind" || t === "onshore_wind" || t === "offshore_wind") return "wind";
  return t;
}

/** Derive a sensible default cooling type when the project record doesn't
 *  carry one. Hyperscale UK DC defaults to hybrid (chillers + free cooling). */
function defaultCoolingType(project) {
  const c = project?.cooling_type || project?.cooling || project?.meta?.cooling_type;
  if (c) return String(c);
  return "hybrid";
}

export default function useDesignProject(projectId) {
  const [project, setProject] = useState(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!projectId) {
      setLoading(false);
      setNotFound(true);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setNotFound(false);

    (async () => {
      let data = null;
      // 1. Canonical v1 endpoint via the shared api client.
      try {
        data = await api.projects?.get?.(projectId);
      } catch { /* fall through */ }
      // 2. Legacy `/api/projects/{id}` fallback (matches the prior DesignPage
      //    code path so no regression for older backend builds).
      if (!data) {
        try {
          const r = await fetch(`/api/projects/${encodeURIComponent(projectId)}`);
          if (r.ok) data = await r.json();
        } catch { /* ignore */ }
      }

      if (cancelled) return;

      let isShim = false;
      if (!data) {
        // Dev shim — keeps the twin mountable when the backend isn't up.
        // Slough Trading Estate coords so the canvas shows somewhere real.
        data = {
          project_id: projectId,
          name: projectId,
          technology: "data_centre",
          capacity_mw: 40,
          lat: 51.5260,
          lon: -0.6155,
        };
        isShim = true;
      }

      const lat = data.lat ?? data.latitude ?? data.centroid_lat ?? null;
      const lon = data.lon ?? data.longitude ?? data.centroid_lon ?? null;
      const capacity_mw = data.capacity_mw ?? data.it_load_mw ?? data.capacity ?? 50;
      const tech = normaliseTech(data.technology || data.workload_type || data.tech);
      const cooling_type = defaultCoolingType(data);
      const polygon_wkt = data.polygon_wkt
        || data.site_polygon_wkt
        || buildBoxWkt(lat, lon);

      const normalised = {
        ...data,
        lat,
        lon,
        capacity_mw,
        tech,
        technology: data.technology || tech,
        cooling_type,
        tier: data.tier ?? 3,
        redundancy: data.redundancy ?? "N+1",
        stage: data.stage ?? null,
        dno: data.dno ?? null,
        polygon_wkt,
      };

      setProject(normalised);
      setNotFound(isShim);
      setLoading(false);
    })();

    return () => { cancelled = true; };
  }, [projectId]);

  return { project, loading, notFound };
}
