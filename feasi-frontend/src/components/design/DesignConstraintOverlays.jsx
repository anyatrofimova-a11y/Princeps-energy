/**
 * DesignConstraintOverlays — mapbox-gl source + layer builders for the
 * Site Designer canvas (BOT-SDB, 2026-04-21).
 *
 * Produces Glint-Solar-style constraint overlays on top of a satellite
 * basemap:
 *   - Buildable area (gold tint)
 *   - EA Flood Zones 2 / 3 (blue outline)
 *   - Statutory designations (SSSI / AONB / Green Belt — red/amber outline)
 *   - Agricultural Land Classification grades 1 / 2 (olive outline)
 *   - Planning red-line (thick gold border)
 *   - Setback rings (property, road, noise — dashed deck.gl polygons)
 *   - Sun-path solstice cones (summer/equinox/winter — binds to the
 *     backend `/api/dc/glint-screen` BOT-B2 shipped)
 *
 * Designed to be *idempotent*: every helper checks for pre-existing sources
 * and layers so React effects that re-run safely repeat the call. Layers
 * carry the `dsgn-` prefix so sibling overlays (BOT-SDL/BOT-SDE) never
 * collide with ours.
 *
 * Exported helpers:
 *   - ensureConstraintSourcesAndLayers(map)        — one-time DOM setup
 *   - setConstraintData(map, ctx, shellLngLat)     — pushes GeoJSON
 *   - setConstraintVisibility(map, toggles)        — show/hide
 *   - buildSetbackRings(lngLat, sizeM, roadBearing)
 *   - buildSunPathArcs(lat, lon, season) → PathLayer data
 */

const LAYER_PREFIX = "dsgn-";
const SOURCES = {
  buildable: `${LAYER_PREFIX}buildable`,
  flood: `${LAYER_PREFIX}flood`,
  designations: `${LAYER_PREFIX}designations`,
  alc: `${LAYER_PREFIX}alc`,
  redline: `${LAYER_PREFIX}redline`,
  setbacks: `${LAYER_PREFIX}setbacks`,
  sunpath: `${LAYER_PREFIX}sunpath`,
};

const LAYERS = {
  buildable_fill: `${LAYER_PREFIX}buildable-fill`,
  flood_fill: `${LAYER_PREFIX}flood-fill`,
  flood_line: `${LAYER_PREFIX}flood-line`,
  designations_fill: `${LAYER_PREFIX}designations-fill`,
  designations_line: `${LAYER_PREFIX}designations-line`,
  alc_fill: `${LAYER_PREFIX}alc-fill`,
  alc_line: `${LAYER_PREFIX}alc-line`,
  redline_line: `${LAYER_PREFIX}redline-line`,
  redline_fill: `${LAYER_PREFIX}redline-fill`,
  setbacks_line: `${LAYER_PREFIX}setbacks-line`,
  setbacks_fill: `${LAYER_PREFIX}setbacks-fill`,
  setbacks_labels: `${LAYER_PREFIX}setbacks-labels`,
  sunpath_line: `${LAYER_PREFIX}sunpath-line`,
};

const EMPTY_FC = { type: "FeatureCollection", features: [] };

/* ─── bucket a buildable-mask Feature by its `class` property ───────────── */
function bucketMaskFeature(f) {
  const cls = f?.properties?.class;
  if (cls === "restricted_flood") return "flood";
  if (cls === "restricted_protected" || cls === "restricted_land")
    return "designations";
  if (cls === "restricted_alc") return "alc";
  if (!cls || cls === "buildable") return "buildable";
  return null;
}

