/**
 * oimTagFormatters — port of OpenInfraMap's friendlynames.ts + friendlyicons.ts
 * for human-readable popups.
 *
 * Sourced from https://github.com/openinframap/openinframap/blob/main/web/src/friendlynames.ts
 * and /friendlyicons.ts (BSD-3-Clause). Princeps fork drops the i18next layer
 * and inlines the English strings.
 */

// Map layer (or source-layer) name → descriptive human label. Matched by
// longest prefix — keep more specific entries above more generic ones.
const FRIENDLY_NAMES = {
  power_transformer: 'Transformer',
  power_tower: 'Power tower',
  power_pole: 'Power pole',
  power_generator_solar: 'Solar generator',
  power_generator: 'Generator',
  power_wind_turbine: 'Wind turbine',
  power_substation: 'Substation',
  power_switch: 'Switch',
  power_compensator: 'Compensator',
  power_converter: 'DC converter',
  power_cable: 'Power cable',
  power_line_underground: 'Underground cable',
  power_line_case: 'Power cable',
  power_line_label: 'Power line',
  power_line: 'Power line',
  power_solar_panel: 'Solar panel',
  power_plant_symbol: 'Power plant',
  power_plant: 'Power plant',
  power_portal: 'Power portal',
  princeps_osm_power_lines: 'Power line',
  princeps_osm_power_substations: 'Substation',
  princeps_osm_power_substation_polys: 'Substation',
  princeps_osm_power_plants: 'Power plant',
  princeps_osm_power_generators: 'Generator',
  princeps_osm_power_towers: 'Power tower',
  princeps_osm_power_switchgear: 'Switchgear',
};

// Icon to show next to the title in the popup header. Path relative to /public.
const FRIENDLY_ICONS = {
  power_transformer: '/icons/oim/power_transformer.svg',
  power_tower: '/icons/oim/power_tower.svg',
  power_pole: '/icons/oim/power_pole.svg',
  power_generator: '/icons/oim/power_generator.svg',
  power_generator_solar: '/icons/oim/power_generator_solar.svg',
  power_wind_turbine: '/icons/oim/power_wind.svg',
  power_plant: '/icons/oim/power_plant.svg',
  power_plant_coal: '/icons/oim/power_plant_coal.svg',
  power_plant_gas: '/icons/oim/power_plant_oilgas.svg',
  power_plant_oil: '/icons/oim/power_plant_oilgas.svg',
  power_plant_nuclear: '/icons/oim/power_plant_nuclear.svg',
  power_plant_solar: '/icons/oim/power_plant_solar.svg',
  power_plant_wind: '/icons/oim/power_plant_wind.svg',
  power_plant_hydro: '/icons/oim/power_plant_hydro.svg',
  power_plant_biomass: '/icons/oim/power_plant_biomass.svg',
  power_plant_battery: '/icons/oim/power_plant_battery.svg',
  power_plant_waste: '/icons/oim/power_plant_waste.svg',
  power_substation: '/icons/oim/power_transformer.svg',
  power_switch: '/icons/oim/power_switch.svg',
  power_compensator: '/icons/oim/power_compensator.svg',
};

/**
 * Returns the friendly label for a Mapbox feature based on its layer/source.
 * Strips the 'oim-' prefix we add in oimStyleAdapter so the match works.
 */
export function friendlyName(feature) {
  if (!feature) return 'Feature';
  const layerId = (feature.layer?.id || '').replace(/^oim-/, '');
  const sourceId = (feature.layer?.source || '').replace(/-/g, '_');
  // Longest-prefix match across layer id and source id.
  const candidates = Object.keys(FRIENDLY_NAMES).sort((a, b) => b.length - a.length);
  for (const key of candidates) {
    if (layerId.startsWith(key) || sourceId.includes(key)) return FRIENDLY_NAMES[key];
  }
  return layerId || 'Feature';
}

/**
 * Returns an icon URL for a feature. For plants we look at the `source` tag
 * (fuel type) to pick a specific image.
 */
export function friendlyIcon(feature) {
  if (!feature) return null;
  const layerId = (feature.layer?.id || '').replace(/^oim-/, '');
  const props = feature.properties || {};
  if (layerId.startsWith('power_plant') && props.source) {
    const key = `power_plant_${String(props.source).toLowerCase()}`;
    if (FRIENDLY_ICONS[key]) return FRIENDLY_ICONS[key];
  }
  const candidates = Object.keys(FRIENDLY_ICONS).sort((a, b) => b.length - a.length);
  for (const key of candidates) {
    if (layerId.startsWith(key)) return FRIENDLY_ICONS[key];
  }
  return null;
}

