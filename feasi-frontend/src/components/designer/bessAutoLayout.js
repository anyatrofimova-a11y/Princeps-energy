/**
 * BESS Auto-Layout Engine
 * Generates optimal site layout from MW target + duration.
 * NFCC 2025 fire safety spacing, UK grid connection costs.
 */

export const BESS_CATALOG = {
  battery_container_20ft: { w: 6.1, h: 2.4, depth: 2.9, capacity_mwh: 1.0, label: "Battery Container" },
  battery_container_40ft: { w: 12.2, h: 2.4, depth: 2.9, capacity_mwh: 3.5, label: "Battery Container (40ft)" },
  pcs_inverter: { w: 6.1, h: 2.4, depth: 2.9, mw_rating: 2.5, label: "PCS / Inverter" },
  transformer_mv: { w: 2.5, h: 2.0, depth: 2.5, label: "MV Transformer" },
  transformer_hv: { w: 6.0, h: 4.0, depth: 4.5, label: "HV Transformer" },
  switchgear: { w: 6.1, h: 2.4, depth: 2.9, label: "MV/HV Switchgear" },
  control_room: { w: 6.1, h: 2.4, depth: 2.9, label: "Control Room" },
  fire_water_tank: { w: 5.0, h: 3.0, depth: 3.0, label: "Fire Water Tank" },
  fire_pump: { w: 4.0, h: 3.0, depth: 2.5, label: "Fire Pump House" },
  aux_transformer: { w: 1.5, h: 1.0, depth: 1.5, label: "Auxiliary Transformer" },
  lightning_mast: { w: 0.5, h: 0.5, depth: 12, label: "Lightning Mast" },
  perimeter_fence: { w: 0, h: 0, depth: 2.1, label: "Perimeter Fence" },
};

const SETBACK = 25; // NFCC boundary setback (m)
const ROAD_WIDTH = 3.7; // fire access road (m)
const CONTAINER_GAP = 6; // NFCC inter-container (m)
const ROW_GAP = 10; // between rows (m)
const CONTAINERS_PER_ROW = 8;
const PCS_PER_CONTAINERS = 4;
const MV_TRANSFORMER_PER_MW = 10;

let _nextId = 0;
function uid(prefix) { return `${prefix}-${++_nextId}`; }