/* ───────── DOM setup — add every source + layer idempotently ──────────── */
export function ensureConstraintSourcesAndLayers(map) {
  if (!map || map._removed) return;

  const addSrc = (id) => {
    if (!map.getSource(id)) map.addSource(id, { type: "geojson", data: EMPTY_FC });
  };
  Object.values(SOURCES).forEach(addSrc);

  // The first symbol layer is our "before" target so overlays render under
  // labels / roads rather than over them (same trick Mapbox's examples use).
  const beforeId =
    map.getStyle().layers?.find(
      (l) => l.type === "symbol" && l.layout?.["text-field"],
    )?.id;

  const safeAdd = (layer, before) => {
    if (map.getLayer(layer.id)) return;
    try {
      if (before && map.getLayer(before)) map.addLayer(layer, before);
      else map.addLayer(layer);
    } catch {
      // style may have reshuffled
      try {
        map.addLayer(layer);
      } catch {
        /* noop */
      }
    }
  };

  /* 1. Buildable — gold translucent */
  safeAdd(
    {
      id: LAYERS.buildable_fill,
      type: "fill",
      source: SOURCES.buildable,
      paint: {
        "fill-color": "#F5B731",
        "fill-opacity": 0.18,
        "fill-outline-color": "rgba(245,183,49,0.55)",
      },
      layout: { visibility: "visible" },
    },
    beforeId,
  );

  /* 2. Flood zones — blue outline */
  safeAdd(
    {
      id: LAYERS.flood_fill,
      type: "fill",
      source: SOURCES.flood,
      paint: {
        "fill-color": "#38BDF8",
        "fill-opacity": 0.18,
      },
      layout: { visibility: "none" },
    },
    beforeId,
  );
  safeAdd(
    {
      id: LAYERS.flood_line,
      type: "line",
      source: SOURCES.flood,
      paint: {
        "line-color": "#0284c7",
        "line-width": 1.4,
        "line-dasharray": [2, 2],
      },
      layout: { visibility: "none" },
    },
    beforeId,
  );

  /* 3. Designations — red (SSSI/AONB) + amber (green-belt/woodland) */
  safeAdd(
    {
      id: LAYERS.designations_fill,
      type: "fill",
      source: SOURCES.designations,
      paint: {
        "fill-color": [
          "match",
          ["get", "class"],
          "restricted_protected", "#DC2626",
          "restricted_land",      "#F59E0B",
          /* default */           "#EF4444",
        ],
        "fill-opacity": 0.2,
      },
      layout: { visibility: "none" },
    },
    beforeId,
  );
  safeAdd(
    {
      id: LAYERS.designations_line,
      type: "line",
      source: SOURCES.designations,
      paint: {
        "line-color": [
          "match",
          ["get", "class"],
          "restricted_protected", "#991B1B",
          "restricted_land",      "#B45309",
          /* default */           "#B91C1C",
        ],
        "line-width": 1.6,
      },
      layout: { visibility: "none" },
    },
    beforeId,
  );

  /* 4. ALC grade 1/2 — olive */
  safeAdd(
    {
      id: LAYERS.alc_fill,
      type: "fill",
      source: SOURCES.alc,
      paint: { "fill-color": "#84cc16", "fill-opacity": 0.18 },
      layout: { visibility: "none" },
    },
    beforeId,
  );
  safeAdd(
    {
      id: LAYERS.alc_line,
      type: "line",
      source: SOURCES.alc,
      paint: { "line-color": "#65a30d", "line-width": 1.3 },
      layout: { visibility: "none" },
    },
    beforeId,
  );

  /* 5. Planning red-line — thick gold border */
  safeAdd({
    id: LAYERS.redline_fill,
    type: "fill",
    source: SOURCES.redline,
    paint: { "fill-color": "#F5B731", "fill-opacity": 0.05 },
    layout: { visibility: "visible" },
  });
  safeAdd({
    id: LAYERS.redline_line,
    type: "line",
    source: SOURCES.redline,
    paint: {
      "line-color": "#D97706",
      "line-width": 3.4,
      "line-dasharray": [4, 2],
    },
    layout: { visibility: "visible" },
  });

  /* 6. Setbacks — dashed outlines */
  safeAdd({
    id: LAYERS.setbacks_fill,
    type: "fill",
    source: SOURCES.setbacks,
    paint: {
      "fill-color": [
        "match",
        ["get", "kind"],
        "property", "rgba(148,163,184,0.08)",
        "road",     "rgba(244,114,182,0.06)",
        "noise",    "rgba(34,197,94,0.05)",
        /* default */ "rgba(0,0,0,0)",
      ],
      "fill-opacity": 1,
    },
    layout: { visibility: "none" },
  });
  safeAdd({
    id: LAYERS.setbacks_line,
    type: "line",
    source: SOURCES.setbacks,
    paint: {
      "line-color": [
        "match",
        ["get", "kind"],
        "property", "#64748b",
        "road",     "#f472b6",
        "noise",    "#22c55e",
        /* default */ "#94a3b8",
      ],
      "line-width": 1.3,
      "line-dasharray": [3, 3],
    },
    layout: { visibility: "none" },
  });
  safeAdd({
    id: LAYERS.setbacks_labels,
    type: "symbol",
    source: SOURCES.setbacks,
    layout: {
      "text-field": ["get", "label"],
      "text-size": 9,
      "text-allow-overlap": false,
      visibility: "none",
    },
    paint: {
      "text-color": "#ffffff",
      "text-halo-color": "#000",
      "text-halo-width": 1.1,
    },
  });

  /* 7. Sun-path — coloured lines by season */
  safeAdd({
    id: LAYERS.sunpath_line,
    type: "line",
    source: SOURCES.sunpath,
    paint: {
      "line-color": [
        "match",
        ["get", "season"],
        "summer", "#fbbf24",
        "winter", "#60a5fa",
        "equinox", "#f97316",
        /* default */ "#fef3c7",
      ],
      "line-width": 2.0,
      "line-opacity": 0.85,
    },
    layout: { visibility: "none" },
  });
}

