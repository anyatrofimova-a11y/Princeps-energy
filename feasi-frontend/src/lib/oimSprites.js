/**
 * oimSprites — loads OpenInfraMap SVG icons into a Mapbox GL map as images.
 *
 * Upstream OIM uses MapLibre's `virtual:render-svg` Vite plugin to bake SVGs
 * into a sprite sheet at build time. We can't do that for Mapbox GL v3 (which
 * uses a different sprite format), so instead we rasterise each SVG to a 256px
 * PNG via the browser's Image+Canvas APIs and feed it to map.addImage().
 *
 * Called once per map on the first style.load (or load) event. Idempotent —
 * subsequent calls bail if the first image is already registered.
 *
 * Icons live at /public/icons/oim/*.svg (copied verbatim from
 * github.com/openinframap/openinframap/web/src/icons, CC-BY 4.0).
 */

// Canonical list of OIM image IDs referenced from style_oim_power.ts. Keeping
// this in sync with /public/icons/oim/ keeps the loader honest — a missing
// entry will log to console rather than fail silently inside Mapbox.
export const OIM_ICON_IDS = [
  'cabinet',
  'comms_tower',
  'converter',
  'line_ref',
  'power_capacitor',
  'power_capacitor_shunt',
  'power_compensator',
  'power_compensator_frame',
  'power_filter',
  'power_generator',
  'power_generator_solar',
  'power_plant',
  'power_plant_battery',
  'power_plant_biomass',
  'power_plant_coal',
  'power_plant_geothermal',
  'power_plant_hydro',
  'power_plant_nuclear',
  'power_plant_oilgas',
  'power_plant_solar',
  'power_plant_waste',
  'power_plant_wind',
  'power_pole',
  'power_pole_transition',
  'power_portal',
  'power_reactor',
  'power_reactor_shunt',
  'power_switch',
  'power_switch_circuit_breaker',
  'power_switch_disconnector',
  'power_tower',
  'power_tower_transition',
  'power_transformer',
  'power_transformer_3_winding',
  'power_transformer_current',
  'power_transformer_potential',
  'power_wind',
  'pumping_station',
  'sewage_pumping_station',
  'sewage_treatment_plant',
  'telecom_datacenter',
  'telecom_exchange',
  'validation_error',
  'valve',
  'water_pumping_station',
  'water_treatment_plant'
];

const ICON_SIZE = 64; // raster size in px — Mapbox scales further from here

function loadSvgAsImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = (e) => reject(e);
    img.src = url;
  });
}

function rasterise(img) {
  const canvas = document.createElement('canvas');
  canvas.width = ICON_SIZE;
  canvas.height = ICON_SIZE;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.drawImage(img, 0, 0, ICON_SIZE, ICON_SIZE);
  return ctx.getImageData(0, 0, ICON_SIZE, ICON_SIZE);
}

/**
 * Ensure all OIM icons are registered as map images. Safe to call multiple
 * times — only loads icons not already present.
 *
 * @param {mapboxgl.Map} map
 * @param {{iconBase?: string}} [opts]
 * @returns {Promise<number>} count of newly-loaded icons
 */
export async function loadOimSprites(map, opts = {}) {
  if (!map) return 0;
  const base = opts.iconBase || '/icons/oim';
  let loaded = 0;
  await Promise.all(
    OIM_ICON_IDS.map(async (id) => {
      try {
        if (map.hasImage(id)) return;
        const img = await loadSvgAsImage(`${base}/${id}.svg`);
        const data = rasterise(img);
        if (!data) return;
        if (!map.hasImage(id)) {
          map.addImage(id, data, { pixelRatio: 2 });
          loaded += 1;
        }
      } catch (e) {
        // Don't bring the map down for one missing icon — Mapbox just renders blank.
        // eslint-disable-next-line no-console
        console.warn(`[oimSprites] failed to load ${id}:`, e?.message || e);
      }
    })
  );
  return loaded;
}