/**
 * Catenary curve math for overhead line (OHL) conductor sag.
 *
 * A real OHL hangs in a catenary y = a * cosh(x/a) - a, where a = H/w
 * (H = horizontal tension, w = unit weight per metre of conductor).
 *
 * For rendering we just need the sampled polyline between two towers.
 * We parameterise by a "sag ratio" (mid-span sag / span length) which
 * is easy to tweak in the UI. Typical UK OHL sag ratios: 2-4%.
 *
 * No external licence — pure math.
 */

const EARTH_R = 6378137;

// Great-circle horizontal distance in metres (equirectangular is fine for spans <2 km).
export function spanMeters(a, b) {
  const lat1 = (a[1] * Math.PI) / 180;
  const lat2 = (b[1] * Math.PI) / 180;
  const dLat = lat2 - lat1;
  const dLon = ((b[0] - a[0]) * Math.PI) / 180;
  const x = dLon * Math.cos((lat1 + lat2) / 2);
  return Math.sqrt(x * x + dLat * dLat) * EARTH_R;
}

/**
 * Solve catenary parameter `a` given span L and mid-span sag s.
 * Relation: s = a * (cosh(L/(2a)) - 1).
 * We invert numerically (bisection) — cheap and robust.
 */
export function catenaryParam(L, sag) {
  if (sag <= 0 || L <= 0) return Infinity;
  let lo = 1e-3;
  let hi = 1e6;
  for (let i = 0; i < 60; i++) {
    const mid = 0.5 * (lo + hi);
    const computed = mid * (Math.cosh(L / (2 * mid)) - 1);
    if (computed > sag) lo = mid;
    else hi = mid;
  }
  return 0.5 * (lo + hi);
}

/**
 * Build a sampled 3D polyline between towers A and B with catenary sag.
 *
 * @param {[number,number]} a  [lon, lat] of tower A attachment
 * @param {[number,number]} b  [lon, lat] of tower B attachment
 * @param {number} hA          attachment height A (m, AGL)
 * @param {number} hB          attachment height B (m, AGL)
 * @param {object} opts        { sagRatio=0.025, samples=16 }
 * @returns {Array<[number,number,number]>} lon/lat/altitude(m)
 */
export function catenaryPath(a, b, hA, hB, opts = {}) {
  const { sagRatio = 0.025, samples = 16 } = opts;
  const L = spanMeters(a, b);
  if (L < 1) return [[...a, hA], [...b, hB]];
  const sag = Math.max(0.5, L * sagRatio);
  const par = catenaryParam(L, sag);
  const out = new Array(samples + 1);
  for (let i = 0; i <= samples; i++) {
    const t = i / samples;
    // Interpolate horizontally along the great-circle (linear lon/lat is fine for short spans).
    const lon = a[0] + (b[0] - a[0]) * t;
    const lat = a[1] + (b[1] - a[1]) * t;
    // Catenary local sag at horizontal offset x from mid-span.
    const x = (t - 0.5) * L;
    const dip = par * (Math.cosh(x / par) - Math.cosh(L / (2 * par)));
    // Base is linear interpolation between the two attachment heights.
    const base = hA + (hB - hA) * t;
    out[i] = [lon, lat, base + dip];
  }
  return out;
}

/**
 * Given an OSM way (array of tower [lon,lat]) generate a sequence of
 * per-span catenary paths. Returns an array of {path,index} objects
 * suitable for PathLayer with getPath.
 */
export function buildOHLSpans(towers, opts = {}) {
  const { attachHeight = 25, ...rest } = opts;
  const spans = [];
  for (let i = 0; i < towers.length - 1; i++) {
    const a = towers[i];
    const b = towers[i + 1];
    spans.push({
      index: i,
      path: catenaryPath(a, b, attachHeight, attachHeight, rest),
    });
  }
  return spans;
}