/* ─── Geometry helpers ─────────────────────────────────────────────────── */
const DEG_PER_M_LAT = 1 / 111_320;
const degPerMLon = (lat) => 1 / (111_320 * Math.cos((lat * Math.PI) / 180));

/**
 * Axis-aligned rectangular ring centred on (lat, lon) with half-size `halfM`.
 */
function rectRing(lat, lon, halfM) {
  const dLat = halfM * DEG_PER_M_LAT;
  const dLon = halfM * degPerMLon(lat);
  return [
    [lon - dLon, lat - dLat],
    [lon + dLon, lat - dLat],
    [lon + dLon, lat + dLat],
    [lon - dLon, lat + dLat],
    [lon - dLon, lat - dLat],
  ];
}

/**
 * Build three setback rings around the site centroid — encoded as mapbox-gl
 * Polygon features with a `kind` + `label` prop the style rules branch on.
 *
 * Computation:
 *   - property setback: 10 m offset from the nominal parcel edge (taken as
 *     the site centroid's inferred footprint; for an MVP we use a
 *     `parcelHalfM` radius of 60 m if the caller doesn't provide a parcel)
 *   - road setback: 20 m offset (applied only if the caller flags a road
 *     crossing through the parcel — else emitted as 0-area and hidden)
 *   - noise setback: 50 m offset (applied if a receptor is within 75 m)
 */
export function buildSetbackRings({
  lat,
  lon,
  parcelHalfM = 60,
  hasRoadCrossing = false,
  hasNearbyReceptor = false,
}) {
  if (lat == null || lon == null) return EMPTY_FC;
  const features = [];

  features.push({
    type: "Feature",
    properties: { kind: "property", offset_m: 10, label: "Prop 10 m" },
    geometry: { type: "Polygon", coordinates: [rectRing(lat, lon, parcelHalfM + 10)] },
  });

  if (hasRoadCrossing) {
    features.push({
      type: "Feature",
      properties: { kind: "road", offset_m: 20, label: "Road 20 m" },
      geometry: {
        type: "Polygon",
        coordinates: [rectRing(lat, lon, parcelHalfM + 20)],
      },
    });
  }

  if (hasNearbyReceptor) {
    features.push({
      type: "Feature",
      properties: { kind: "noise", offset_m: 50, label: "Noise 50 m" },
      geometry: {
        type: "Polygon",
        coordinates: [rectRing(lat, lon, parcelHalfM + 50)],
      },
    });
  }

  return { type: "FeatureCollection", features };
}

/* ─── Sun-path arcs ────────────────────────────────────────────────────── */
/**
 * Turn the `/api/dc/glint-screen` payload into three polyline features —
 * one per season (summer / equinox / winter). The backend returns cone
 * polygons; for the sun-path overlay we want the *bearing-of-sun* sweep
 * from sunrise → noon → sunset, so we synthesise a poly-arc from the noon
 * azimuth + sun-altitude projected onto the ground plane.
 *
 * Approximation: a half-ellipse of length 300 m centred on the site,
 * oriented along the solar-noon bearing. Sufficient for the "where does
 * the sun come from" viz Glint shows.
 */
