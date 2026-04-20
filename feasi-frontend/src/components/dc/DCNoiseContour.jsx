/**
 * DCNoiseContour — ISO 9613-2 ring contours around the genset yard + chiller plant.
 *
 * The backend helper `utils/noise_propagation.py` generates contour polygons; we
 * keep the shape simple (circles) on the client since the dominant sources are
 * two point emitters and the terrain is flat enough at these scales to treat
 * the contours as radially symmetric at 55 dB / 65 dB thresholds.
 *
 * 55 dB = amber ring (planning-advisory), 65 dB = red ring (likely exceedance).
 * If any provided receptor sits inside an amber or red ring, a flag marker
 * renders on the receptor and its dB level appears in a small pop.
 */
import React, { useEffect, useState } from "react";
import { PolygonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { fetchNoiseContours } from "../../api/dcOps";

const M_PER_DEG_LAT = 111_320;
function mPerDegLon(lat) { return M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180); }

function circlePolygon(lat, lon, radiusM, n = 64) {
  const ring = [];
  for (let i = 0; i < n; i++) {
    const th = (i / n) * 2 * Math.PI;
    const dx = Math.cos(th) * radiusM;
    const dy = Math.sin(th) * radiusM;
    ring.push([lon + dx / mPerDegLon(lat), lat + dy / M_PER_DEG_LAT]);
  }
  ring.push(ring[0]);
  return ring;
}

export function useNoiseContours({ lat, lon, itLoadMw, genLat, genLon, chillLat, chillLon, receptors = [], enabled = true }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    fetchNoiseContours({ lat, lon, itLoadMw, genLat, genLon, chillLat, chillLon, receptors })
      .then(d => { if (!cancelled) setData(d); });
    return () => { cancelled = true; };
    // Debounce receptor list by stringifying once — cheap for <20 receptors.
  }, [enabled, lat, lon, itLoadMw, genLat, genLon, chillLat, chillLon, JSON.stringify(receptors)]);
  return data;
}

export function noiseContourLayers({ data, visible = true }) {
  if (!visible || !data?.emitters) return [];
  const ringPolys = [];
  data.emitters.forEach(e => {
    // Draw outermost (lowest-dB) ring first so the inner red circle paints on top.
    (e.rings || []).slice().sort((a, b) => b.radius_m - a.radius_m).forEach(r => {
      ringPolys.push({
        polygon: circlePolygon(e.lat, e.lon, r.radius_m),
        color: r.color,
        db: r.db,
        label: e.label,
      });
    });
  });

  const layers = [
    new PolygonLayer({
      id: "dc-noise-rings",
      data: ringPolys,
      getPolygon: d => d.polygon,
      getFillColor: d => [d.color[0], d.color[1], d.color[2], 35],
      getLineColor: d => d.color,
      lineWidthMinPixels: 2,
      stroked: true,
      filled: true,
      extruded: false,
    }),
    new ScatterplotLayer({
      id: "dc-noise-emitters",
      data: data.emitters,
      getPosition: d => [d.lon, d.lat],
      getFillColor: [15, 23, 42, 240],
      getLineColor: [245, 183, 49, 255],
      stroked: true,
      lineWidthMinPixels: 2,
      radiusUnits: "pixels",
      getRadius: 8,
      pickable: true,
    }),
    new TextLayer({
      id: "dc-noise-emitter-labels",
      data: data.emitters,
      getPosition: d => [d.lon, d.lat],
      getText: d => `${d.label} · ${d.source_db} dB`,
      getSize: 10,
      getColor: [255, 255, 255, 240],
      getPixelOffset: [0, -14],
      background: true,
      getBackgroundColor: [15, 23, 42, 220],
      backgroundPadding: [4, 2],
      fontFamily: '"DM Sans", sans-serif',
      fontWeight: 700,
    }),
  ];

  // Receptor flags — mark any breaching receptor red.
  if (data.receptor_flags && data.receptor_flags.length > 0) {
    layers.push(new ScatterplotLayer({
      id: "dc-noise-receptors",
      data: data.receptor_flags,
      getPosition: d => [d.lon, d.lat],
      getFillColor: d => d.exceeds ? [239, 68, 68, 255] : [148, 163, 184, 200],
      getLineColor: [255, 255, 255, 255],
      stroked: true,
      lineWidthMinPixels: 1.5,
      radiusUnits: "pixels",
      getRadius: d => d.exceeds ? 7 : 5,
      pickable: true,
    }));
    layers.push(new TextLayer({
      id: "dc-noise-receptor-labels",
      data: data.receptor_flags.filter(r => r.exceeds),
      getPosition: d => [d.lon, d.lat],
      getText: d => `${d.label || "Receptor"}: ${d.db_at_receptor} dB ⚠`,
      getSize: 10,
      getColor: [255, 220, 220, 240],
      getPixelOffset: [0, 16],
      background: true,
      getBackgroundColor: [127, 29, 29, 220],
      backgroundPadding: [4, 2],
      fontFamily: '"DM Sans", sans-serif',
      fontWeight: 700,
    }));
  }

  return layers;
}

export default function DCNoiseContour() { return null; }
