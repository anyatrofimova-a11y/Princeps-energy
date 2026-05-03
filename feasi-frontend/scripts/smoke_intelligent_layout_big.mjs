// Smoke test: 10 ha rotated rectangle + larger capacity.
import {
  buildIntelligentDcLayout,
  parsePolygonWkt,
} from '../src/components/design/placement/intelligentLayout.js';
import * as turf from '@turf/turf';

// 10 ha site ~ 400 × 250 m, rotated 35° clockwise from north-south.
const LAT = 51.5260;
const LON = -0.6155;
const halfL = 200;
const halfW = 125;
const rot = (35 * Math.PI) / 180;
// Build rotated rectangle in ENU, then convert to lng/lat
const mPerDegLat = 110540;
const mPerDegLon = 111320 * Math.cos((LAT * Math.PI) / 180);
const c = Math.cos(rot);
const s = Math.sin(rot);
const corners = [
  [-halfL, -halfW],
  [halfL, -halfW],
  [halfL, halfW],
  [-halfL, halfW],
  [-halfL, -halfW],
].map(([x, y]) => [x * c - y * s, x * s + y * c]);
const lngLat = corners.map(([x, y]) => [LON + x / mPerDegLon, LAT + y / mPerDegLat]);
const wkt =
  'POLYGON((' + lngLat.map(([a, b]) => `${a} ${b}`).join(', ') + '))';

console.log('polygon wkt:', wkt);

const result = buildIntelligentDcLayout({
  polygon: wkt,
  capacityMw: 120,
  pocLatLon: [LAT - 0.003, LON + 0.002],
  roadLatLon: [LAT + 0.003, LON - 0.002],
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
let outside = 0;
let outsideSetback = 0;
for (const a of result.assets) {
  byCat[a.category] = (byCat[a.category] || 0) + 1;
  if (!turf.booleanPointInPolygon(turf.point(a.position), poly)) outside += 1;
  if (!turf.booleanPointInPolygon(turf.point(a.position), setback))
    outsideSetback += 1;
}
console.log('by category:', byCat);
console.log('outside polygon:', outside);
console.log('outside 5m setback:', outsideSetback);

const gensets = result.assets.filter((a) => a.category === 'genset');
const halls = result.assets.filter((a) => a.category === 'hall');
let minD = Infinity;
for (const g of gensets) {
  for (const h of halls) {
    const d = turf.distance(turf.point(g.position), turf.point(h.position), {
      units: 'meters',
    });
    if (d < minD) minD = d;
  }
}
console.log('halls:', halls.length, '  gensets:', gensets.length);
console.log('min genset→hall distance (m):', Math.round(minD));
