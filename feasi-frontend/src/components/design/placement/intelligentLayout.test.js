// Unit tests for intelligentLayout — guards the invariant "every DC asset
// must sit inside the project red-line polygon" for two site archetypes:
//   1. 2.5ha axis-aligned rectangle (Slough Trading Estate style)
//   2. 10ha rectangle rotated 35° off north (hyperscale campus style)

import { describe, it, expect } from 'vitest';
import * as turf from '@turf/turf';
import {
  buildIntelligentDcLayout,
  parsePolygonWkt,
} from './intelligentLayout.js';

function buildAxisAlignedWkt(lat, lon, halfLenM, halfWidM) {
  const dLat = halfWidM / 110540;
  const dLon = halfLenM / (111320 * Math.cos((lat * Math.PI) / 180));
  const ring = [
    [lon - dLon, lat - dLat],
    [lon + dLon, lat - dLat],
    [lon + dLon, lat + dLat],
    [lon - dLon, lat + dLat],
    [lon - dLon, lat - dLat],
  ];
  return `POLYGON((${ring.map(([a, b]) => `${a} ${b}`).join(', ')}))`;
}

function buildRotatedWkt(lat, lon, halfLenM, halfWidM, rotDeg) {
  const mPerDegLat = 110540;
  const mPerDegLon = 111320 * Math.cos((lat * Math.PI) / 180);
  const rot = (rotDeg * Math.PI) / 180;
  const c = Math.cos(rot);
  const s = Math.sin(rot);
  const corners = [
    [-halfLenM, -halfWidM],
    [halfLenM, -halfWidM],
    [halfLenM, halfWidM],
    [-halfLenM, halfWidM],
    [-halfLenM, -halfWidM],
  ].map(([x, y]) => [x * c - y * s, x * s + y * c]);
  const ll = corners.map(([x, y]) => [
    lon + x / mPerDegLon,
    lat + y / mPerDegLat,
  ]);
  return `POLYGON((${ll.map(([a, b]) => `${a} ${b}`).join(', ')}))`;
}

describe('intelligentLayout — 2.5ha axis-aligned polygon', () => {
  const LAT = 51.5260;
  const LON = -0.6155;
  const wkt = buildAxisAlignedWkt(LAT, LON, 80, 78);
  const result = buildIntelligentDcLayout({
    polygon: wkt,
    capacityMw: 40,
    pocLatLon: [LAT - 0.002, LON],
    roadLatLon: [LAT, LON - 0.002],
  });
  const poly = turf.polygon([parsePolygonWkt(wkt)]);
  const setback = turf.buffer(poly, -5, { units: 'meters' });

  it('places every asset inside the red-line polygon', () => {
    for (const a of result.assets) {
      expect(
        turf.booleanPointInPolygon(turf.point(a.position), poly),
      ).toBe(true);
    }
  });

  it('respects the 5 m red-line setback for every asset centre', () => {
    for (const a of result.assets) {
      expect(
        turf.booleanPointInPolygon(turf.point(a.position), setback),
      ).toBe(true);
    }
  });

  it('produces the full asset vocabulary', () => {
    const cats = new Set(result.assets.map((a) => a.category));
    for (const c of ['hall', 'tx_yard', 'gatehouse', 'office', 'genset', 'crac', 'ups']) {
      expect(cats.has(c)).toBe(true);
    }
  });

  it('reports a roughly correct area and long-axis bearing', () => {
    expect(result.meta.areaM2).toBeGreaterThan(24000);
    expect(result.meta.areaM2).toBeLessThan(26000);
    // axis-aligned E-W rectangle → long axis runs east (bearing 90°)
    expect(Math.abs(result.meta.longAxisBearingDeg - 90)).toBeLessThan(5);
  });
});

describe('intelligentLayout — 10ha rotated polygon', () => {
  const LAT = 51.5260;
  const LON = -0.6155;
  const wkt = buildRotatedWkt(LAT, LON, 200, 125, 35);
  const result = buildIntelligentDcLayout({
    polygon: wkt,
    capacityMw: 120,
    pocLatLon: [LAT - 0.003, LON + 0.002],
    roadLatLon: [LAT + 0.003, LON - 0.002],
  });
  const poly = turf.polygon([parsePolygonWkt(wkt)]);

  it('places every asset inside the polygon', () => {
    for (const a of result.assets) {
      expect(
        turf.booleanPointInPolygon(turf.point(a.position), poly),
      ).toBe(true);
    }
  });

  it('maintains >50 m fire break between gensets and halls', () => {
    const gensets = result.assets.filter((a) => a.category === 'genset');
    const halls = result.assets.filter((a) => a.category === 'hall');
    let minD = Infinity;
    for (const g of gensets) {
      for (const h of halls) {
        const d = turf.distance(
          turf.point(g.position),
          turf.point(h.position),
          { units: 'meters' },
        );
        if (d < minD) minD = d;
      }
    }
    expect(minD).toBeGreaterThanOrEqual(50);
  });

  it('detects the rotated long axis near the input rotation', () => {
    // For 35° rotation, long axis bearing ≈ 90°−35° = 55° (or symmetric 235°)
    const b = result.meta.longAxisBearingDeg;
    const ok =
      Math.abs(b - 55) < 8 ||
      Math.abs(b - 235) < 8 ||
      Math.abs(b - 125) < 8 || // 90° wrap
      Math.abs(b - 305) < 8;
    expect(ok).toBe(true);
  });
});

describe('intelligentLayout — degenerate inputs', () => {
  it('returns empty layout for invalid polygon', () => {
    const r = buildIntelligentDcLayout({
      polygon: 'NOT A POLYGON',
      capacityMw: 40,
    });
    expect(r.assets).toEqual([]);
    expect(r.meta.error).toBe('invalid_polygon');
  });

  it('returns empty layout for non-positive capacity', () => {
    const wkt = buildAxisAlignedWkt(51.5, -0.1, 100, 100);
    const r = buildIntelligentDcLayout({ polygon: wkt, capacityMw: 0 });
    expect(r.assets).toEqual([]);
    expect(r.meta.error).toBe('invalid_capacity');
  });
});
