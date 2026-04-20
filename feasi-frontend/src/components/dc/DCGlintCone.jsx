/**
 * DCGlintCone — solar-noon glint/glare reflection cones from reflective
 * cooling-plant surfaces (dry coolers' finned panels, chiller enclosure
 * cladding) at summer and winter solstice geometry.
 *
 * Why both solstices: the reflected beam sweeps a large elevation range
 * across the year, and the *worst* receptor hit is usually at winter
 * noon (low sun → long reflected projection across the horizon).
 *
 * Summer cone renders narrow + high-altitude (yellow), winter cone is
 * wider + longer (amber). Receptor hits render a red exclamation pin.
 */
import React, { useEffect, useState } from "react";
import { PolygonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { fetchGlintCones } from "../../api/dcOps";

const M_PER_DEG_LAT = 111_320;
function mPerDegLon(lat) { return M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180); }

function conePolygon(lat, lon, bearingDeg, spreadDeg, lengthM, segs = 8) {
  const ring = [[lon, lat]];
  const bearRad = (bearingDeg * Math.PI) / 180;
  const halfSpread = (spreadDeg * Math.PI) / 180;
  for (let i = 0; i <= segs; i++) {
    const off = -halfSpread + (2 * halfSpread * i) / segs;
    const dir = bearRad + off;
    // bearing 0 = north (+y), east = +x
    const dx = Math.sin(dir) * lengthM;
    const dy = Math.cos(dir) * lengthM;
    ring.push([lon + dx / mPerDegLon(lat), lat + dy / M_PER_DEG_LAT]);
  }
  ring.push([lon, lat]);
  return ring;
}

export function useGlintCones({ lat, lon, coolingLat, coolingLon, receptors = [], enabled = true }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    fetchGlintCones({ lat, lon, coolingLat, coolingLon, receptors })
      .then(d => { if (!cancelled) setData(d); });
    return () => { cancelled = true; };
  }, [enabled, lat, lon, coolingLat, coolingLon, JSON.stringify(receptors)]);
  return data;
}

export function glintConeLayers({ data, visible = true }) {
  if (!visible || !data?.cones) return [];
  const summerCol = [253, 224, 71, 70];         // soft yellow fill
  const summerEdge = [253, 224, 71, 220];
  const winterCol = [251, 146, 60, 90];         // amber fill (longer + wider)
  const winterEdge = [251, 146, 60, 230];

  const polys = data.cones.map(c => ({
    polygon: conePolygon(c.lat, c.lon, c.bearing_deg, c.spread_deg, c.length_m),
    season: c.season,
    surface: c.surface,
    sun_alt_deg: c.sun_alt_deg,
    length_m: c.length_m,
  }));

  const layers = [
    new PolygonLayer({
      id: "dc-glint-cones",
      data: polys,
      getPolygon: d => d.polygon,
      getFillColor: d => d.season === "winter" ? winterCol : summerCol,
      getLineColor: d => d.season === "winter" ? winterEdge : summerEdge,
      lineWidthMinPixels: 1.5,
      stroked: true,
      filled: true,
      extruded: false,
    }),
    new TextLayer({
      id: "dc-glint-legend",
      data: data.surfaces,
      getPosition: d => [d.lon, d.lat],
      getText: d => `Glint source · ${d.label}`,
      getSize: 10,
      getColor: [255, 255, 255, 240],
      getPixelOffset: [0, -24],
      background: true,
      getBackgroundColor: [217, 119, 6, 220],
      backgroundPadding: [4, 2],
      fontFamily: '"DM Sans", sans-serif',
      fontWeight: 700,
    }),
  ];

  if (data.receptor_hits && data.receptor_hits.length > 0) {
    layers.push(new ScatterplotLayer({
      id: "dc-glint-receptor-hits",
      data: data.receptor_hits,
      getPosition: d => [d.lon, d.lat],
      getFillColor: [239, 68, 68, 255],
      getLineColor: [255, 255, 255, 255],
      stroked: true,
      lineWidthMinPixels: 1.5,
      radiusUnits: "pixels",
      getRadius: 8,
      pickable: true,
    }));
    layers.push(new TextLayer({
      id: "dc-glint-receptor-labels",
      data: data.receptor_hits,
      getPosition: d => [d.lon, d.lat],
      getText: d => `${d.label || "Receptor"} · ${d.season} glint @ ${d.bearing_deg}° ⚠`,
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

export default function DCGlintCone() { return null; }