export function buildSunPathArcs({ lat, lon, glintCones }) {
  if (lat == null || lon == null) return EMPTY_FC;
  // Fallback seasons if /api/dc/glint-screen is offline.
  const fallback = [
    { season: "summer",  bearing: 0,   length_m: 320, sun_alt: 62 },
    { season: "equinox", bearing: 0,   length_m: 250, sun_alt: 38 },
    { season: "winter",  bearing: 0,   length_m: 180, sun_alt: 15 },
  ];
  const cones = glintCones?.cones?.length
    ? glintCones.cones.map((c) => ({
        season: c.season || "equinox",
        bearing: c.bearing_deg ?? 0,
        length_m: c.length_m ?? 250,
        sun_alt: c.sun_alt_deg ?? 38,
      }))
    : fallback;

  // Ensure we emit one arc per season at most.
  const bySeason = {};
  for (const c of cones) if (!bySeason[c.season]) bySeason[c.season] = c;
  if (!bySeason.equinox) bySeason.equinox = fallback[1];

  const dLat = DEG_PER_M_LAT;
  const dLon = degPerMLon(lat);

  const features = Object.values(bySeason).map((c) => {
    // Sample a 20-point arc that sweeps ±90° around the solar-noon bearing.
    // Points are laid out on the compass (sun AZIMUTH). We flip the bearing
    // so the arc represents where the sun *is*, not where the beam reflects.
    const sunBearing = (c.bearing + 180) % 360; // opposite of reflected beam
    const coords = [];
    const N = 24;
    for (let i = 0; i <= N; i += 1) {
      const t = i / N;
      const az = sunBearing - 90 + t * 180; // sweep -90°→+90° of noon
      const rad = (az * Math.PI) / 180;
      const r = c.length_m;
      // Flatten the arc toward the horizon at low altitudes.
      const flatten = Math.cos((c.sun_alt * Math.PI) / 180);
      const dx = Math.sin(rad) * r * flatten;
      const dy = Math.cos(rad) * r * flatten;
      coords.push([lon + dx * dLon, lat + dy * dLat]);
    }
    return {
      type: "Feature",
      properties: {
        season: c.season,
        bearing_deg: sunBearing,
        sun_alt_deg: c.sun_alt,
      },
      geometry: { type: "LineString", coordinates: coords },
    };
  });

  return { type: "FeatureCollection", features };
}

/* ─── Red-line polygon from the shell or site centroid ─────────────────── */
export function buildRedLine({ lat, lon, halfM = 80 }) {
  if (lat == null || lon == null) return EMPTY_FC;
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: { role: "red-line", buffer_m: halfM },
        geometry: { type: "Polygon", coordinates: [rectRing(lat, lon, halfM)] },
      },
    ],
  };
}

/* ─── Bucket the buildable-mask FC into three FCs (buildable/desig/alc) ── */
export function bucketConstraintData(ctx) {
  const out = {
    buildable: EMPTY_FC,
    designations: EMPTY_FC,
    alc: EMPTY_FC,
    flood: ctx?.floodZones || EMPTY_FC,
  };
  const feats = ctx?.buildableMask?.features || [];
  if (!feats.length) return out;

  const buckets = { buildable: [], designations: [], alc: [], flood: [] };
  for (const f of feats) {
    const b = bucketMaskFeature(f);
    if (b && buckets[b]) buckets[b].push(f);
  }
  out.buildable = { type: "FeatureCollection", features: buckets.buildable };
  out.designations = { type: "FeatureCollection", features: buckets.designations };
  out.alc = { type: "FeatureCollection", features: buckets.alc };
  // Merge buildable-mask flood-class polygons with EA Flood endpoint features.
  if (buckets.flood.length) {
    out.flood = {
      type: "FeatureCollection",
      features: [...(out.flood.features || []), ...buckets.flood],
    };
  }
  return out;
}

/* ─── Push context data into mapbox-gl sources ─────────────────────────── */
export function setConstraintData(map, ctx, { lat, lon } = {}) {
  if (!map || map._removed) return;
  const apply = () => {
    try {
      if (map._removed) return;
      const buckets = bucketConstraintData(ctx);

      const set = (srcId, data) => {
        const src = map.getSource(srcId);
        if (src && typeof src.setData === "function") src.setData(data || EMPTY_FC);
      };
      set(SOURCES.buildable, buckets.buildable);
      set(SOURCES.designations, buckets.designations);
      set(SOURCES.alc, buckets.alc);
      set(SOURCES.flood, buckets.flood);
      if (lat != null && lon != null) {
        set(SOURCES.redline, buildRedLine({ lat, lon, halfM: 80 }));
        set(
          SOURCES.setbacks,
          buildSetbackRings({ lat, lon, parcelHalfM: 60, hasRoadCrossing: true, hasNearbyReceptor: false }),
        );
        set(
          SOURCES.sunpath,
          buildSunPathArcs({ lat, lon, glintCones: ctx?.glintCones }),
        );
      }
    } catch {
      /* style not ready, ignore */
    }
  };
  if (map.isStyleLoaded && map.isStyleLoaded()) apply();
  else map.once("load", apply);
}