export function generateBESSLayout(mwTarget, durationHours = 2) {
  _nextId = 0;
  const objects = [];
  const mwh = mwTarget * durationHours;

  // Pick container type
  const useType = mwTarget >= 50 ? "battery_container_40ft" : "battery_container_20ft";
  const spec = BESS_CATALOG[useType];
  const containerCount = Math.ceil(mwh / spec.capacity_mwh);
  const rowCount = Math.ceil(containerCount / CONTAINERS_PER_ROW);

  // Origin offset (setback + road)
  const ox = SETBACK + ROAD_WIDTH + 5;
  const oy = SETBACK + ROAD_WIDTH + 5;

  // Place battery containers in rows
  for (let row = 0; row < rowCount; row++) {
    const inThisRow = Math.min(CONTAINERS_PER_ROW, containerCount - row * CONTAINERS_PER_ROW);
    for (let col = 0; col < inThisRow; col++) {
      objects.push({
        id: uid("bat"),
        type: useType,
        x: ox + col * (spec.w + CONTAINER_GAP),
        y: oy + row * (spec.h + ROW_GAP),
        w: spec.w,
        h: spec.h,
        rotation: 0,
        category: "infrastructure",
        properties: { capacity_mwh: spec.capacity_mwh, row: row + 1, position: col + 1 },
      });
    }
  }

  // PCS inverters — 1 per PCS_PER_CONTAINERS containers, at end of rows
  const pcsCount = Math.ceil(containerCount / PCS_PER_CONTAINERS);
  const pcsSpec = BESS_CATALOG.pcs_inverter;
  const batteryBlockWidth = CONTAINERS_PER_ROW * (spec.w + CONTAINER_GAP);
  for (let i = 0; i < pcsCount; i++) {
    const row = Math.floor(i / 2);
    const side = i % 2;
    objects.push({
      id: uid("pcs"),
      type: "pcs_inverter",
      x: ox + batteryBlockWidth + 8 + side * (pcsSpec.w + 4),
      y: oy + row * (spec.h + ROW_GAP),
      w: pcsSpec.w,
      h: pcsSpec.h,
      rotation: 0,
      category: "electrical",
      properties: { mw_rating: pcsSpec.mw_rating },
    });
  }

  // Transformers
  const mvCount = Math.ceil(mwTarget / MV_TRANSFORMER_PER_MW);
  const txY = oy + rowCount * (spec.h + ROW_GAP) + 15;
  for (let i = 0; i < mvCount; i++) {
    const txSpec = BESS_CATALOG.transformer_mv;
    objects.push({
      id: uid("tx-mv"),
      type: "transformer_mv",
      x: ox + i * (txSpec.w + 8),
      y: txY,
      w: txSpec.w,
      h: txSpec.h,
      rotation: 0,
      category: "electrical",
      properties: {},
    });
  }
  if (mwTarget > 50) {
    const hvSpec = BESS_CATALOG.transformer_hv;
    objects.push({
      id: uid("tx-hv"),
      type: "transformer_hv",
      x: ox + mvCount * (BESS_CATALOG.transformer_mv.w + 8) + 10,
      y: txY,
      w: hvSpec.w,
      h: hvSpec.h,
      rotation: 0,
      category: "electrical",
      properties: {},
    });
  }

  // Switchgear
  const sgSpec = BESS_CATALOG.switchgear;
  objects.push({
    id: uid("sg"),
    type: "switchgear",
    x: ox,
    y: txY + 12,
    w: sgSpec.w,
    h: sgSpec.h,
    rotation: 0,
    category: "electrical",
    properties: {},
  });

  // Control room — near entrance (bottom-left)
  const crSpec = BESS_CATALOG.control_room;
  objects.push({
    id: uid("ctrl"),
    type: "control_room",
    x: SETBACK + ROAD_WIDTH + 2,
    y: txY + 25,
    w: crSpec.w,
    h: crSpec.h,
    rotation: 0,
    category: "infrastructure",
    properties: {},
  });

  // Fire water tank — centre of battery area
  const fwSpec = BESS_CATALOG.fire_water_tank;
  const centreX = ox + (batteryBlockWidth / 2) - fwSpec.w / 2;
  const centreY = oy + ((rowCount * (spec.h + ROW_GAP)) / 2);
  objects.push({
    id: uid("fw"),
    type: "fire_water_tank",
    x: centreX + batteryBlockWidth + 30,
    y: centreY,
    w: fwSpec.w,
    h: fwSpec.h,
    rotation: 0,
    category: "safety",
    properties: { volume_litres: 228000 },
  });

  // Fire pump
  const fpSpec = BESS_CATALOG.fire_pump;
  objects.push({
    id: uid("fp"),
    type: "fire_pump",
    x: centreX + batteryBlockWidth + 30,
    y: centreY + fwSpec.h + 4,
    w: fpSpec.w,
    h: fpSpec.h,
    rotation: 0,
    category: "safety",
    properties: {},
  });

  // Aux transformer
  const auxSpec = BESS_CATALOG.aux_transformer;
  objects.push({
    id: uid("aux"),
    type: "aux_transformer",
    x: SETBACK + ROAD_WIDTH + 2 + crSpec.w + 4,
    y: txY + 25,
    w: auxSpec.w,
    h: auxSpec.h,
    rotation: 0,
    category: "electrical",
    properties: {},
  });

  // Calculate metrics
  const metrics = calculateBESSMetrics(objects, mwTarget, durationHours);

  // Access roads (simplified perimeter)
  const maxX = Math.max(...objects.map(o => o.x + o.w)) + 10;
  const maxY = Math.max(...objects.map(o => o.y + o.h)) + 10;
  const accessRoads = [
    { points: [
      { x: SETBACK, y: SETBACK },
      { x: maxX + SETBACK, y: SETBACK },
      { x: maxX + SETBACK, y: maxY + SETBACK },
      { x: SETBACK, y: maxY + SETBACK },
      { x: SETBACK, y: SETBACK },
    ], width: ROAD_WIDTH },
  ];

  return {
    objects,
    metrics,
    accessRoads,
    setbackZone: { margin: SETBACK },
    siteExtent: { width: maxX + 2 * SETBACK, height: maxY + 2 * SETBACK },
  };
}

export function calculateBESSMetrics(objects, mwTarget, durationHours = 2) {
  const containers = objects.filter(o => o.type.startsWith("battery_container"));
  const pcs = objects.filter(o => o.type === "pcs_inverter");
  const totalMwh = containers.reduce((s, o) => s + (o.properties?.capacity_mwh || 0), 0);
  const totalMw = mwTarget || totalMwh / (durationHours || 2);

  const capex = containers.length * 150000 + pcs.length * 80000 + 200000 * objects.filter(o => o.type.startsWith("transformer")).length + 100000;
  const voltage = totalMw < 5 ? "11kV" : totalMw < 50 ? "33kV" : "132kV";
  const costPerKm = voltage === "11kV" ? 80000 : voltage === "33kV" ? 150000 : 500000;
  const gridCost = costPerKm * 2; // assume 2km average
  const timeline = voltage === "11kV" ? 12 : voltage === "33kV" ? 24 : 36;

  const maxX = Math.max(...objects.map(o => o.x + o.w), 0);
  const maxY = Math.max(...objects.map(o => o.y + o.h), 0);
  const siteArea = (maxX + 50) * (maxY + 50);
  const footprint = objects.reduce((s, o) => s + o.w * o.h, 0);

  // Revenue (Modo benchmark)
  const durationMult = durationHours >= 4 ? 1.15 : durationHours >= 2 ? 1.0 : 0.85;
  const revenuePerMw = Math.round(72000 * durationMult);

  return {
    total_mw: Math.round(totalMw * 10) / 10,
    total_mwh: Math.round(totalMwh * 10) / 10,
    duration_hours: durationHours,
    container_count: containers.length,
    pcs_count: pcs.length,
    site_area_m2: Math.round(siteArea),
    site_area_ha: Math.round(siteArea / 10000 * 10) / 10,
    footprint_m2: Math.round(footprint),
    estimated_capex_gbp: capex,
    estimated_revenue_gbp_per_mw_yr: revenuePerMw,
    irr_pct: 10.2,
    payback_years: Math.round(capex / (totalMw * revenuePerMw) * 10) / 10,
    grid_connection_voltage: voltage,
    grid_connection_cost_gbp: gridCost,
    grid_connection_timeline_months: timeline,
  };
}
