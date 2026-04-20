/**
 * dyn_weather — ERA5 weather overlay. Two modes controlled by
 * ctx.variable ("ghi" | "wind"):
 *   - irradiance W/m²
 *   - wind speed m/s @10 m
 *
 * Data from /api/twin/weather/grid. Rendered as a flat grid of
 * ColumnLayer hex cells (avoids a new deck.gl package). Cell colour =
 * magnitude, cell alpha = confidence-ish proxy.
 *
 * Time-aware. Cadence 1 req / 30 s max (ERA5 is hourly resolution).
 *
 * Data model (ctx.data):
 *   { var: "ghi"|"wind", ts, bbox, cell_dx, cell_dy,
 *     points: [{lon, lat, value}] }
 *
 * Registry contract: docs/audits/twin_layer_registry_contract.md.
 */

import { PolygonLayer } from "@deck.gl/layers";

// Ramp helpers – 6-stop gradients.
const GHI_STOPS = [
  [10,  15,  40,  90],   // 0
  [30,  50,  120, 150],  // 150 W/m²
  [80,  140, 200, 175],  // 300
  [210, 210, 140, 200],  // 500
  [240, 180, 60,  215],  // 700
  [240, 110, 40,  230],  // >900
];
const WIND_STOPS = [
  [20,  40,  70,  90],
  [40,  100, 160, 150],
  [80,  170, 220, 175],
  [150, 220, 200, 200],
  [230, 200, 90,  220],
  [230, 80,  80,  240],
];

function rampFor(variable, value) {
  const stops = variable === "wind" ? WIND_STOPS : GHI_STOPS;
  const max = variable === "wind" ? 20 : 900;
  const t = Math.max(0, Math.min(1, (Number(value) || 0) / max));
  const idx = t * (stops.length - 1);
  const i = Math.floor(idx);
  const f = idx - i;
  const a = stops[i];
  const b = stops[Math.min(i + 1, stops.length - 1)];
  return [
    Math.round(a[0] + (b[0] - a[0]) * f),
    Math.round(a[1] + (b[1] - a[1]) * f),
    Math.round(a[2] + (b[2] - a[2]) * f),
    Math.round(a[3] + (b[3] - a[3]) * f),
  ];
}

function cellPolygon(lon, lat, dx, dy) {
  const hx = dx / 2;
  const hy = dy / 2;
  return [
    [lon - hx, lat - hy],
    [lon + hx, lat - hy],
    [lon + hx, lat + hy],
    [lon - hx, lat + hy],
    [lon - hx, lat - hy],
  ];
}

function makeDynWeatherLayer(ctx = {}) {
  const {
    visible = true,
    data = null,
    variable = "ghi",
    opacity = 0.6,
    onHover,
  } = ctx;

  if (!data || !Array.isArray(data.points) || data.points.length === 0) {
    return new PolygonLayer({
      id: "dyn_weather_empty",
      data: [],
      visible: false,
      getPolygon: (d) => d.polygon,
    });
  }

  const variableId = data.var || variable;
  const dx = Number(data.cell_dx) || 0.5;
  const dy = Number(data.cell_dy) || 0.5;

  const rows = data.points.map((p) => ({
    lon: p.lon, lat: p.lat, value: p.value,
    polygon: cellPolygon(p.lon, p.lat, dx, dy),
  }));

  return new PolygonLayer({
    id: `dyn_weather_${variableId}`,
    data: rows,
    visible,
    pickable: Boolean(onHover),
    filled: true,
    stroked: false,
    extruded: false,
    opacity,
    getPolygon: (d) => d.polygon,
    getFillColor: (d) => rampFor(variableId, d.value),
    onHover,
    parameters: { depthTest: false },
    updateTriggers: {
      getFillColor: [variableId, data.ts],
    },
  });
}

export default {
  id: "dyn_weather",
  menuLabel: "Weather (ERA5)",
  defaultVisible: false,
  category: "dynamic",
  attribution: "ERA5 (Copernicus Climate Change Service) · synthesised when no CDS key",
  licence: "Copernicus licence (non-commercial free)",
  timeAware: true,
  layerFactory: makeDynWeatherLayer,
  dataHook: null,
};