const VOLTAGE_FIELDS = ['voltage', 'voltage_kv', 'voltage_2', 'voltage_3', 'voltage_4'];

function fmtVoltage(v) {
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return null;
  if (n < 1) return `${(n * 1000).toFixed(0)} V`;
  if (n < 1000) return `${n.toFixed(0)} kV`;
  return `${(n / 1000).toFixed(0)} kV`;
}

function fmtPower(v, unit) {
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return null;
  if (unit === 'MW') return n >= 1000 ? `${(n / 1000).toFixed(2)} GW` : `${n.toFixed(1)} MW`;
  if (unit === 'kW') return n >= 1000 ? `${(n / 1000).toFixed(1)} MW` : `${n.toFixed(0)} kW`;
  return `${n} ${unit}`;
}

/**
 * Convert a feature's raw OSM properties into a clean ordered key/value list
 * for display in the popup. Drops obviously-internal columns (osm_id,
 * fetched_at, raw tag bag) and prettifies units.
 */
export function formatProperties(feature) {
  if (!feature) return [];
  const props = feature.properties || {};
  const out = [];

  // Ordered priority fields first.
  const priority = [
    ['name', 'Name'],
    ['operator', 'Operator'],
    ['ref', 'Reference'],
    ['source', 'Source'],
    ['method', 'Method'],
    ['substation_type', 'Substation type'],
    ['line_type', 'Line type'],
  ];
  for (const [key, label] of priority) {
    const v = props[key];
    if (v != null && v !== '') out.push({ label, value: String(v) });
  }

  // Voltages
  const voltages = VOLTAGE_FIELDS
    .map((f) => fmtVoltage(props[f]))
    .filter(Boolean);
  if (voltages.length) out.push({ label: voltages.length > 1 ? 'Voltages' : 'Voltage', value: voltages.join(' / ') });

  // Power output
  const mw = fmtPower(props.output_mw, 'MW');
  if (mw) out.push({ label: 'Output', value: mw });
  const kw = fmtPower(props.output_kw, 'kW');
  if (kw && !mw) out.push({ label: 'Output', value: kw });

  // Lifecycle
  if (props.construction) out.push({ label: 'Status', value: 'Under construction' });
  if (props.disused) out.push({ label: 'Status', value: 'Disused' });

  // Transformer details
  if (props.voltage_primary) out.push({ label: 'Primary', value: fmtVoltage(props.voltage_primary) || props.voltage_primary });
  if (props.voltage_secondary) out.push({ label: 'Secondary', value: fmtVoltage(props.voltage_secondary) || props.voltage_secondary });
  if (props.voltage_tertiary) out.push({ label: 'Tertiary', value: fmtVoltage(props.voltage_tertiary) || props.voltage_tertiary });
  if (props.rating) out.push({ label: 'Rating', value: props.rating });
  if (props.windings) out.push({ label: 'Windings', value: String(props.windings) });

  // REPD linkage — links our OSM plant row to a regulatory record.
  if (props.repd_id) out.push({ label: 'REPD ID', value: String(props.repd_id) });

  // Frequency, circuits, cables — only if present
  if (props.frequency) out.push({ label: 'Frequency', value: `${props.frequency} Hz` });
  if (props.circuits) out.push({ label: 'Circuits', value: String(props.circuits) });
  if (props.cables) out.push({ label: 'Cables', value: String(props.cables) });

  return out;
}

/**
 * Returns the Wikidata QID if the feature has one in its tags JSONB, else null.
 */
export function wikidataQid(feature) {
  if (!feature) return null;
  const props = feature.properties || {};
  let tags = props.tags;
  if (typeof tags === 'string') {
    try { tags = JSON.parse(tags); } catch { tags = null; }
  }
  return (tags && (tags.wikidata || tags['ref:wikidata'])) || props.wikidata || null;
}

/**
 * Returns the OSM URL (way/node/relation) for a feature, derived from osm_id.
 * We don't know the type for sure on the front end, so default to "way" — OSM
 * will 404 silently for the wrong type, but the user can switch.
 */
export function osmUrl(feature) {
  if (!feature) return null;
  const id = feature.properties?.osm_id;
  if (!id) return null;
  // Heuristic — points are typically nodes, lines/polys are typically ways.
  const geomType = feature.geometry?.type || '';
  const kind = geomType === 'Point' ? 'node' : 'way';
  return `https://www.openstreetmap.org/${kind}/${id}`;
}
