/**
 * Domain layer pack dispatcher.
 *
 * Given the active project's technology, return the right deck.gl layer bundle.
 * For co-located projects, return the union of component packs.
 *
 *   import { getDomainLayerPack, DOMAIN_PACKS } from "./components/map/domain";
 *   const layers = getDomainLayerPack("solar", {
 *     active_layer_toggles: { solar_irradiance: true, solar_slope: false, ... },
 *     viewport_bbox,
 *     timeWindow,
 *     onHover, onClick,
 *   });
 */

import SOLAR_PACK, { makeSolarLayers, SOLAR_SUBLAYERS, SOLAR_ACCENT } from "./solar";
import BESS_PACK,  { makeBessLayers,  BESS_SUBLAYERS,  BESS_ACCENT  } from "./bess";
import DC_PACK,    { makeDcLayers,    DC_SUBLAYERS,    DC_ACCENT    } from "./dc";
import WIND_PACK,  { makeWindLayers,  WIND_SUBLAYERS,  WIND_ACCENT  } from "./wind";
import EV_PACK,    { makeEvLayers,    EV_SUBLAYERS,    EV_ACCENT    } from "./ev";

export const DOMAIN_PACKS = {
  solar: SOLAR_PACK,
  bess:  BESS_PACK,
  dc:    DC_PACK,
  wind:  WIND_PACK,
  ev:    EV_PACK,
};

export const DOMAIN_PACK_IDS = ["solar", "bess", "dc", "wind", "ev", "co-located"];

export {
  SOLAR_PACK, BESS_PACK, DC_PACK, WIND_PACK, EV_PACK,
  SOLAR_SUBLAYERS, BESS_SUBLAYERS, DC_SUBLAYERS, WIND_SUBLAYERS, EV_SUBLAYERS,
  SOLAR_ACCENT, BESS_ACCENT, DC_ACCENT, WIND_ACCENT, EV_ACCENT,
  makeSolarLayers, makeBessLayers, makeDcLayers, makeWindLayers, makeEvLayers,
};

/** Normalise tech strings so we can accept "solar", "pv", "solar_pv", etc. */
export function normaliseTech(tech) {
  if (!tech) return null;
  const t = String(tech).toLowerCase().trim();
  if (["solar", "pv", "solar_pv", "photovoltaic"].includes(t)) return "solar";
  if (["bess", "battery", "battery_storage", "storage"].includes(t)) return "bess";
  if (["dc", "data_centre", "data-centre", "datacentre", "data_center", "hyperscale"].includes(t)) return "dc";
  if (["wind", "onshore_wind", "offshore_wind", "wind_farm"].includes(t)) return "wind";
  if (["ev", "ev_charging", "chargepoint", "charging_hub", "make_ready"].includes(t)) return "ev";
  if (["co-located", "colocated", "co_located", "hybrid"].includes(t)) return "co-located";
  return t;
}

/**
 * Build the deck.gl layer array for a given tech + toggles.
 *
 * @param {string} tech   'solar' | 'bess' | 'dc' | 'wind' | 'ev' | 'co-located'
 * @param {object} params { active_layer_toggles, viewport_bbox, timeWindow, onHover, onClick,
 *                          coLocatedTechs? (array, used when tech==='co-located') }
 * @returns {Array} deck.gl layer instances
 */
export function getDomainLayerPack(tech, params = {}) {
  const {
    active_layer_toggles = {},
    viewport_bbox = null,
    timeWindow = null,
    onHover = null,
    onClick = null,
    coLocatedTechs = null,
  } = params;

  const norm = normaliseTech(tech);
  if (!norm) return [];

  const buildArgs = {
    active: active_layer_toggles,
    viewport_bbox,
    timeWindow,
    onHover,
    onClick,
  };

  if (norm === "co-located") {
    // Union of component packs. Defaults to solar + bess (most common UK case)
    // unless caller provides explicit list.
    const techs = (coLocatedTechs && coLocatedTechs.length)
      ? coLocatedTechs.map(normaliseTech).filter(Boolean)
      : ["solar", "bess"];
    const seen = new Set();
    const out = [];
    for (const t of techs) {
      const pack = DOMAIN_PACKS[t];
      if (!pack) continue;
      for (const layer of pack.build(buildArgs)) {
        if (!seen.has(layer.id)) {
          seen.add(layer.id);
          out.push(layer);
        }
      }
    }
    return out;
  }

  const pack = DOMAIN_PACKS[norm];
  if (!pack) return [];
  return pack.build(buildArgs);
}

/** For legend/UI consumption — returns the sublayer list for a given pack id. */
export function getDomainSublayers(tech) {
  const norm = normaliseTech(tech);
  if (norm === "co-located") {
    return [
      ...(DOMAIN_PACKS.solar?.sublayers || []),
      ...(DOMAIN_PACKS.bess?.sublayers  || []),
    ];
  }
  return DOMAIN_PACKS[norm]?.sublayers || [];
}

export default getDomainLayerPack;
