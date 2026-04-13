/**
 * Data Centre Auto-Layout Engine
 * Generates campus layout from IT load MW + Uptime Tier.
 * EN 50600, Uptime Institute tier requirements.
 */

export const DC_CATALOG = {
  server_hall_standard: { w: 50, h: 25, depth: 6, it_load_mw: 4, label: "Server Hall" },
  server_hall_large: { w: 80, h: 30, depth: 6, it_load_mw: 8, label: "Server Hall (Large)" },
  server_hall_hyperscale: { w: 100, h: 50, depth: 6, it_load_mw: 16, label: "Server Hall (Hyperscale)" },
  primary_substation: { w: 60, h: 40, depth: 4, label: "Primary Substation" },
  transformer_compound: { w: 8, h: 5, depth: 5, mva: 30, label: "Transformer (30MVA)" },
  mv_switchgear: { w: 20, h: 8, depth: 4, label: "MV Switchgear" },
  generator: { w: 15, h: 4, depth: 3.5, mw_rating: 2.5, label: "Generator (2.5MW)" },
  fuel_storage: { w: 12, h: 3, depth: 3, litres: 100000, label: "Fuel Storage (100kL)" },
  ups_building: { w: 10, h: 6, depth: 3, label: "UPS / Battery" },
  cooling_plant: { w: 30, h: 20, depth: 4, mw_cooling: 5, label: "Cooling Plant" },
  water_treatment: { w: 8, h: 5, depth: 3, label: "Water Treatment" },
  office_noc: { w: 20, h: 15, depth: 4, label: "Office / NOC" },
  loading_dock: { w: 15, h: 30, depth: 5, label: "Loading Dock" },
  gatehouse: { w: 6, h: 4, depth: 3, label: "Security Gatehouse" },
  car_park: { w: 40, h: 25, depth: 0, label: "Car Park" },
  fire_pump: { w: 10, h: 6, depth: 3, label: "Fire Pump Room" },
  suds_tank: { w: 20, h: 10, depth: 3, label: "SuDS Attenuation" },
};

const SETBACK = 10;
const ROAD_WIDTH = 5.5;
const HALL_GAP = 15; // cooling corridors
const TIER_PUE = { 1: 1.5, 2: 1.4, 3: 1.3, 4: 1.25 };
const TIER_REDUNDANCY = { 1: "N", 2: "N+1", 3: "N+1", 4: "2N" };
const TIER_FUEL_HOURS = { 1: 12, 2: 24, 3: 48, 4: 72 };

let _nextId = 0;
function uid(prefix) { return `${prefix}-${++_nextId}`; }

