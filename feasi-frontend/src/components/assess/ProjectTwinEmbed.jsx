import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { GeoJsonLayer, ScatterplotLayer, ArcLayer } from "@deck.gl/layers";
import AgenticKPIRail from "./AgenticKPIRail";
import TwinOverlayToggles from "./TwinOverlayToggles";
import { DEFAULT_LAYERS, loadPrefs, savePrefs, fetchTwinFeeds } from "./twinData";

mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN || "";

/**
 * ProjectTwinEmbed — Mapbox GL + deck.gl, centred on a project's lat/lon
 * at ~10 ha scale. Overlays are filtered to the project (site boundary,
 * nearest substation + arc, 500 m designations, flood zones, land use,
 * queue projects within 10 km). All feeds fail gracefully — missing
 * data renders a "pending" badge on the left toggle rail, never an error.
 *
 * Emits `princeps-chat` events via the AgenticKPIRail's "Ask agent" button.
 */
export default function ProjectTwinEmbed({ project, onOpenSubstation, onOpenParcel }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const overlayRef = useRef(null);

  const [layers, setLayers] = useState(loadPrefs);
  const [feeds, setFeeds] = useState({});
  const [statuses, setStatuses] = useState({});
  const [tooltip, setTooltip] = useState(null);
  const [, setMapReady] = useState(false);

  const lat = project?.lat;
  const lon = project?.lon;
  const pid = project?.id || project?.project_id;
  const hasToken = !!mapboxgl.accessToken;
  const hasCoords = typeof lat === "number" && typeof lon === "number";

  useEffect(() => { savePrefs(layers); }, [layers]);

  const handleToggle = useCallback((key) => {
    setLayers((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);
  const handleSetAll = useCallback((v) => {
    setLayers(() => Object.fromEntries(Object.keys(DEFAULT_LAYERS).map((k) => [k, !!v])));
  }, []);

  /* ── Mapbox + deck.gl overlay ────────────────────────────────────────── */
  useEffect(() => {
    if (!hasToken || !hasCoords || !containerRef.current || mapRef.current) return;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/light-v11",
      center: [lon, lat],
      zoom: 14.2,
      pitch: 0,
      attributionControl: false,
    });
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "bottom-right");
    map.addControl(new mapboxgl.AttributionControl({ compact: true }), "bottom-left");

    const overlay = new MapboxOverlay({ layers: [] });
    map.addControl(overlay);

    mapRef.current = map;
    overlayRef.current = overlay;
    map.on("load", () => setMapReady(true));

    return () => {
      try { map.remove(); } catch { /* noop */ }
      mapRef.current = null;
      overlayRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasToken, hasCoords]);

  useEffect(() => {
    if (!mapRef.current || !hasCoords) return;
    mapRef.current.flyTo({ center: [lon, lat], zoom: 14.2, duration: 600 });
  }, [lat, lon, hasCoords]);

  /* ── Data feeds ──────────────────────────────────────────────────────── */
  useEffect(() => {
    if (!hasCoords) return;
    let cancelled = false;
    (async () => {
      const result = await fetchTwinFeeds({
        pid, lat, lon,
        sitePolygon: project?.metadata?.site_polygon,
      });
      if (cancelled) return;
      const { statuses: st, ...rest } = result;
      setFeeds(rest);
      setStatuses(st);
    })();
    return () => { cancelled = true; };
  }, [pid, lat, lon, hasCoords, project?.metadata?.site_polygon]);

  /* ── deck.gl layers ──────────────────────────────────────────────────── */
  const deckLayers = useMemo(() => {
    if (!hasCoords) return [];
    const { boundary, substation, designations, flood, landuse, queue } = feeds;
    const out = [];

    if (layers.boundary && boundary) {
      out.push(new GeoJsonLayer({
        id: "site-boundary",
        data: boundary,
        stroked: true, filled: true,
        getFillColor: [201, 166, 75, 40],
        getLineColor: [201, 166, 75, 230],
        lineWidthMinPixels: 2.5,
        pickable: true,
        onClick: () => onOpenParcel?.(pid),
      }));
    }

    if (layers.designations && designations) {
      out.push(new GeoJsonLayer({
        id: "designations",
        data: designations,
        stroked: true, filled: true,
        getFillColor: [200, 80, 80, 60],
        getLineColor: [180, 50, 50, 200],
        lineWidthMinPixels: 1,
        pickable: true,
        onHover: (info) => {
          if (!info.object) { setTooltip(null); return; }
          const p = info.object.properties || {};
          const name = p.name || p.designation || p.type || "Designation";
          const typ = p.type || p.category || "";
          const dist = p.distance_m != null ? `${Math.round(p.distance_m)} m` : "";
          setTooltip({
            x: info.x, y: info.y,
            text: `${name}${typ ? " · " + typ : ""}${dist ? " · " + dist : ""}`,
          });
        },
      }));
    }

    if (layers.flood && flood) {
      out.push(new GeoJsonLayer({
        id: "flood",
        data: flood,
        stroked: true, filled: true,
        getFillColor: [60, 120, 220, 70],
        getLineColor: [40, 90, 180, 200],
        lineWidthMinPixels: 1,
        pickable: true,
      }));
    }

    if (layers.landuse && landuse) {
      out.push(new GeoJsonLayer({
        id: "landuse",
        data: landuse,
        stroked: false, filled: true,
        getFillColor: (f) => f?.properties?.color || [140, 170, 90, 90],
        pickable: false,
      }));
    }

    if (layers.substation && substation) {
      const sPt = [substation._lon, substation._lat];
      const siPt = [lon, lat];
      out.push(new ArcLayer({
        id: "sub-arc",
        data: [{ from: siPt, to: sPt }],
        getSourcePosition: (d) => d.from,
        getTargetPosition: (d) => d.to,
        getSourceColor: [201, 166, 75, 220],
        getTargetColor: [40, 120, 220, 220],
        getWidth: 2,
      }));
      out.push(new ScatterplotLayer({
        id: "sub-marker",
        data: [substation],
        getPosition: (d) => [d._lon, d._lat],
        getRadius: 80,
        radiusMinPixels: 8,
        radiusMaxPixels: 16,
        getFillColor: [40, 120, 220, 230],
        getLineColor: [255, 255, 255, 255],
        lineWidthMinPixels: 2,
        stroked: true,
        pickable: true,
        onClick: () => onOpenSubstation?.(substation),
      }));
    }

    if (layers.queue && Array.isArray(queue) && queue.length) {
      const points = queue.map((q) => ({
        position: [
          q.lon ?? q.longitude ?? q.geometry?.coordinates?.[0],
          q.lat ?? q.latitude ?? q.geometry?.coordinates?.[1],
        ],
        mw: q.capacity_mw ?? q.mw ?? 10,
        raw: q,
      })).filter((d) => d.position[0] != null && d.position[1] != null);
      if (points.length) {
        out.push(new ScatterplotLayer({
          id: "queue",
          data: points,
          getPosition: (d) => d.position,
          getRadius: (d) => Math.max(30, Math.sqrt(d.mw || 10) * 15),
          radiusMinPixels: 3,
          radiusMaxPixels: 10,
          getFillColor: [180, 140, 60, 170],
          stroked: false,
          pickable: true,
          onHover: (info) => {
            if (!info.object) { setTooltip(null); return; }
            const r = info.object.raw || {};
            setTooltip({
              x: info.x, y: info.y,
              text: `${r.name || r.project_name || "Queued project"} · ${Math.round(info.object.mw)} MW`,
            });
          },
        }));
      }
    }

    return out;
  }, [layers, feeds, lat, lon, hasCoords, pid, onOpenParcel, onOpenSubstation]);

  useEffect(() => {
    if (!overlayRef.current) return;
    overlayRef.current.setProps({ layers: deckLayers });
  }, [deckLayers]);

  /* ── Render ──────────────────────────────────────────────────────────── */

  if (!hasCoords) {
    return <EmptyState title="No project coordinates yet"
                       sub="Select a site or pick a location from the overview to see the twin." />;
  }
  if (!hasToken) {
    return <EmptyState title="Mapbox token missing"
                       sub="Set VITE_MAPBOX_TOKEN to render the project twin." />;
  }

  return (
    <div className="pte-root">
      <div ref={containerRef} className="pte-map" />
      <TwinOverlayToggles
        layers={layers}
        onToggle={handleToggle}
        onSetAll={handleSetAll}
        statuses={statuses}
      />
      <AgenticKPIRail project={project} />
      {tooltip && (
        <div className="pte-tooltip" style={{ left: tooltip.x + 10, top: tooltip.y + 10 }}>
          {tooltip.text}
        </div>
      )}

      <style>{`
        .pte-root { position: absolute; inset: 0; overflow: hidden; border-radius: 12px; }
        .pte-map { position: absolute; inset: 0; }
        .pte-tooltip {
          position: absolute; pointer-events: none; z-index: 10;
          background: rgba(18, 20, 24, 0.92);
          color: #F5E9C8;
          border: 1px solid rgba(201, 166, 75, 0.4);
          border-radius: 4px;
          padding: 4px 8px;
          font-family: "JetBrains Mono", ui-monospace, Menlo, monospace;
          font-size: 11px;
          max-width: 280px;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
      `}</style>
    </div>
  );
}

function EmptyState({ title, sub }) {
  return (
    <div className="pte-empty">
      <div>
        <div className="pte-empty-title">{title}</div>
        <div className="pte-empty-sub">{sub}</div>
      </div>
      <style>{`
        .pte-empty {
          position: absolute; inset: 0;
          display: flex; align-items: center; justify-content: center;
          background: linear-gradient(135deg, #1A1D23 0%, #0F1318 100%);
          color: rgba(255,255,255,0.7);
          text-align: center;
          border-radius: 12px;
        }
        .pte-empty-title { font-size: 14px; font-weight: 600; color: #F5E9C8; }
        .pte-empty-sub { font-size: 11px; color: rgba(255,255,255,0.45); margin-top: 6px; }
      `}</style>
    </div>
  );
}
