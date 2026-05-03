// Smoke test for intelligentLayout — run with:
//   node feasi-frontend/scripts/smoke_intelligent_layout.mjs
import {
  buildIntelligentDcLayout,
  parsePolygonWkt,
} from '../src/components/design/placement/intelligentLayout.js';
import * as turf from '@turf/turf';

// Slough Trading Estate rectangle centred at 51.5260, -0.6155 — 2.5ha
// ≈ 160 m × 156 m, axis aligned N-E-S-W (the "default" axis case).
const LAT = 51.5260;
const LON = -0.6155;
const halfLonM = 80;
const halfLatM = 78;
const dLat = halfLatM / 110540;
const dLon = halfLonM / (111320 * Math.cos((LAT * Math.PI) / 180));
const wkt =
  `POLYGON((${LON - dLon} ${LAT - dLat}, ${LON + dLon} ${LAT - dLat}, ` +
  `${LON + dLon} ${LAT + dLat}, ${LON - dLon} ${LAT + dLat}, ` +
  `${LON - dLon} ${LAT - dLat}))`;

console.log('polygon wkt:', wkt);

const result = buildIntelligentDcLayout({
  polygon: wkt,
  capacityMw: 40,
  pocLatLon: [LAT - 0.002, LON], // POC ~200 m south
  roadLatLon: [LAT, LON - 0.002], // public road ~200 m west
  tier: 3,
  redundancy: 'N+1',
});

console.log('meta:', JSON.stringify(result.meta, null, 2));
console.log(
  'assets:',
  result.assets.length,
  '→ inside polygon:',
  result.meta.insidePolygon,
  '/',
  result.meta.total,
);

const ring = parsePolygonWkt(wkt);
const poly = turf.polygon([ring]);
const setback = turf.buffer(poly, -5, { units: 'meters' });

const byCat = {};
const outside = [];
const outsideSetback = [];
for (const a of result.assets) {
  byCat[a.category] = (byCat[a.category] || 0) + 1;
  if (!turf.booleanPointInPolygon(turf.point(a.position), poly)) {
    outside.push(a);
  }
  if (!turf.booleanPointInPolygon(turf.point(a.position), setback)) {
    outsideSetback.push(a);
  }
}
console.log('by category:', byCat);
console.log('outside polygon:', outside.length);
console.log('outside 5m setback:', outsideSetback.length);
for (const a of outside) {
  console.log('  OUTSIDE:', a.id, a.category, a.position);
}
for (const a of outsideSetback) {
  console.log('  SETBACK VIOLATION:', a.id, a.category, a.position);
}

// Genset distance to nearest hall
const gensets = result.assets.filter((a) => a.category === 'genset');
const halls = result.assets.filter((a) => a.category === 'hall');
if (gensets.length && halls.length) {
  let minD = Infinity;
  for (const g of gensets) {
    for (const h of halls) {
      const d = turf.distance(turf.point(g.position), turf.point(h.position), {
        units: 'meters',
      });
      if (d < minD) minD = d;
    }
  }
  console.log('min genset→hall distance (m):', Math.round(minD));
}
