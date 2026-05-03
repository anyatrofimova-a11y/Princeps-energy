// Live verification — fetch the real Slough project from the running
// backend and ensure intelligentLayout lands every asset inside the red-
// line polygon. Run from the feasi-frontend directory:
//   node scripts/verify_live_layout.mjs
import { buildIntelligentDcLayout } from '../src/components/design/placement/intelligentLayout.js';
import * as turf from '@turf/turf';

const SLOUGH_ID = 'd0003220-e879-4b19-bc6b-235771f1a517';
const r = await fetch(
  `http://localhost:8000/api/v1/projects/${SLOUGH_ID}`,
);
if (!r.ok) {
  console.error('project fetch failed:', r.status);
  process.exit(1);
}
const project = await r.json();
console.log(
  'project:',
  project.name,
  '— tech:',
  project.technology,
  'capacity:',
  project.capacity_mw,
  'MW',
);
// Mirror useDesignProject's box-synthesis fallback when no explicit
// polygon_wkt is on the record. 300 m × 300 m box centred on (lat, lon).
function buildBoxWkt(lat, lon, halfSizeM = 150) {
  if (lat == null || lon == null) return null;
  const mPerDegLat = 110540;
  const mPerDegLon = 111320 * Math.cos((lat * Math.PI) / 180);
  const dLat = halfSizeM / mPerDegLat;
  const dLon = halfSizeM / mPerDegLon;
  const ring = [
    [lon - dLon, lat - dLat],
    [lon + dLon, lat - dLat],
    [lon + dLon, lat + dLat],
    [lon - dLon, lat + dLat],
    [lon - dLon, lat - dLat],
  ];
  return `POLYGON((${ring.map(([a, b]) => `${a} ${b}`).join(', ')}))`;
}

const polygon_wkt =
  project.polygon_wkt ||
  project.site_polygon_wkt ||
  project.polygon ||
  buildBoxWkt(project.lat, project.lon);
if (!polygon_wkt) {
  console.error('no polygon_wkt on project — cannot verify');
  process.exit(2);
}
console.log('polygon_wkt length:', polygon_wkt.length, '(synthesised:',
  !(project.polygon_wkt || project.site_polygon_wkt), ')');

const result = buildIntelligentDcLayout({
  polygon: polygon_wkt,
  capacityMw: project.capacity_mw || 40,
  pocLatLon:
    project.poc_lat && project.poc_lon
      ? [project.poc_lat, project.poc_lon]
      : null,
  roadLatLon:
    project.road_lat && project.road_lon
      ? [project.road_lat, project.road_lon]
      : null,
  tier: project.tier || 3,
  redundancy: project.redundancy || 'N+1',
});
console.log('meta:', JSON.stringify(result.meta, null, 2));

// Re-parse polygon via turf for the containment check.
const m = polygon_wkt.trim().match(/POLYGON\s*\(\s*\(([^)]+)\)\s*\)/i);
if (!m) {
  console.error('could not parse polygon for verification');
  process.exit(3);
}
const ring = m[1]
  .split(',')
  .map((pair) => pair.trim().split(/\s+/).map(Number).slice(0, 2));
if (
  ring[0][0] !== ring[ring.length - 1][0] ||
  ring[0][1] !== ring[ring.length - 1][1]
) {
  ring.push(ring[0]);
}
const poly = turf.polygon([ring]);

let outside = 0;
const byCat = {};
for (const a of result.assets) {
  byCat[a.category] = (byCat[a.category] || 0) + 1;
  if (!turf.booleanPointInPolygon(turf.point(a.position), poly)) {
    outside += 1;
    console.log('  OUTSIDE:', a.id, a.category, a.position);
  }
}
console.log('by category:', byCat);
console.log('assets inside polygon:', result.assets.length - outside, '/', result.assets.length);
console.log(outside === 0 ? 'PASS ✓' : 'FAIL ✗');
