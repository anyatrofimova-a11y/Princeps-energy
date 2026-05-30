/**
 * oimStyleAdapter — post-process upstream OpenInfraMap layer specs so they
 * bind to Princeps' Mapbox GL v3 GeoJSON sources instead of OIM's vector tiles.
 *
 * Upstream OIM layers use:
 *     source: 'power'
 *     'source-layer': 'power_line' | 'power_substation' | 'power_substation_point'
 *                   | 'power_plant' | 'power_plant_point' | 'power_generator'
 *                   | 'power_generator_area' | 'power_tower' | 'power_switch'
 *                   | 'power_transformer' | 'power_compensator' | 'power_portal_way'
 *
 * We map each source-layer to one GeoJSON source served from FastAPI:
 *     princeps-osm-power-lines       (osm_power_line)
 *     princeps-osm-power-substations (osm_power_substation, points)
 *     princeps-osm-power-substation-polys (osm_power_substation_poly, polygons)
 *     princeps-osm-power-plants      (osm_power_plant)
 *     princeps-osm-power-generators  (osm_power_generator)
 *     princeps-osm-power-towers      (osm_power_tower)
 *     princeps-osm-power-switchgear  (osm_power_switchgear; carries switches,
 *                                     transformers, compensators)
 *
 * Mapbox GL v3 vs MapLibre incompatibilities we strip here:
 *   - `zorder` (OIM convention only; we honour it for sort order then drop)
 *   - `interpolate-hcl` colour expression (Mapbox supports — kept)
 *   - 'symbol-z-order' = 'source' is supported in Mapbox GL v3 — kept
 *   - 'text-font' values must exist in the basemap's glyph set — caller
 *     can override via OIM_FONT_OVERRIDE if a custom style is used
 */

// Map upstream 'source-layer' name → { source, sourceLayer? } for Princeps.
// `sourceLayer` is undefined for GeoJSON sources (no vector-tile sublayers).
const SOURCE_LAYER_MAP = {
  power_line:                 { source: 'princeps-osm-power-lines' },
  power_substation:           { source: 'princeps-osm-power-substation-polys' },
  power_substation_point:     { source: 'princeps-osm-power-substations' },
  power_plant:                { source: 'princeps-osm-power-plants' },
  power_plant_point:          { source: 'princeps-osm-power-plants' },
  power_generator:            { source: 'princeps-osm-power-generators' },
  power_generator_area:       { source: 'princeps-osm-power-generators' },
  power_tower:                { source: 'princeps-osm-power-towers' },
  power_switch:               { source: 'princeps-osm-power-switchgear' },
  power_transformer:          { source: 'princeps-osm-power-switchgear' },
  power_compensator:          { source: 'princeps-osm-power-switchgear' },
  power_portal_way:           { source: 'princeps-osm-power-lines' }, // rare; share lines
};

// Layer IDs to drop entirely on Mapbox GL v3 if they reference source-layers
// we don't expose. Right now: portal_way (no separate ingest), pole transformer
// stays (we route to switchgear instead).
const DROP_LAYER_IDS = new Set([]);

// Default Mapbox-friendly font stack (overridable per call). The upstream OIM
// style uses ['Noto Sans Regular'] which only exists in OIM's glyph server.
const DEFAULT_FONT = ['DIN Pro Regular', 'Arial Unicode MS Regular'];

/**
 * Adapt a list of OIM layer specs for the Princeps Mapbox GL v3 map.
 *
 * @param {Array} layers - output of style_oim_power.ts default export
 * @param {object} [opts]
 * @param {string} [opts.idPrefix='oim-'] - prefix to add to each layer id (avoid clashes)
 * @param {string[]} [opts.font] - overrides text-font for symbol layers
 * @returns {Array} mapbox layer specs (zorder stripped; ids prefixed)
 */
export function adaptOimLayers(layers, opts = {}) {
  const idPrefix = opts.idPrefix ?? 'oim-';
  const font = opts.font || DEFAULT_FONT;

  // Honour upstream zorder for stable insertion order before stripping it.
  const sorted = [...layers]
    .map((l, i) => ({ ...l, _origIndex: i }))
    .sort((a, b) => (a.zorder ?? a._origIndex) - (b.zorder ?? b._origIndex));

  const out = [];
  for (const layer of sorted) {
    if (DROP_LAYER_IDS.has(layer.id)) continue;

    const sourceLayer = layer['source-layer'];
    const mapping = SOURCE_LAYER_MAP[sourceLayer];
    if (!mapping) {
      // Unknown source-layer — skip silently rather than fail.
      // eslint-disable-next-line no-console
      console.debug(`[oimStyleAdapter] skipping ${layer.id}: unknown source-layer ${sourceLayer}`);
      continue;
    }

    const adapted = { ...layer };
    delete adapted.zorder;
    delete adapted._origIndex;
    adapted.id = `${idPrefix}${layer.id}`;
    adapted.source = mapping.source;
    if (mapping.sourceLayer) {
      adapted['source-layer'] = mapping.sourceLayer;
    } else {
      delete adapted['source-layer'];
    }

    // Override text-font on symbol layers so it matches the Mapbox basemap.
    if (adapted.type === 'symbol' && adapted.layout?.['text-font']) {
      adapted.layout = { ...adapted.layout, 'text-font': font };
    }

    out.push(adapted);
  }
  return out;
}

/**
 * Returns the GeoJSON source IDs the adapted layers will reference. Useful
 * for tearing the overlay down without scanning the full layer list.
 */
export const OIM_SOURCE_IDS = Array.from(new Set(Object.values(SOURCE_LAYER_MAP).map((m) => m.source)));