export function generateDCLayout(itLoadMw, tier = 3) {
  _nextId = 0;
  const objects = [];
  const pue = TIER_PUE[tier] || 1.3;
  const totalMw = itLoadMw * pue;
  const redundancy = TIER_REDUNDANCY[tier] || "N+1";
  const fuelHours = TIER_FUEL_HOURS[tier] || 48;

  // Pick hall type
  let hallType, hallSpec;
  if (itLoadMw > 60) { hallType = "server_hall_hyperscale"; hallSpec = DC_CATALOG.server_hall_hyperscale; }
  else if (itLoadMw > 30) { hallType = "server_hall_large"; hallSpec = DC_CATALOG.server_hall_large; }
  else { hallType = "server_hall_standard"; hallSpec = DC_CATALOG.server_hall_standard; }

  const hallCount = Math.ceil(itLoadMw / hallSpec.it_load_mw);

  const ox = SETBACK + ROAD_WIDTH + 80; // leave room for substation on left
  const oy = SETBACK + ROAD_WIDTH + 20;

  // Place server halls in parallel rows
  const hallsPerColumn = Math.ceil(hallCount / 2);
  for (let i = 0; i < hallCount; i++) {
    const col = Math.floor(i / hallsPerColumn);
    const row = i % hallsPerColumn;
    objects.push({
      id: uid("hall"),
      type: hallType,
      x: ox + col * (hallSpec.w + HALL_GAP + 40), // gap for cooling
      y: oy + row * (hallSpec.h + HALL_GAP),
      w: hallSpec.w,
      h: hallSpec.h,
      rotation: 0,
      category: "infrastructure",
      properties: { it_load_mw: hallSpec.it_load_mw, hall_number: i + 1 },
    });
  }

  // Primary substation — left side
  const subSpec = DC_CATALOG.primary_substation;
  const subW = totalMw > 100 ? 80 : 60;
  const subH = totalMw > 100 ? 60 : 40;
  objects.push({
    id: uid("sub"),
    type: "primary_substation",
    x: SETBACK + ROAD_WIDTH,
    y: oy,
    w: subW,
    h: subH,
    rotation: 0,
    category: "electrical",
    properties: { capacity_mva: Math.round(totalMw * 1.1) },
  });

  // Transformers
  const txCount = Math.ceil(totalMw / 30) + (redundancy === "2N" ? Math.ceil(totalMw / 30) : 1);
  const txSpec = DC_CATALOG.transformer_compound;
  for (let i = 0; i < Math.min(txCount, 8); i++) {
    objects.push({
      id: uid("tx"),
      type: "transformer_compound",
      x: SETBACK + ROAD_WIDTH + subW + 8 + (i % 4) * (txSpec.w + 6),
      y: oy + subH + 10 + Math.floor(i / 4) * (txSpec.h + 8),
      w: txSpec.w,
      h: txSpec.h,
      rotation: 0,
      category: "electrical",
      properties: { mva: txSpec.mva },
    });
  }

  // MV Switchgear
  const sgSpec = DC_CATALOG.mv_switchgear;
  const sgCount = Math.ceil(hallCount / 2);
  for (let i = 0; i < sgCount; i++) {
    objects.push({
      id: uid("sg"),
      type: "mv_switchgear",
      x: SETBACK + ROAD_WIDTH + subW + 8,
      y: oy + subH + 10 + Math.ceil(txCount / 4) * (txSpec.h + 8) + 10 + i * (sgSpec.h + 6),
      w: sgSpec.w,
      h: sgSpec.h,
      rotation: 0,
      category: "electrical",
      properties: {},
    });
  }

  // Generators — behind halls
  const genBase = redundancy === "2N" ? Math.ceil(totalMw / 2.5) * 2 : Math.ceil(totalMw / 2.5) + 1;
  const genCount = Math.min(genBase, 80);
  const genSpec = DC_CATALOG.generator;
  const hallBlockMaxY = oy + hallsPerColumn * (hallSpec.h + HALL_GAP);
  const genStartY = hallBlockMaxY + 20;
  const gensPerRow = 10;
  for (let i = 0; i < genCount; i++) {
    const col = i % gensPerRow;
    const row = Math.floor(i / gensPerRow);
    objects.push({
      id: uid("gen"),
      type: "generator",
      x: ox + col * (genSpec.w + 4),
      y: genStartY + row * (genSpec.h + 6),
      w: genSpec.w,
      h: genSpec.h,
      rotation: 0,
      category: "infrastructure",
      properties: { mw_rating: genSpec.mw_rating },
    });
  }

  // Fuel storage
  const fuelLitres = totalMw * 250 * fuelHours;
  const tankCount = Math.ceil(fuelLitres / 100000);
  const fuelSpec = DC_CATALOG.fuel_storage;
  const genRows = Math.ceil(genCount / gensPerRow);
  const fuelY = genStartY + genRows * (genSpec.h + 6) + 20;
  for (let i = 0; i < Math.min(tankCount, 10); i++) {
    objects.push({
      id: uid("fuel"),
      type: "fuel_storage",
      x: ox + i * (fuelSpec.w + 6),
      y: fuelY,
      w: fuelSpec.w,
      h: fuelSpec.h,
      rotation: 0,
      category: "infrastructure",
      properties: { litres: fuelSpec.litres },
    });
  }

  // UPS — one per hall, adjacent
  const upsSpec = DC_CATALOG.ups_building;
  for (let i = 0; i < hallCount; i++) {
    const hall = objects.find(o => o.properties?.hall_number === i + 1);
    if (hall) {
      objects.push({
        id: uid("ups"),
        type: "ups_building",
        x: hall.x + hall.w + 4,
        y: hall.y,
        w: upsSpec.w,
        h: upsSpec.h,
        rotation: 0,
        category: "electrical",
        properties: {},
      });
    }
  }

  // Cooling plant — alongside hall columns
  const coolSpec = DC_CATALOG.cooling_plant;
  const coolCount = Math.ceil(itLoadMw / coolSpec.mw_cooling);
  for (let i = 0; i < Math.min(coolCount, hallCount); i++) {
    const hall = objects.find(o => o.properties?.hall_number === i + 1);
    if (hall) {
      objects.push({
        id: uid("cool"),
        type: "cooling_plant",
        x: hall.x + hall.w + upsSpec.w + 10,
        y: hall.y,
        w: coolSpec.w,
        h: Math.min(coolSpec.h, hall.h),
        rotation: 0,
        category: "infrastructure",
        properties: { mw_cooling: coolSpec.mw_cooling },
      });
    }
  }

  // Office/NOC — near entrance (bottom-left, below substation)
  const offSpec = DC_CATALOG.office_noc;
  const siteBottomY = fuelY + fuelSpec.h + 30;
  objects.push({
    id: uid("office"),
    type: "office_noc",
    x: SETBACK + ROAD_WIDTH,
    y: siteBottomY,
    w: offSpec.w,
    h: offSpec.h,
    rotation: 0,
    category: "infrastructure",
    properties: {},
  });

  // Gatehouse
  const gateSpec = DC_CATALOG.gatehouse;
  objects.push({
    id: uid("gate"),
    type: "gatehouse",
    x: SETBACK + ROAD_WIDTH,
    y: siteBottomY + offSpec.h + 10,
    w: gateSpec.w,
    h: gateSpec.h,
    rotation: 0,
    category: "infrastructure",
    properties: {},
  });

  // Loading dock — rear
  const ldSpec = DC_CATALOG.loading_dock;
  objects.push({
    id: uid("dock"),
    type: "loading_dock",
    x: ox + hallsPerColumn > 1 ? (hallSpec.w + HALL_GAP + 40) * 2 + ox : ox + hallSpec.w + 60,
    y: oy,
    w: ldSpec.w,
    h: ldSpec.h,
    rotation: 0,
    category: "infrastructure",
    properties: {},
  });

  // Car park
  const cpSpec = DC_CATALOG.car_park;
  objects.push({
    id: uid("park"),
    type: "car_park",
    x: SETBACK + ROAD_WIDTH + offSpec.w + 10,
    y: siteBottomY,
    w: cpSpec.w,
    h: cpSpec.h,
    rotation: 0,
    category: "site",
    properties: {},
  });

  // Fire pump (if >20MW)
  if (totalMw > 20) {
    const fpSpec = DC_CATALOG.fire_pump;
    objects.push({
      id: uid("fire"),
      type: "fire_pump",
      x: ox + hallSpec.w + 60,
      y: hallBlockMaxY + 5,
      w: fpSpec.w,
      h: fpSpec.h,
      rotation: 0,
      category: "safety",
      properties: {},
    });
  }

  // SuDS
  const sudsSpec = DC_CATALOG.suds_tank;
  objects.push({
    id: uid("suds"),
    type: "suds_tank",
    x: SETBACK + ROAD_WIDTH + offSpec.w + cpSpec.w + 20,
    y: siteBottomY + 10,
    w: sudsSpec.w,
    h: sudsSpec.h,
    rotation: 0,
    category: "site",
    properties: {},
  });

  const metrics = calculateDCMetrics(objects, itLoadMw, tier);

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

export function calculateDCMetrics(objects, itLoadMw, tier = 3) {
  const pue = TIER_PUE[tier] || 1.3;
  const totalMw = itLoadMw * pue;
  const coolingMw = totalMw - itLoadMw;
  const redundancy = TIER_REDUNDANCY[tier] || "N+1";
  const fuelHours = TIER_FUEL_HOURS[tier] || 48;

  const halls = objects.filter(o => o.type.startsWith("server_hall"));
  const gens = objects.filter(o => o.type === "generator");
  const genTotalMw = gens.length * 2.5;
  const fuelTanks = objects.filter(o => o.type === "fuel_storage");
  const fuelLitres = fuelTanks.length * 100000;

  const maxX = Math.max(...objects.map(o => o.x + o.w), 0);
  const maxY = Math.max(...objects.map(o => o.y + o.h), 0);
  const siteArea = (maxX + 20) * (maxY + 20);

  const buildCostPerMw = tier >= 4 ? 13000000 : tier >= 3 ? 10000000 : 8000000;
  const voltage = totalMw < 5 ? "11kV" : totalMw < 50 ? "33kV" : totalMw < 150 ? "132kV" : "275kV";
  const gridCostMap = { "11kV": 200000, "33kV": 2000000, "132kV": 12000000, "275kV": 30000000 };
  const timelineMap = { "11kV": 12, "33kV": 24, "132kV": 36, "275kV": 48 };

  return {
    it_load_mw: Math.round(itLoadMw * 10) / 10,
    total_facility_mw: Math.round(totalMw * 10) / 10,
    pue,
    cooling_mw: Math.round(coolingMw * 10) / 10,
    tier,
    redundancy,
    hall_count: halls.length,
    generator_count: gens.length,
    generator_total_mw: genTotalMw,
    fuel_storage_litres: fuelLitres,
    fuel_autonomy_hours: fuelHours,
    site_area_m2: Math.round(siteArea),
    site_area_ha: Math.round(siteArea / 10000 * 10) / 10,
    build_cost_gbp: itLoadMw * buildCostPerMw,
    revenue_per_mw_yr_gbp: 1500000, // £125/kW/month wholesale
    grid_connection_voltage: voltage,
    grid_connection_cost_gbp: gridCostMap[voltage] || 5000000,
    grid_connection_timeline_months: timelineMap[voltage] || 36,
  };
}