/* ─── Toggle visibility ────────────────────────────────────────────────── */
export function setConstraintVisibility(map, toggles = {}) {
  if (!map || map._removed) return;
  const vis = (layerId, on) => {
    if (!map.getLayer(layerId)) return;
    try {
      map.setLayoutProperty(layerId, "visibility", on ? "visible" : "none");
    } catch {
      /* noop */
    }
  };
  vis(LAYERS.buildable_fill, toggles.buildable !== false);
  vis(LAYERS.flood_fill, !!toggles.flood);
  vis(LAYERS.flood_line, !!toggles.flood);
  vis(LAYERS.designations_fill, !!toggles.designations);
  vis(LAYERS.designations_line, !!toggles.designations);
  vis(LAYERS.alc_fill, !!toggles.alc);
  vis(LAYERS.alc_line, !!toggles.alc);
  vis(LAYERS.redline_fill, toggles.redline !== false);
  vis(LAYERS.redline_line, toggles.redline !== false);
  vis(LAYERS.setbacks_fill, !!toggles.setbacks);
  vis(LAYERS.setbacks_line, !!toggles.setbacks);
  vis(LAYERS.setbacks_labels, !!toggles.setbacks);
  vis(LAYERS.sunpath_line, !!toggles.sunpath);
}

/* ─── Floating toggle panel for the designer canvas ────────────────────── */
export function DesignOverlayTogglePanel({ toggles, onToggle, ctx }) {
  const buildableCount = ctx?.buildableMask?.features?.length || 0;
  const designationCount = (ctx?.buildableMask?.features || []).filter(
    (f) =>
      f?.properties?.class === "restricted_protected" ||
      f?.properties?.class === "restricted_land",
  ).length;
  const alcCount = (ctx?.buildableMask?.features || []).filter(
    (f) => f?.properties?.class === "restricted_alc",
  ).length;
  const floodCount =
    (ctx?.floodZones?.features?.length || 0) +
    (ctx?.buildableMask?.features || []).filter(
      (f) => f?.properties?.class === "restricted_flood",
    ).length;

  const groups = [
    {
      title: "Context",
      rows: [
        { key: "redline", label: "Red-line", count: null, alwaysEnabled: true },
        { key: "buildable", label: "Buildable area", count: buildableCount },
        { key: "designations", label: "SSSI / AONB / Land", count: designationCount },
        { key: "flood", label: "Flood Zone 2/3", count: floodCount },
        { key: "alc", label: "ALC 1 / 2", count: alcCount },
      ],
    },
    {
      title: "Civil",
      rows: [
        { key: "setbacks", label: "Setbacks", count: null, alwaysEnabled: true },
        { key: "sunpath", label: "Sun path", count: null, alwaysEnabled: true },
      ],
    },
  ];

  return (
    <div
      style={{
        position: "absolute",
        top: 12,
        right: 12,
        width: 226,
        background: "rgba(15,23,42,0.92)",
        color: "#e2e8f0",
        borderRadius: 10,
        padding: "10px 12px",
        zIndex: 5,
        fontFamily: '"DM Sans", sans-serif',
        fontSize: 11,
        backdropFilter: "blur(8px)",
        boxShadow: "0 6px 20px rgba(0,0,0,0.4)",
      }}
    >
      {groups.map((g) => (
        <div key={g.title} style={{ marginBottom: 6 }}>
          <div
            style={{
              fontSize: 9,
              letterSpacing: 0.6,
              textTransform: "uppercase",
              color: "#94a3b8",
              fontWeight: 700,
              marginBottom: 4,
            }}
          >
            {g.title}
          </div>
          {g.rows.map((r) => (
            <label
              key={r.key}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "3px 0",
                cursor: "pointer",
                opacity: r.alwaysEnabled || r.count > 0 ? 1 : 0.5,
              }}
            >
              <input
                type="checkbox"
                checked={!!toggles[r.key]}
                onChange={(e) => onToggle(r.key, e.target.checked)}
                disabled={!r.alwaysEnabled && r.count === 0}
                style={{ accentColor: "#f5b731" }}
              />
              <span style={{ flex: 1 }}>{r.label}</span>
              {r.count != null && (
                <span
                  style={{
                    fontSize: 9,
                    color: r.count > 0 ? "#fbbf24" : "#64748b",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {r.count}
                </span>
              )}
            </label>
          ))}
        </div>
      ))}
    </div>
  );
}

export default DesignOverlayTogglePanel;
