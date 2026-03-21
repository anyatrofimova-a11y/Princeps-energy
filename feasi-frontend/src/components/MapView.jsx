import React, { useEffect, useRef, useCallback } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { Protocol } from "pmtiles";
import { getTentativeGuides, getModifyGuides, getCursor } from "../lib/draw-modes";

mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN || "";
import { useSite } from "../SiteContext";
import api from "../services/api";
import electricityZonesGeoJSON from "../data/electricity-zones.json";

const PROXY = "pmtiles://http://localhost:3000/pmtiles-proxy";

let protocolAdded = false;

// Colour schemes for EPC layer fields (from PBCC datasets.js)
const EPC_COLOURS = {
  // Zone categorical fields
  zones_match: {
    modal_age: ["pre1900","#9e0142","19001929","#d53e4f","19301949","#f46d43","19501966","#fdae61","19671975","#fee08b","19761982","#ffffbf","19831990","#e6f598","19911995","#abdda4","19962002","#66c2a5","20032006","#3288bd","20072011","#5e4fa2","20122021","#934fa2","post2022","#c259a7","#888"],
    modal_wall: ["verygood","#2c7bb6","good","#abd9e9","average","#ffffbf","poor","#fdae61","verypoor","#d7191c","#888"],
    modal_roof: ["verygood","#2c7bb6","good","#abd9e9","average","#ffffbf","poor","#fdae61","verypoor","#d7191c","above","#4d9221","#888"],
    modal_heat: ["verygood","#2c7bb6","good","#abd9e9","average","#ffffbf","poor","#fdae61","verypoor","#d7191c","#888"],
    modal_window: ["verygood","#2c7bb6","good","#abd9e9","average","#ffffbf","poor","#fdae61","verypoor","#d7191c","#888"],
    modal_mainheat: ["community","#377eb8","gasboiler","#e41a1c","heatpump","#4daf4a","oilboiler","#984ea3","roomheater","#ffff33","storageheater","#ff7f00","#888"],
    modal_mainfuel: ["biomass","#4daf4a","electric","#377eb8","lpg","#ff7f00","mainsgas","#e41a1c","oil","#984ea3","#888"],
    modal_floord: ["below","#225ea8","solidinsulated","#b2e2e2","solidlimitedinsulated","#66c2a4","soliduninsulated","#238b45","suspendedlimitedinsulated","#df65b0","suspendeduninsulated","#ce1256","#888"],
    modal_type: ["flat","#e31a1c","house_detached","#c2e699","house_semi","#78c679","house_endterrace","#31a354","house_midterrace","#006837","bungalow_detached","#fbb4b9","bungalow_semi","#f768a1","bungalow_endterrace","#c51b8a","bungalow_midterrace","#7a0177","maisonette","#1f78b4","parkhome","#fa7c00","#888"],
  },
  // Zone interpolate fields
  zones_interp: {
    epc_score_avg: [0,"#d73027",50,"#fc8d59",55,"#fee08b",60,"#ffffbf",65,"#d9ef8b",70,"#91cf60",80,"#1a9850"],
    floor_area_avg: [0,"#4d9221",40,"#7fbc41",60,"#b8e186",80,"#e6f5d0",100,"#fde0ef",120,"#f1b6da",140,"#de77ae",160,"#c51b7d"],
    percent_EPC: [0,"#ffffb2",30,"#fed976",50,"#feb24c",60,"#fd8d3c",70,"#fc4e2a",80,"#e31a1c",90,"#b10026"],
  },
  // Domestic EPC categorical
  epc_dom_match: {
    cur_rate: ["A","#0e7e58","B","#2aa45b","C","#8cbc42","D","#f6cc15","E","#f2a867","F","#f17e23","G","#e31d3e","#999"],
    b_type: ["Detached","#1f78b4","Semi-Detached","#33a02c","Mid-Terrace","#e31a1c","Enclosed Mid-Terrace","#ff7f00","End-Terrace","#6a3d9a","Enclosed End-Terrace","#b15928","#999"],
    p_type: ["Flat","#e31a1c","House","#33a02c","Maisonette","#1f78b4","Bungalow","#6a3d9a","Park home","#ff7f00","#999"],
    age: ["before 1900","#9e0142","1900-1929","#d53e4f","1930-1949","#f46d43","1950-1966","#fdae61","1967-1975","#fee08b","1976-1982","#ffffbf","1983-1990","#e6f598","1991-1995","#abdda4","1996-2002","#66c2a5","2003-2006","#3288bd","2007-2011","#5e4fa2","2012-2021","#934fa2","2022 onwards","#c259a7","#999"],
    floor_ee: ["Very Good","#2c7bb6","Good","#abd9e9","Average","#ffffbf","Poor","#fdae61","Very Poor","#d7191c","#999"],
    water_ee: ["Very Good","#2c7bb6","Good","#abd9e9","Average","#ffffbf","Poor","#fdae61","Very Poor","#d7191c","#999"],
    wind_ee: ["Very Good","#2c7bb6","Good","#abd9e9","Average","#ffffbf","Poor","#fdae61","Very Poor","#d7191c","#999"],
    wall_ee: ["Very Good","#2c7bb6","Good","#abd9e9","Average","#ffffbf","Poor","#fdae61","Very Poor","#d7191c","#999"],
    roof_ee: ["Very Good","#2c7bb6","Good","#abd9e9","Average","#ffffbf","Poor","#fdae61","Very Poor","#d7191c","#999"],
    heat_ee: ["Very Good","#2c7bb6","Good","#abd9e9","Average","#ffffbf","Poor","#fdae61","Very Poor","#d7191c","#999"],
    con_ee: ["Very Good","#2c7bb6","Good","#abd9e9","Average","#ffffbf","Poor","#fdae61","Very Poor","#d7191c","#999"],
    light_ee: ["Very Good","#2c7bb6","Good","#abd9e9","Average","#ffffbf","Poor","#fdae61","Very Poor","#d7191c","#999"],
    sol_wat: ["yes","#fdae61","no","#2c7bb6","#999"],
  },
  // Domestic EPC interpolate fields
  epc_dom_interp: {
    year: [2014,"#e31d3e",2016,"#f17e23",2018,"#f6cc15",2020,"#f2a867",2022,"#8cbc42",2024,"#0e7e58"],
    area: [0,"#4d9221",40,"#7fbc41",60,"#b8e186",80,"#e6f5d0",100,"#fde0ef",120,"#f1b6da",140,"#de77ae",160,"#c51b7d"],
  },
  // Non-domestic
  epc_nondom_match: {
    band: ["A","#0e7e58","B","#2aa45b","C","#8cbc42","D","#f6cc15","E","#f2a867","F","#f17e23","G","#e31d3e","#999"],
    transaction: ["Mandatory issue (Display in public building)","#1f78b4","Mandatory issue (Marketed sale)","#33a02c","Mandatory issue (Non-marketed sale)","#e31a1c","Mandatory issue (Property on construction)","#ff7f00","Mandatory issue (Property to let)","#6a3d9a","Voluntary (No legal requirement for an EPC)","#b15928","Voluntary re-issue (A valid EPC is already lodged)","#ffff99","#999"],
  },
  epc_nondom_interp: {
    year: [2014,"#e31d3e",2016,"#f17e23",2018,"#f6cc15",2020,"#f2a867",2022,"#8cbc42",2024,"#0e7e58"],
    area: [0,"#4d9221",40,"#7fbc41",60,"#b8e186",80,"#e6f5d0",100,"#fde0ef",120,"#f1b6da",140,"#de77ae",160,"#c51b7d"],
  },
  // Postcodes
  postcodes_match: {
    combined: ["A+","#313695","A","#4575b4","A-","#4575b4","B+","#74add1","B","#abd9e9","B-","#abd9e9","C+","#e0f3f8","C","#e0f3f8","C-","#ffffbf","D+","#ffffbf","D","#fee090","D-","#fee090","E+","#fdae61","E","#fdae61","E-","#f46d43","F+","#d73027","F","#d73027","F-","#a50026","#000"],
    gas: ["A+","#313695","A","#4575b4","A-","#4575b4","B+","#74add1","B","#abd9e9","B-","#abd9e9","C+","#e0f3f8","C","#e0f3f8","C-","#ffffbf","D+","#ffffbf","D","#fee090","D-","#fee090","E+","#fdae61","E","#fdae61","E-","#f46d43","F+","#d73027","F","#d73027","F-","#a50026","#000"],
    elec: ["A+","#313695","A","#4575b4","A-","#4575b4","B+","#74add1","B","#abd9e9","B-","#abd9e9","C+","#e0f3f8","C","#e0f3f8","C-","#ffffbf","D+","#ffffbf","D","#fee090","D-","#fee090","E+","#fdae61","E","#fdae61","E-","#f46d43","F+","#d73027","F","#d73027","F-","#a50026","#000"],
  },
};

function makeColourExpr(field, matchMap, interpMap) {
  if (interpMap && interpMap[field]) {
    return ["interpolate", ["linear"], ["coalesce", ["get", field], 0], ...interpMap[field]];
  }
  if (matchMap && matchMap[field]) {
    return ["match", ["get", field], ...matchMap[field]];
  }
  return "#888";
}

// Asset type colour map for energy infrastructure
const ASSET_COLOURS = {
  nuclear: "#e53935",        // red
  gas: "#ff8f00",            // amber
  biomass: "#8d6e63",        // brown
  wind: "#00b0ff",           // cyan
  solar: "#fdd835",          // yellow
  hydro: "#1565c0",          // deep blue
  battery: "#7cb342",        // green
  interconnector: "#ab47bc", // purple
  substation: "#78909c",     // blue-grey
};

const EMPTY_FC = { type: "FeatureCollection", features: [] };

export default function MapView({ slopeOpacity = 0.6, layers = {}, pickMode = false, onPick, pickedLocation, onZoneClick, epcFields = {},
  drawState, onDrawClick, onDrawDoubleClick, onDrawMouseMove, onDrawSelectFeature, onDrawDragVertex, chatLayers = [], onMapReady }) {
  const { stabilityData, gridHighlightSub } = useSite();
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const [mapReady, setMapReady] = React.useState(false);

  useEffect(() => {
    if (!protocolAdded) {
      try {
        const protocol = new Protocol();
        if (typeof mapboxgl.addProtocol === "function") {
          mapboxgl.addProtocol("pmtiles", protocol.tile);
        }
        // mapbox-gl v3 doesn't support addProtocol — PMTiles layers will be skipped
      } catch (e) {
        console.warn("PMTiles protocol registration skipped:", e.message);
      }
      protocolAdded = true;
    }

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        glyphs: "mapbox://fonts/mapbox/{fontstack}/{range}.pbf",
        sprite: "mapbox://sprites/mapbox/dark-v11",
        sources: {
          "carto-dark": {
            type: "raster",
            tiles: ["https://basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}@2x.png"],
            tileSize: 256, maxzoom: 20,
            attribution: "© CartoDB",
          },
          "carto-labels": {
            type: "raster",
            tiles: ["https://basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}@2x.png"],
            tileSize: 256, maxzoom: 20,
          },
        },
        layers: [
          { id: "carto-base", type: "raster", source: "carto-dark" },
        ],
      },
      center: [-1.5, 52.5],
      zoom: 7,
      pitch: 45,
      bearing: -10,
      maxPitch: 85,
    });

    mapRef.current = map;

    map.on("error", (e) => {
      console.warn("Mapbox error:", e.error?.message || e.message || e);
    });

    const setupMap = () => {
      if (map._setupDone) return;
      map._setupDone = true;
      console.log("[MapView] running setup");
      // safe() isolates each section so one failure doesn't kill everything
      const safe = (label, fn) => { try { fn(); } catch(e) { console.error(`[MapView] ${label}:`, e.message, e); } };

      safe("terrain", () => {
        map.addSource("terrainSource", { type: "raster-dem", url: "mapbox://mapbox.mapbox-terrain-dem-v1", tileSize: 512, maxzoom: 14 });
        map.addSource("hillshadeSource", { type: "raster-dem", url: "mapbox://mapbox.mapbox-terrain-dem-v1", tileSize: 512, maxzoom: 14 });
        map.addLayer({
          id: "hillshade", type: "hillshade", source: "hillshadeSource",
          paint: { "hillshade-shadow-color": "#8a9a8a", "hillshade-highlight-color": "#ffffff", "hillshade-accent-color": "#2e7d32", "hillshade-illumination-anchor": "map", "hillshade-exaggeration": 0.4 },
        });
        map.setTerrain({ source: "terrainSource", exaggeration: 2.0 });
      });

      safe("sky+fog", () => {
        map.addLayer({
          id: "sky", type: "sky",
          paint: { "sky-type": "atmosphere", "sky-atmosphere-sun": [0, 15], "sky-atmosphere-sun-intensity": 5, "sky-atmosphere-color": "#88ccff" },
        });
        map.setFog({
          range: [1, 12], color: "rgba(200, 210, 230, 0.9)", "high-color": "#add8e6",
          "space-color": "#0b1026", "horizon-blend": 0.05, "star-intensity": 0.1,
        });
      });

      // Expose map instance to parent
      if (onMapReady) onMapReady(map);

      safe("icons+patterns", () => {
        const SITE_ICONS = [
          "substation", "exchange", "hazard", "optimal-site",
          "power-source", "flight-path", "fibre-pop", "flood-zone",
        ];
        for (const name of SITE_ICONS) {
          map.loadImage(`/icons/${name}.svg`, (err, img) => {
            if (!err && img && !map.hasImage(`icon-${name}`)) {
              map.addImage(`icon-${name}`, img, { sdf: false });
            }
          });
        }

        const makeHatch = (color, spacing = 10, width = 1.5) => {
          const size = spacing * 2;
          const canvas = document.createElement("canvas");
          canvas.width = size; canvas.height = size;
          const ctx = canvas.getContext("2d");
          ctx.strokeStyle = color;
          ctx.lineWidth = width;
          ctx.beginPath();
          ctx.moveTo(0, size); ctx.lineTo(size, 0);
          ctx.moveTo(-size / 2, size / 2); ctx.lineTo(size / 2, -size / 2);
          ctx.moveTo(size / 2, size * 1.5); ctx.lineTo(size * 1.5, size / 2);
          ctx.stroke();
          return ctx.getImageData(0, 0, size, size);
        };
        map.addImage("hatch-blue", makeHatch("#4a6fa5", 10, 1.5), { pixelRatio: 2 });
        map.addImage("hatch-red", makeHatch("#e53935", 10, 1.5), { pixelRatio: 2 });
        map.addImage("hatch-green", makeHatch("#2e7d32", 10, 1.5), { pixelRatio: 2 });
        map.addImage("hatch-amber", makeHatch("#ff8f00", 10, 1.5), { pixelRatio: 2 });
        map.addImage("hatch-grey", makeHatch("#78909c", 10, 1.5), { pixelRatio: 2 });

        const makeCrossHatch = (color, spacing = 10, width = 1) => {
          const size = spacing * 2;
          const canvas = document.createElement("canvas");
          canvas.width = size; canvas.height = size;
          const ctx = canvas.getContext("2d");
          ctx.strokeStyle = color;
          ctx.lineWidth = width;
          ctx.beginPath();
          ctx.moveTo(0, size); ctx.lineTo(size, 0);
          ctx.moveTo(0, 0); ctx.lineTo(size, size);
          ctx.stroke();
          return ctx.getImageData(0, 0, size, size);
        };
        map.addImage("crosshatch-red", makeCrossHatch("#e53935", 8, 1.5), { pixelRatio: 2 });
        map.addImage("crosshatch-blue", makeCrossHatch("#1565c0", 8, 1.5), { pixelRatio: 2 });
      });

      // Carto dark labels (above hillshade, below data layers)
      safe("labels", () => map.addLayer({ id: "base-labels", type: "raster", source: "carto-labels" }));

      // ── ESRI Aerial imagery + energy assets ──
      safe("aerial+assets", () => {
      map.addSource("esri-imagery", {
        type: "raster",
        tiles: ["https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
        tileSize: 256, maxzoom: 19,
        attribution: "Esri, Maxar, Earthstar Geographics",
      });
      map.addLayer({
        id: "aerial-layer", type: "raster", source: "esri-imagery",
        paint: { "raster-opacity": 0.85 },
        layout: { visibility: layers.aerial ? "visible" : "none" },
      });

      // ── Real energy infrastructure assets ──
      map.addSource("energy-assets", {
        type: "geojson",
        data: EMPTY_FC,
      });

      // Fetch real energy assets from backend
      api.analytics.energyAssets().then((data) => {
        if (data && data.features) {
          const src = map.getSource("energy-assets");
          if (src) src.setData(data);
        }
      });

      // Energy asset circles — colour by type, size by capacity
      map.addLayer({
        id: "energy-assets-circle",
        type: "circle",
        source: "energy-assets",
        paint: {
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            5, ["interpolate", ["linear"], ["coalesce", ["get", "capacity_mw"], 0], 0, 2, 100, 4, 1000, 7, 3000, 10],
            10, ["interpolate", ["linear"], ["coalesce", ["get", "capacity_mw"], 0], 0, 4, 100, 8, 1000, 14, 3000, 20],
            15, ["interpolate", ["linear"], ["coalesce", ["get", "capacity_mw"], 0], 0, 6, 100, 12, 1000, 22, 3000, 32],
          ],
          "circle-color": [
            "match", ["get", "asset_type"],
            "nuclear", ASSET_COLOURS.nuclear,
            "gas", ASSET_COLOURS.gas,
            "biomass", ASSET_COLOURS.biomass,
            "wind", ASSET_COLOURS.wind,
            "solar", ASSET_COLOURS.solar,
            "hydro", ASSET_COLOURS.hydro,
            "battery", ASSET_COLOURS.battery,
            "interconnector", ASSET_COLOURS.interconnector,
            "substation", ASSET_COLOURS.substation,
            "#888",
          ],
          "circle-opacity": 0.82,
          "circle-blur": 0.2,
          "circle-stroke-width": [
            "match", ["get", "echelon"],
            "division", 3,
            "brigade", 2.5,
            "battalion", 2,
            "company", 1.5,
            1,
          ],
          "circle-stroke-color": [
            "match", ["get", "asset_type"],
            "nuclear", "rgba(229,57,53,0.5)",
            "gas", "rgba(255,143,0,0.5)",
            "biomass", "rgba(141,110,99,0.5)",
            "wind", "rgba(0,176,255,0.5)",
            "solar", "rgba(253,216,53,0.5)",
            "hydro", "rgba(21,101,192,0.5)",
            "battery", "rgba(124,179,66,0.5)",
            "interconnector", "rgba(171,71,188,0.5)",
            "substation", "rgba(120,144,156,0.5)",
            "rgba(136,136,136,0.5)",
          ],
        },
        layout: { visibility: layers.environment ? "visible" : "none" },
      });

      // Echelon symbol overlay (XX, X, II, I, ...)
      map.addLayer({
        id: "energy-assets-echelon",
        type: "symbol",
        source: "energy-assets",
        filter: ["!=", ["get", "asset_type"], "substation"],
        paint: {
          "text-color": "#fff",
          "text-halo-color": "rgba(0,0,0,0.6)",
          "text-halo-width": 1,
        },
        layout: {
          "text-field": ["get", "echelon_symbol"],
          "text-font": ["Noto Sans Bold"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 5, 7, 10, 10, 15, 14],
          "text-allow-overlap": true,
          visibility: layers.environment ? "visible" : "none",
        },
        minzoom: 6,
      });

      // Asset name + capacity labels
      map.addLayer({
        id: "energy-assets-labels",
        type: "symbol",
        source: "energy-assets",
        filter: ["!=", ["get", "asset_type"], "substation"],
        paint: {
          "text-color": "#333",
          "text-halo-color": "rgba(255, 255, 255, 0.9)",
          "text-halo-width": 1.5,
        },
        layout: {
          "text-field": ["concat", ["get", "name"], "\n", ["get", "capacity_mw"], " MW"],
          "text-font": ["Noto Sans Regular"],
          "text-size": 10,
          "text-offset": [0, 1.8],
          "text-anchor": "top",
          visibility: layers.environment ? "visible" : "none",
        },
        minzoom: 9,
      });

      // Substation labels (smaller, only at higher zoom)
      map.addLayer({
        id: "energy-assets-sub-labels",
        type: "symbol",
        source: "energy-assets",
        filter: ["==", ["get", "asset_type"], "substation"],
        paint: {
          "text-color": "#546e7a",
          "text-halo-color": "rgba(255, 255, 255, 0.8)",
          "text-halo-width": 1,
        },
        layout: {
          "text-field": ["concat", ["get", "name"], "\n", ["get", "voltage_kv"], " kV"],
          "text-font": ["Noto Sans Regular"],
          "text-size": 9,
          "text-offset": [0, 1.5],
          "text-anchor": "top",
          visibility: layers.environment ? "visible" : "none",
        },
        minzoom: 11,
      });

      // Energy asset click popup
      map.on("click", "energy-assets-circle", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        const status = p.status ? `<br/>Status: ${p.status}` : "";
        const operator = p.operator ? `<br/>Operator: ${p.operator}` : "";
        const voltage = p.voltage_kv ? `<br/>Voltage: ${p.voltage_kv} kV` : "";
        const echelon = p.echelon_symbol ? ` <span style="font-weight:bold;opacity:0.6">[${p.echelon_symbol}]</span>` : "";
        new mapboxgl.Popup({ maxWidth: "260px" })
          .setLngLat(e.lngLat)
          .setHTML(
            `<div style="font-size:12px">` +
            `<strong>${p.name}</strong>${echelon}<br/>` +
            `Type: ${p.asset_type}${p.subtype ? ` (${p.subtype})` : ""}<br/>` +
            `Capacity: ${p.capacity_mw} MW` +
            `${voltage}${operator}${status}` +
            `</div>`
          )
          .addTo(map);
      });

      // Slope raster from our backend
      map.addSource("slope-raster", {
        type: "raster",
        tiles: ["/tiles/slope/{z}/{x}/{y}.png"],
        tileSize: 256,
      });
      map.addLayer({
        id: "slope-tiles",
        type: "raster",
        source: "slope-raster",
        paint: { "raster-opacity": slopeOpacity },
        layout: { visibility: layers.slope ? "visible" : "none" },
      });
      }); // end safe("aerial+assets")

      // PMTiles vector overlays — wrapped in try/catch because mapbox-gl v3
      // removed addProtocol, so pmtiles:// URLs may fail
      try {
      map.addSource("pbcc-carbon", {
        type: "vector",
        url: `${PROXY}/pbcc.pmtiles`,
      });
      map.addLayer({
        id: "carbon-fill",
        type: "fill",
        source: "pbcc-carbon",
        "source-layer": "pbcc",
        paint: {
          "fill-color": [
            "interpolate", ["linear"],
            ["coalesce", ["get", "total_co2"], 0],
            0, "rgba(255,255,255,0)",
            50, "#fff9c4",
            200, "#ffcc02",
            500, "#f44336",
            1000, "#b71c1c",
          ],
          "fill-opacity": 0.55,
        },
        layout: { visibility: layers.carbon ? "visible" : "none" },
      });
      map.addLayer({
        id: "carbon-line",
        type: "line",
        source: "pbcc-carbon",
        "source-layer": "pbcc",
        paint: { "line-color": "#e91e63", "line-width": 0.4, "line-opacity": 0.4 },
        layout: { visibility: layers.carbon ? "visible" : "none" },
      });

      // Local Authority boundaries
      map.addSource("pbcc-la", {
        type: "vector",
        url: `${PROXY}/la.pmtiles`,
      });
      map.addLayer({
        id: "la-line",
        type: "line",
        source: "pbcc-la",
        "source-layer": "la",
        paint: { "line-color": "#ff9800", "line-width": 2, "line-opacity": 0.7 },
        layout: { visibility: layers.la ? "visible" : "none" },
      });
      map.addLayer({
        id: "la-fill",
        type: "fill",
        source: "pbcc-la",
        "source-layer": "la",
        paint: { "fill-color": "#ff9800", "fill-opacity": 0.06 },
        layout: { visibility: layers.la ? "visible" : "none" },
      });

      // Transport overlay
      map.addSource("pbcc-transport", {
        type: "vector",
        url: `${PROXY}/transport.pmtiles`,
      });
      map.addLayer({
        id: "transport-fill",
        type: "fill",
        source: "pbcc-transport",
        "source-layer": "transport",
        paint: { "fill-color": "#00bcd4", "fill-opacity": 0.25 },
        layout: { visibility: layers.transport ? "visible" : "none" },
      });
      map.addLayer({
        id: "transport-line",
        type: "line",
        source: "pbcc-transport",
        "source-layer": "transport",
        paint: { "line-color": "#00838f", "line-width": 0.5, "line-opacity": 0.5 },
        layout: { visibility: layers.transport ? "visible" : "none" },
      });

      // ── Retrofit / EPC layers ──

      // Neighbourhood zones
      map.addSource("retrofit-zones", {
        type: "vector",
        url: `${PROXY}/zones_retrofit_20251124.pmtiles`,
      });
      map.addLayer({
        id: "zones-fill",
        type: "fill",
        source: "retrofit-zones",
        "source-layer": "zones",
        paint: {
          "fill-color": [
            "interpolate", ["linear"],
            ["coalesce", ["get", "epc_score_avg"], 55],
            0, "#d73027", 50, "#fc8d59", 55, "#fee08b",
            60, "#ffffbf", 65, "#d9ef8b", 70, "#91cf60", 80, "#1a9850",
          ],
          "fill-opacity": 0.5,
          "fill-outline-color": "rgba(0,0,0,0.2)",
        },
        layout: { visibility: layers.epcZones ? "visible" : "none" },
      });

      // Domestic EPC points
      map.addSource("epc-dom", {
        type: "vector",
        url: `${PROXY}/epc_dom_20251124.pmtiles`,
      });
      map.addLayer({
        id: "epc-dom-circles",
        type: "circle",
        source: "epc-dom",
        "source-layer": "epc_dom",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 1.5, 14, 4, 22, 20],
          "circle-color": [
            "match", ["get", "cur_rate"],
            "A", "#0e7e58", "B", "#2aa45b", "C", "#8cbc42",
            "D", "#f6cc15", "E", "#f2a867", "F", "#f17e23", "G", "#e31d3e",
            "#999",
          ],
          "circle-opacity": 0.8,
          "circle-stroke-width": 0.3,
          "circle-stroke-color": "#333",
        },
        layout: { visibility: layers.epcDom ? "visible" : "none" },
        minzoom: 12,
      });

      // Non-domestic EPC points
      map.addSource("epc-nondom", {
        type: "vector",
        url: `${PROXY}/epc_nondom.pmtiles`,
      });
      map.addLayer({
        id: "epc-nondom-circles",
        type: "circle",
        source: "epc-nondom",
        "source-layer": "epc_nondom",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 2, 14, 5, 22, 22],
          "circle-color": [
            "match", ["get", "band"],
            "A", "#0e7e58", "B", "#2aa45b", "C", "#8cbc42",
            "D", "#f6cc15", "E", "#f2a867", "F", "#f17e23", "G", "#e31d3e",
            "#999",
          ],
          "circle-opacity": 0.8,
          "circle-stroke-width": 0.5,
          "circle-stroke-color": "#555",
        },
        layout: { visibility: layers.epcNondom ? "visible" : "none" },
        minzoom: 12,
      });

      // Postcode gas & electricity emissions
      map.addSource("retrofit-postcodes", {
        type: "vector",
        url: `${PROXY}/postcodes.pmtiles`,
      });
      map.addLayer({
        id: "postcodes-fill",
        type: "fill",
        source: "retrofit-postcodes",
        "source-layer": "postcodes",
        paint: {
          "fill-color": [
            "match", ["get", "combined"],
            "A+", "#313695", "A", "#4575b4", "A-", "#4575b4",
            "B+", "#74add1", "B", "#abd9e9", "B-", "#abd9e9",
            "C+", "#e0f3f8", "C", "#e0f3f8", "C-", "#ffffbf",
            "D+", "#ffffbf", "D", "#fee090", "D-", "#fee090",
            "E+", "#fdae61", "E", "#fdae61", "E-", "#f46d43",
            "F+", "#d73027", "F", "#d73027", "F-", "#a50026",
            "#000",
          ],
          "fill-opacity": 0.6,
          "fill-outline-color": "rgba(0,0,0,0.1)",
        },
        layout: { visibility: layers.postcodes ? "visible" : "none" },
      });
      } catch (pmtilesErr) {
        console.warn("PMTiles vector layers unavailable (mapbox-gl v3):", pmtilesErr.message);
      }

      // ── Grid flow network (FlowmapBlue-style) — on top of all data layers ──
      safe("grid+osm+layers", () => {
      map.addSource("grid-flow-lines", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("grid-flow-nodes", { type: "geojson", data: { type: "FeatureCollection", features: [] } });

      // Live national grid sources
      map.addSource("grid-live-interconnectors", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("grid-live-generation", { type: "geojson", data: { type: "FeatureCollection", features: [] } });

      // OSM power infrastructure sources
      map.addSource("osm-power-lines", { type: "geojson", data: EMPTY_FC });
      map.addSource("osm-power-substations", { type: "geojson", data: EMPTY_FC });
      map.addSource("osm-power-towers", { type: "geojson", data: EMPTY_FC });
      map.addSource("osm-power-generators", { type: "geojson", data: EMPTY_FC });
      map.addSource("osm-power-plants", { type: "geojson", data: EMPTY_FC });

      // NGED CIM substations source
      map.addSource("nged-substations", { type: "geojson", data: EMPTY_FC });

      // ESO TEC + REPD sources
      map.addSource("eso-tec-projects", { type: "geojson", data: EMPTY_FC });
      map.addSource("repd-projects", { type: "geojson", data: EMPTY_FC });

      // Grid connection capacity sources
      map.addSource("gc-capacity-subs", { type: "geojson", data: EMPTY_FC });
      map.addSource("gc-grid-lines", { type: "geojson", data: EMPTY_FC });
      map.addSource("gc-highlight-sub", { type: "geojson", data: EMPTY_FC });

      // Demand GSP source
      map.addSource("demand-gsps", { type: "geojson", data: EMPTY_FC });

      // Constraint overlay + queue depth sources
      map.addSource("grid-constraints", { type: "geojson", data: EMPTY_FC });
      map.addSource("queue-depth", { type: "geojson", data: EMPTY_FC });
      // Land registry parcels source
      map.addSource("land-parcels", { type: "geojson", data: EMPTY_FC });
      // Highlight pulse marker for selected land listing
      map.addSource("land-highlight", { type: "geojson", data: EMPTY_FC });

      // DC infrastructure sources
      map.addSource("dc-capacity", { type: "geojson", data: EMPTY_FC });
      map.addSource("dc-fibre", { type: "geojson", data: EMPTY_FC });
      map.addSource("dc-ixp", { type: "geojson", data: EMPTY_FC });

      // Flow glow (wide blurred line — FlowmapBlue cyan style)
      map.addLayer({
        id: "grid-flow-glow",
        type: "line",
        source: "grid-flow-lines",
        paint: {
          "line-color": ["interpolate", ["linear"], ["get", "utilization"],
            0, "#00bcd4", 0.4, "#0097a7", 0.7, "#e65100", 0.9, "#c62828"],
          "line-width": ["interpolate", ["linear"], ["zoom"], 5, 6, 7, 12, 10, 20, 14, 30],
          "line-blur": 6,
          "line-opacity": 0.5,
        },
        layout: { visibility: "visible", "line-cap": "round" },
      });

      // Flow core (solid, width by flow_mw)
      map.addLayer({
        id: "grid-flow-core",
        type: "line",
        source: "grid-flow-lines",
        paint: {
          "line-color": ["interpolate", ["linear"], ["get", "utilization"],
            0, "#00e5ff", 0.4, "#00bcd4", 0.7, "#ff9800", 0.9, "#f44336"],
          "line-width": ["interpolate", ["linear"], ["get", "flow_mw"],
            0, 0.5, 50, 1.5, 150, 2.5, 400, 4, 700, 6],
          "line-opacity": 0.85,
        },
        layout: { visibility: "visible", "line-cap": "round" },
      });

      // Flow dash (animated)
      map.addLayer({
        id: "grid-flow-dash",
        type: "line",
        source: "grid-flow-lines",
        paint: {
          "line-color": "rgba(255,255,255,0.4)",
          "line-width": 1,
          "line-dasharray": [0, 4, 3],
        },
        layout: { visibility: "visible", "line-cap": "round" },
      });

      // Live interconnector flow lines (glow)
      map.addLayer({
        id: "grid-live-ic-glow",
        type: "line",
        source: "grid-live-interconnectors",
        paint: {
          "line-color": ["match", ["get", "direction"], "import", "#1565c0", "#e65100"],
          "line-width": ["interpolate", ["linear"], ["get", "abs_flow_mw"], 0, 4, 1000, 14, 3000, 22],
          "line-blur": 6,
          "line-opacity": 0.3,
        },
        layout: { visibility: "visible", "line-cap": "round" },
      });

      // Live interconnector flow lines (core)
      map.addLayer({
        id: "grid-live-ic-core",
        type: "line",
        source: "grid-live-interconnectors",
        paint: {
          "line-color": ["match", ["get", "direction"], "import", "#1565c0", "#e65100"],
          "line-width": ["interpolate", ["linear"], ["get", "abs_flow_mw"], 0, 2, 1000, 5, 3000, 9],
          "line-opacity": 0.85,
        },
        layout: { visibility: "visible", "line-cap": "round" },
      });

      // Live interconnector dash (animated)
      map.addLayer({
        id: "grid-live-ic-dash",
        type: "line",
        source: "grid-live-interconnectors",
        paint: {
          "line-color": "rgba(255,255,255,0.5)",
          "line-width": 2,
          "line-dasharray": [0, 4, 3],
        },
        layout: { visibility: "visible", "line-cap": "round" },
      });

      // Live interconnector labels
      map.addLayer({
        id: "grid-live-ic-labels",
        type: "symbol",
        source: "grid-live-interconnectors",
        paint: {
          "text-color": "#1a237e",
          "text-halo-color": "rgba(255,255,255,0.9)",
          "text-halo-width": 1.5,
        },
        layout: {
          "symbol-placement": "line-center",
          "text-field": ["concat", ["get", "flow_mw"], " MW"],
          "text-font": ["Noto Sans Bold"],
          "text-size": 11,
          visibility: "visible",
        },
        minzoom: 5,
      });

      // Live generation bubbles (glow)
      map.addLayer({
        id: "grid-live-gen-glow",
        type: "circle",
        source: "grid-live-generation",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "generation_mw"], 0, 4, 2000, 18, 8000, 35],
          "circle-color": ["match", ["get", "type"],
            "nuclear", "#7b1fa2", "gas", "#d84315", "wind", "#0277bd",
            "solar", "#f9a825", "biomass", "#33691e", "coal", "#424242",
            "hydro", "#00838f", "pumped", "#4527a0", "#757575"],
          "circle-blur": 0.6,
          "circle-opacity": 0.3,
        },
        layout: { visibility: "visible" },
      });

      // Live generation bubbles (core)
      map.addLayer({
        id: "grid-live-gen-circles",
        type: "circle",
        source: "grid-live-generation",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "generation_mw"], 0, 3, 2000, 12, 8000, 24],
          "circle-color": ["match", ["get", "type"],
            "nuclear", "#7b1fa2", "gas", "#d84315", "wind", "#0277bd",
            "solar", "#f9a825", "biomass", "#33691e", "coal", "#424242",
            "hydro", "#00838f", "pumped", "#4527a0", "#757575"],
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "rgba(255,255,255,0.8)",
          "circle-opacity": 0.85,
        },
        layout: { visibility: "visible" },
      });

      // Live generation labels
      map.addLayer({
        id: "grid-live-gen-labels",
        type: "symbol",
        source: "grid-live-generation",
        paint: {
          "text-color": "#212121",
          "text-halo-color": "rgba(255,255,255,0.9)",
          "text-halo-width": 1.5,
        },
        layout: {
          "text-field": ["concat", ["get", "type"], "\n", ["get", "generation_mw"], " MW"],
          "text-font": ["Noto Sans Regular"],
          "text-size": 10,
          "text-offset": [0, 2.2],
          visibility: "visible",
        },
        minzoom: 6,
      });

      // ── Agile pricing regional heatmap ──
      map.addSource("agile-pricing", { type: "geojson", data: { type: "FeatureCollection", features: [] } });

      // Price region glow (large heatmap-style circles)
      map.addLayer({
        id: "agile-price-glow",
        type: "circle",
        source: "agile-pricing",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 40, 7, 80, 10, 120],
          "circle-color": ["interpolate", ["linear"], ["get", "price_pence"],
            0, "#1b5e20", 10, "#4caf50", 15, "#8bc34a", 20, "#ffeb3b",
            30, "#ff9800", 40, "#f44336", 60, "#b71c1c"],
          "circle-blur": 0.9,
          "circle-opacity": 0.35,
        },
        layout: { visibility: "none" },
      });

      // Price region labels
      map.addLayer({
        id: "agile-price-labels",
        type: "symbol",
        source: "agile-pricing",
        paint: {
          "text-color": "#212121",
          "text-halo-color": "rgba(255,255,255,0.9)",
          "text-halo-width": 1.5,
        },
        layout: {
          "text-field": ["concat", ["get", "label"], "\n", ["get", "price_pence"], "p/kWh"],
          "text-font": ["Noto Sans Bold"],
          "text-size": 12,
          visibility: "none",
        },
        minzoom: 5,
      });

      // Price click popup
      map.on("click", "agile-price-glow", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        new mapboxgl.Popup({ maxWidth: "220px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${p.label}</strong><br/>Agile price: <strong>${p.price_pence}p/kWh</strong><br/>Category: ${p.price_category}</div>`)
          .addTo(map);
      });
      map.on("mouseenter", "agile-price-glow", () => { if (!map._pickMode) map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "agile-price-glow", () => { if (!map._pickMode) map.getCanvas().style.cursor = ""; });

      // ── Smart Meter Demand heatmap (Weave) ──
      map.addSource("demand-heatmap", { type: "geojson", data: { type: "FeatureCollection", features: [] } });

      // Demand glow (large blurred circles — magenta heatmap)
      map.addLayer({
        id: "demand-glow",
        type: "circle",
        source: "demand-heatmap",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"],
            5, ["interpolate", ["linear"], ["get", "kwh_per_meter"], 0, 4, 5, 12, 15, 25],
            9, ["interpolate", ["linear"], ["get", "kwh_per_meter"], 0, 8, 5, 25, 15, 50],
          ],
          "circle-color": ["interpolate", ["linear"], ["get", "kwh_per_meter"],
            0, "#7b1fa2", 2, "#ab47bc", 5, "#e040fb", 8, "#ff6d00", 12, "#ff1744"],
          "circle-blur": 0.7,
          "circle-opacity": 0.5,
        },
        layout: { visibility: "none" },
      });

      // Demand circles (solid inner dots)
      map.addLayer({
        id: "demand-circles",
        type: "circle",
        source: "demand-heatmap",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"],
            5, 3,
            9, ["interpolate", ["linear"], ["get", "kwh_per_meter"], 0, 4, 5, 8, 15, 14],
          ],
          "circle-color": ["interpolate", ["linear"], ["get", "kwh_per_meter"],
            0, "#ce93d8", 2, "#ab47bc", 5, "#e040fb", 8, "#ff6d00", 12, "#ff1744"],
          "circle-stroke-width": 1,
          "circle-stroke-color": "rgba(255,255,255,0.6)",
        },
        layout: { visibility: "none" },
        minzoom: 7,
      });

      // Demand labels
      map.addLayer({
        id: "demand-labels",
        type: "symbol",
        source: "demand-heatmap",
        paint: {
          "text-color": "#e040fb",
          "text-halo-color": "rgba(0,0,0,0.8)",
          "text-halo-width": 1.2,
        },
        layout: {
          "text-field": ["concat", ["get", "kwh_per_meter"], " kWh"],
          "text-font": ["Noto Sans Bold"],
          "text-size": 10,
          "text-offset": [0, 1.4],
          visibility: "none",
        },
        minzoom: 9,
      });

      // Demand click popup
      map.on("click", "demand-circles", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        new mapboxgl.Popup({ maxWidth: "260px" })
          .setLngLat(e.lngLat)
          .setHTML(
            `<div style="font-size:12px">` +
            `<strong>${p.name || p.substation_id}</strong><br/>` +
            `DNO: ${p.dno}<br/>` +
            `Total: <strong>${p.total_kwh} kWh</strong><br/>` +
            `Meters: ${p.meter_count}<br/>` +
            `Per meter: <strong>${p.kwh_per_meter} kWh</strong>` +
            `</div>`
          )
          .addTo(map);
      });
      map.on("mouseenter", "demand-circles", () => { if (!map._pickMode) map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "demand-circles", () => { if (!map._pickMode) map.getCanvas().style.cursor = ""; });

      // Fetch demand data
      fetch("/grid/demand-map")
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (data && map.getSource("demand-heatmap")) {
            map.getSource("demand-heatmap").setData(data);
          }
        })
        .catch(() => {});

      // Other geodata layers are lazy-loaded on toggle (see LAZY_RASTER_LAYERS)

      // Node glow (blurred halo — cyan bloom)
      map.addLayer({
        id: "grid-node-glow",
        type: "circle",
        source: "grid-flow-nodes",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"],
            5, ["interpolate", ["linear"], ["get", "demand_mw"], 0, 6, 200, 12, 600, 20],
            8, ["interpolate", ["linear"], ["get", "demand_mw"], 0, 10, 200, 18, 600, 30],
            12, ["interpolate", ["linear"], ["get", "demand_mw"], 0, 14, 200, 26, 600, 42]],
          "circle-color": ["match", ["get", "node_type"], "gsp", "#00e5ff", "#00bcd4"],
          "circle-blur": 0.8,
          "circle-opacity": 0.5,
        },
        layout: { visibility: "visible" },
      });

      // Node circles (solid — visible at all zoom levels)
      map.addLayer({
        id: "grid-node-circles",
        type: "circle",
        source: "grid-flow-nodes",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"],
            5, ["interpolate", ["linear"], ["get", "demand_mw"], 0, 3, 200, 5, 600, 8],
            8, ["interpolate", ["linear"], ["get", "demand_mw"], 0, 4, 200, 7, 600, 12],
            12, ["interpolate", ["linear"], ["get", "demand_mw"], 0, 6, 200, 10, 600, 18]],
          "circle-color": ["match", ["get", "node_type"], "gsp", "#00e5ff", "#26c6da"],
          "circle-stroke-width": 1,
          "circle-stroke-color": "rgba(255,255,255,0.8)",
        },
        layout: { visibility: "visible" },
      });

      // Node labels
      map.addLayer({
        id: "grid-node-labels",
        type: "symbol",
        source: "grid-flow-nodes",
        paint: {
          "text-color": "#006064",
          "text-halo-color": "rgba(255,255,255,0.9)",
          "text-halo-width": 1.5,
        },
        layout: {
          "text-field": ["concat", ["get", "name"], "\n", ["get", "demand_mw"], " MW"],
          "text-font": ["Noto Sans Regular"],
          "text-size": 10,
          "text-offset": [0, 1.8],
          visibility: "visible",
        },
        minzoom: 9,
      });

      // ── OSM Power Infrastructure layers (OpenInfraMap-style) ──
      // Voltage colour ramp matching OpenInfraMap
      const osmVoltageColor = [
        "case",
        [">=", ["coalesce", ["get", "voltage_kv"], 0], 400], "#B54EB2",
        [">=", ["coalesce", ["get", "voltage_kv"], 0], 275], "#C73030",
        [">=", ["coalesce", ["get", "voltage_kv"], 0], 132], "#B55D00",
        [">=", ["coalesce", ["get", "voltage_kv"], 0], 66], "#B59F10",
        [">=", ["coalesce", ["get", "voltage_kv"], 0], 33], "#55B555",
        [">=", ["coalesce", ["get", "voltage_kv"], 0], 11], "#6E97B8",
        "#7A7A85",
      ];

      // Power line glow
      map.addLayer({
        id: "osm-power-line-glow",
        type: "line",
        source: "osm-power-lines",
        paint: {
          "line-color": osmVoltageColor,
          "line-width": ["interpolate", ["linear"], ["zoom"],
            5, ["interpolate", ["linear"], ["coalesce", ["get", "voltage_kv"], 0], 0, 3, 132, 6, 400, 10],
            10, ["interpolate", ["linear"], ["coalesce", ["get", "voltage_kv"], 0], 0, 5, 132, 10, 400, 18],
            14, ["interpolate", ["linear"], ["coalesce", ["get", "voltage_kv"], 0], 0, 8, 132, 16, 400, 28],
          ],
          "line-blur": 5,
          "line-opacity": 0.35,
        },
        layout: { visibility: "none", "line-cap": "round" },
      });

      // Power line core
      map.addLayer({
        id: "osm-power-line-core",
        type: "line",
        source: "osm-power-lines",
        paint: {
          "line-color": osmVoltageColor,
          "line-width": ["interpolate", ["linear"], ["zoom"],
            5, ["interpolate", ["linear"], ["coalesce", ["get", "voltage_kv"], 0], 0, 0.5, 132, 1.5, 400, 3],
            10, ["interpolate", ["linear"], ["coalesce", ["get", "voltage_kv"], 0], 0, 1, 132, 2.5, 400, 5],
            14, ["interpolate", ["linear"], ["coalesce", ["get", "voltage_kv"], 0], 0, 1.5, 132, 4, 400, 7],
          ],
          "line-opacity": 0.85,
        },
        layout: { visibility: "none", "line-cap": "round" },
      });

      // Power line labels (voltage + name at zoom >= 10 for >= 132kV)
      map.addLayer({
        id: "osm-power-line-labels",
        type: "symbol",
        source: "osm-power-lines",
        filter: [">=", ["coalesce", ["get", "voltage_kv"], 0], 132],
        paint: {
          "text-color": osmVoltageColor,
          "text-halo-color": "rgba(255,255,255,0.85)",
          "text-halo-width": 1.5,
        },
        layout: {
          "symbol-placement": "line",
          "text-field": ["concat",
            ["case", ["has", "voltage_kv"],
              ["concat", ["to-string", ["round", ["get", "voltage_kv"]]], "kV"], ""],
            ["case", ["has", "name"], ["concat", " ", ["get", "name"]], ""],
          ],
          "text-font": ["Noto Sans Regular"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 10, 9, 14, 12],
          "text-allow-overlap": false,
          visibility: "none",
        },
        minzoom: 10,
      });

      // Substation circles
      map.addLayer({
        id: "osm-substation-circles",
        type: "circle",
        source: "osm-power-substations",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"],
            5, ["interpolate", ["linear"], ["coalesce", ["get", "voltage_kv"], 0], 0, 2, 132, 4, 400, 7],
            10, ["interpolate", ["linear"], ["coalesce", ["get", "voltage_kv"], 0], 0, 4, 132, 8, 400, 14],
            14, ["interpolate", ["linear"], ["coalesce", ["get", "voltage_kv"], 0], 0, 6, 132, 12, 400, 20],
          ],
          "circle-color": osmVoltageColor,
          "circle-opacity": 0.75,
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "rgba(255,255,255,0.7)",
        },
        layout: { visibility: "none" },
      });

      // Substation labels
      map.addLayer({
        id: "osm-substation-labels",
        type: "symbol",
        source: "osm-power-substations",
        paint: {
          "text-color": "#333",
          "text-halo-color": "rgba(255,255,255,0.9)",
          "text-halo-width": 1.5,
        },
        layout: {
          "text-field": ["concat",
            ["coalesce", ["get", "name"], "Substation"],
            ["case", ["has", "voltage_kv"],
              ["concat", "\n", ["to-string", ["round", ["get", "voltage_kv"]]], "kV"], ""],
          ],
          "text-font": ["Noto Sans Regular"],
          "text-size": 10,
          "text-offset": [0, 1.8],
          "text-anchor": "top",
          visibility: "none",
        },
        minzoom: 10,
      });

      // Tower dots (very numerous — only at zoom >= 12)
      map.addLayer({
        id: "osm-tower-dots",
        type: "circle",
        source: "osm-power-towers",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 2, 16, 5],
          "circle-color": ["match", ["get", "tower_type"], "pole", "#8B6914", "portal", "#555", "#444"],
          "circle-opacity": 0.7,
          "circle-stroke-width": 0.5,
          "circle-stroke-color": "rgba(255,255,255,0.5)",
        },
        layout: { visibility: "none" },
        minzoom: 12,
      });

      // Generator circles — coloured by source
      map.addLayer({
        id: "osm-generator-circles",
        type: "circle",
        source: "osm-power-generators",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"],
            8, 3, 12, 7, 16, 12],
          "circle-color": [
            "match", ["coalesce", ["get", "source"], "unknown"],
            "solar", "#FDD835",
            "wind", "#00B0FF",
            "gas", "#FF8F00",
            "nuclear", "#E53935",
            "hydro", "#1565C0",
            "biomass", "#8D6E63",
            "oil", "#795548",
            "coal", "#424242",
            "battery", "#7CB342",
            "waste", "#6D4C41",
            "#888",
          ],
          "circle-opacity": 0.8,
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "rgba(255,255,255,0.7)",
        },
        layout: { visibility: "none" },
        minzoom: 8,
      });

      // Generator labels
      map.addLayer({
        id: "osm-generator-labels",
        type: "symbol",
        source: "osm-power-generators",
        paint: {
          "text-color": "#333",
          "text-halo-color": "rgba(255,255,255,0.9)",
          "text-halo-width": 1.5,
        },
        layout: {
          "text-field": ["concat",
            ["coalesce", ["get", "name"], ["coalesce", ["get", "source"], "generator"]],
            ["case", ["has", "output_kw"],
              ["concat", "\n", ["to-string", ["round", ["get", "output_kw"]]], " kW"], ""],
          ],
          "text-font": ["Noto Sans Regular"],
          "text-size": 9,
          "text-offset": [0, 1.5],
          "text-anchor": "top",
          visibility: "none",
        },
        minzoom: 11,
      });

      // OSM power click popups
      map.on("click", "osm-power-line-core", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        const vkv = p.voltage_kv ? `${Math.round(p.voltage_kv)} kV` : "Unknown voltage";
        const typ = p.line_type || "line";
        const op = p.operator ? `<br/>Operator: ${p.operator}` : "";
        const nm = p.name ? `<strong>${p.name}</strong><br/>` : "";
        const rf = p.ref ? `Ref: ${p.ref}<br/>` : "";
        new mapboxgl.Popup({ maxWidth: "260px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px">${nm}${rf}${vkv} ${typ}${op}</div>`)
          .addTo(map);
      });
      map.on("click", "osm-substation-circles", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        const nm = p.name || "Substation";
        const vkv = p.voltage_kv ? `${Math.round(p.voltage_kv)} kV` : "";
        const typ = p.substation_type ? `Type: ${p.substation_type}<br/>` : "";
        const op = p.operator ? `Operator: ${p.operator}` : "";
        new mapboxgl.Popup({ maxWidth: "240px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${nm}</strong><br/>${vkv ? vkv + "<br/>" : ""}${typ}${op}</div>`)
          .addTo(map);
      });
      map.on("click", "osm-generator-circles", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        const nm = p.name || "Generator";
        const src = p.source ? `Source: ${p.source}<br/>` : "";
        const out = p.output_kw ? `Output: ${Math.round(p.output_kw)} kW` : "";
        const op = p.operator ? `<br/>Operator: ${p.operator}` : "";
        new mapboxgl.Popup({ maxWidth: "240px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${nm}</strong><br/>${src}${out}${op}</div>`)
          .addTo(map);
      });
      for (const lid of ["osm-power-line-core", "osm-substation-circles", "osm-generator-circles"]) {
        map.on("mouseenter", lid, () => { if (!map._pickMode) map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", lid, () => { if (!map._pickMode) map.getCanvas().style.cursor = ""; });
      }

      // NGED CIM substation circles — RAG coloured by headroom
      map.addLayer({
        id: "nged-sub-circles",
        type: "circle",
        source: "nged-substations",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"],
            5, ["interpolate", ["linear"], ["coalesce", ["get", "rated_mva"], 0], 0, 3, 20, 5, 100, 9],
            10, ["interpolate", ["linear"], ["coalesce", ["get", "rated_mva"], 0], 0, 5, 20, 9, 100, 16],
            14, ["interpolate", ["linear"], ["coalesce", ["get", "rated_mva"], 0], 0, 7, 20, 12, 100, 22],
          ],
          "circle-color": [
            "match", ["coalesce", ["get", "rag"], "gray"],
            "green", "#4caf50",
            "amber", "#ff9800",
            "red", "#f44336",
            "#999"
          ],
          "circle-opacity": 0.8,
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "rgba(255,255,255,0.7)",
        },
        layout: { visibility: "none" },
      });

      // NGED substation labels
      map.addLayer({
        id: "nged-sub-labels",
        type: "symbol",
        source: "nged-substations",
        paint: {
          "text-color": "#333",
          "text-halo-color": "rgba(255,255,255,0.9)",
          "text-halo-width": 1.5,
        },
        layout: {
          visibility: "none",
          "text-field": ["concat", ["get", "name"], "\n", ["to-string", ["get", "headroom_mw"]], " MW"],
          "text-size": 10,
          "text-offset": [0, 1.5],
          "text-anchor": "top",
          "text-optional": true,
        },
        minzoom: 10,
      });

      // NGED substation click popup
      map.on("click", "nged-sub-circles", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        const name = p.name || "Substation";
        const region = p.region ? `<br/>Region: ${p.region.replace(/_/g, " ")}` : "";
        const voltage = p.voltage_kv ? `<br/>Voltage: ${p.voltage_kv} kV` : "";
        const rated = p.rated_mva ? `<br/>Rated: ${p.rated_mva} MVA` : "";
        const load = p.connected_load_mw != null ? `<br/>Load: ${p.connected_load_mw} MW` : "";
        const headroom = p.headroom_mw != null ? `<br/><strong>Headroom: ${p.headroom_mw} MW</strong>` : "";
        const confidence = p.osm_match_score ? `<br/><span style="opacity:0.6">Match: ${Math.round(p.osm_match_score * 100)}%</span>` : "";
        new mapboxgl.Popup({ maxWidth: "260px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${name}</strong>${region}${voltage}${rated}${load}${headroom}${confidence}</div>`)
          .addTo(map);
      });
      map.on("mouseenter", "nged-sub-circles", () => { if (!map._pickMode) map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "nged-sub-circles", () => { if (!map._pickMode) map.getCanvas().style.cursor = ""; });

      // ── Grid Connection Capacity Map layers ──
      // Grid lines (transmission/distribution)
      map.addLayer({
        id: "gc-lines-glow",
        type: "line",
        source: "gc-grid-lines",
        paint: {
          "line-color": ["match", ["coalesce", ["get", "voltage_kv"], 0],
            400, "#e53935", 275, "#ff7043", 132, "#ffa726", 66, "#ffca28", 33, "#66bb6a", "#90a4ae"],
          "line-width": ["interpolate", ["linear"], ["zoom"], 5, 1, 10, 2, 14, 4],
          "line-blur": 3,
          "line-opacity": 0.5,
        },
        layout: { visibility: "none", "line-cap": "round" },
      });
      map.addLayer({
        id: "gc-lines-core",
        type: "line",
        source: "gc-grid-lines",
        paint: {
          "line-color": ["match", ["coalesce", ["get", "voltage_kv"], 0],
            400, "#e53935", 275, "#ff7043", 132, "#ffa726", 66, "#ffca28", 33, "#66bb6a", "#90a4ae"],
          "line-width": ["interpolate", ["linear"], ["zoom"], 5, 0.5, 10, 1, 14, 2],
          "line-opacity": 0.85,
        },
        layout: { visibility: "none", "line-cap": "round" },
      });

      // Capacity substation circles — graduated by headroom
      map.addLayer({
        id: "gc-capacity-circles",
        type: "circle",
        source: "gc-capacity-subs",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"],
            5, ["interpolate", ["linear"], ["coalesce", ["get", "gen_headroom_mw"], 0], 0, 3, 10, 6, 50, 10, 200, 16],
            10, ["interpolate", ["linear"], ["coalesce", ["get", "gen_headroom_mw"], 0], 0, 5, 10, 10, 50, 16, 200, 24],
            14, ["interpolate", ["linear"], ["coalesce", ["get", "gen_headroom_mw"], 0], 0, 7, 10, 14, 50, 22, 200, 32],
          ],
          "circle-color": [
            "match", ["coalesce", ["get", "rag"], "gray"],
            "green", "#24a148", "amber", "#f1c21b", "red", "#da1e28", "#8d8d8d"
          ],
          "circle-opacity": 0.75,
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "rgba(255,255,255,0.6)",
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "gc-capacity-labels",
        type: "symbol",
        source: "gc-capacity-subs",
        paint: {
          "text-color": "#f4f4f4",
          "text-halo-color": "rgba(0,0,0,0.8)",
          "text-halo-width": 1.5,
        },
        layout: {
          visibility: "none",
          "text-field": ["concat", ["get", "name"], "\n", ["to-string", ["round", ["coalesce", ["get", "gen_headroom_mw"], 0]]], " MW"],
          "text-size": 10,
          "text-offset": [0, 1.8],
          "text-anchor": "top",
          "text-optional": true,
        },
        minzoom: 9,
      });

      // Highlighted candidate substation (pulsing ring)
      map.addLayer({
        id: "gc-highlight-ring",
        type: "circle",
        source: "gc-highlight-sub",
        paint: {
          "circle-radius": 18,
          "circle-color": "transparent",
          "circle-stroke-width": 3,
          "circle-stroke-color": "#D4A018",
          "circle-opacity": 1,
        },
        layout: { visibility: "visible" },
      });

      map.on("click", "gc-capacity-circles", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        const coords = e.features[0].geometry.coordinates;
        const name = p.name || "Substation";
        // Dispatch event for copilot node inspector
        window.dispatchEvent(new CustomEvent("princeps-node-click", {
          detail: { ...p, name, lat: coords[1], lon: coords[0] },
        }));
        // Also show popup
        const headroom = p.gen_headroom_mw != null ? `<br/><strong>Headroom: ${p.gen_headroom_mw} MW</strong>` : "";
        const voltage = p.voltage_kv ? `<br/>Voltage: ${p.voltage_kv} kV` : "";
        const queued = p.ecr_queued ? `<br/>Queue: ${p.ecr_queued} projects` : "";
        new mapboxgl.Popup({ maxWidth: "240px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${name}</strong>${voltage}${headroom}${queued}</div>`)
          .addTo(map);
      });
      map.on("mouseenter", "gc-capacity-circles", () => { if (!map._pickMode) map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "gc-capacity-circles", () => { if (!map._pickMode) map.getCanvas().style.cursor = ""; });

      // ── Grid Constraint Overlay — boundary zone polygons ──
      map.addLayer({
        id: "constraint-zone-fill",
        type: "fill",
        source: "grid-constraints",
        paint: {
          "fill-color": [
            "match", ["get", "risk_level"],
            "HIGH", "#f44336",
            "MEDIUM", "#ff9800",
            "LOW", "#4caf50",
            "#888",
          ],
          "fill-opacity": [
            "interpolate", ["linear"], ["get", "peak_constraint_prob"],
            0, 0.08, 0.3, 0.18, 0.6, 0.35, 1.0, 0.55,
          ],
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "constraint-zone-outline",
        type: "line",
        source: "grid-constraints",
        paint: {
          "line-color": [
            "match", ["get", "risk_level"],
            "HIGH", "#f44336",
            "MEDIUM", "#ff9800",
            "LOW", "#4caf50",
            "#888",
          ],
          "line-width": 2,
          "line-dasharray": [4, 2],
          "line-opacity": 0.8,
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "constraint-zone-labels",
        type: "symbol",
        source: "grid-constraints",
        paint: {
          "text-color": "#fff",
          "text-halo-color": "rgba(0,0,0,0.85)",
          "text-halo-width": 1.5,
        },
        layout: {
          visibility: "none",
          "text-field": [
            "concat",
            ["get", "boundary_id"], " ", ["get", "name"],
            "\n", ["to-string", ["round", ["get", "peak_loading_pct"]]], "% loaded",
            "\n£", ["to-string", ["get", "constraint_cost_gbp_mwh"]], "/MWh",
          ],
          "text-size": 12,
          "text-font": ["Noto Sans Bold"],
          "text-allow-overlap": true,
        },
        minzoom: 5,
      });

      map.on("click", "constraint-zone-fill", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        new mapboxgl.Popup({ maxWidth: "280px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px">
            <strong>${p.boundary_id} — ${p.name}</strong>
            <br/>Capacity: ${p.capacity_gw} GW
            <br/>Peak loading: ${p.peak_loading_pct}%
            <br/>Risk: <span style="color:${p.risk_level === "HIGH" ? "#f44336" : p.risk_level === "MEDIUM" ? "#ff9800" : "#4caf50"}">${p.risk_level}</span>
            <br/>Constrained hours (48h): ${p.constrained_hours}
            <br/>Constraint cost: £${p.constraint_cost_gbp_mwh}/MWh
          </div>`)
          .addTo(map);
      });
      map.on("mouseenter", "constraint-zone-fill", () => { if (!map._pickMode) map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "constraint-zone-fill", () => { if (!map._pickMode) map.getCanvas().style.cursor = ""; });

      // ── Land Registry Parcels ──
      map.addLayer({
        id: "land-parcels-fill",
        type: "fill",
        source: "land-parcels",
        paint: {
          "fill-color": ["get", "color"],
          "fill-opacity": 0.15,
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "land-parcels-outline",
        type: "line",
        source: "land-parcels",
        paint: {
          "line-color": ["get", "color"],
          "line-width": 1.5,
          "line-opacity": 0.7,
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "land-parcels-labels",
        type: "symbol",
        source: "land-parcels",
        paint: {
          "text-color": "#f4f4f4",
          "text-halo-color": "rgba(0,0,0,0.8)",
          "text-halo-width": 1.2,
        },
        layout: {
          visibility: "none",
          "text-field": [
            "concat",
            ["to-string", ["get", "area_ha"]], " ha\n",
            ["get", "tenure"],
          ],
          "text-size": 10,
          "text-font": ["Noto Sans Regular"],
          "text-allow-overlap": false,
        },
        minzoom: 14,
      });
      map.addLayer({
        id: "land-available-markers",
        type: "circle",
        source: "land-parcels",
        filter: ["==", ["get", "available"], true],
        paint: {
          "circle-radius": 6,
          "circle-color": "#16a34a",
          "circle-opacity": 0.8,
          "circle-stroke-width": 2,
          "circle-stroke-color": "#ffffff",
        },
        layout: { visibility: "none" },
        minzoom: 12,
      });
      map.on("click", "land-parcels-fill", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        new mapboxgl.Popup({ maxWidth: "260px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px">
            <strong>${p.title_number || "Parcel"}</strong>
            <br/>Tenure: <span style="color:${p.color}">${p.tenure}</span>
            <br/>Area: ${p.area_ha} ha
            ${p.available ? '<br/><span style="color:#16a34a;font-weight:600">Potentially available</span>' : ""}
          </div>`)
          .addTo(map);
      });
      map.on("mouseenter", "land-parcels-fill", () => { if (!map._pickMode) map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "land-parcels-fill", () => { if (!map._pickMode) map.getCanvas().style.cursor = ""; });

      // ── Land highlight pulse (selected listing) ──
      map.addLayer({
        id: "land-highlight-pulse",
        type: "circle",
        source: "land-highlight",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 20, 14, 40, 18, 60],
          "circle-color": "#D4A018",
          "circle-opacity": 0.3,
          "circle-stroke-width": 3,
          "circle-stroke-color": "#D4A018",
          "circle-stroke-opacity": 0.8,
        },
      });
      map.addLayer({
        id: "land-highlight-core",
        type: "circle",
        source: "land-highlight",
        paint: {
          "circle-radius": 8,
          "circle-color": "#D4A018",
          "circle-opacity": 0.9,
          "circle-stroke-width": 2,
          "circle-stroke-color": "#fff",
        },
      });
      map.addLayer({
        id: "land-highlight-label",
        type: "symbol",
        source: "land-highlight",
        layout: {
          "text-field": ["get", "label"],
          "text-size": 12,
          "text-anchor": "bottom",
          "text-offset": [0, -2],
          "text-allow-overlap": true,
          "text-font": ["Noto Sans Bold"],
        },
        paint: {
          "text-color": "#ffffff",
          "text-halo-color": "#D4A018",
          "text-halo-width": 2,
        },
      });

      // Listen for land highlight events from copilot
      const landHighlightHandler = (e) => {
        const { lat, lon, id } = e.detail;
        const src = map.getSource("land-highlight");
        if (src) {
          src.setData({
            type: "FeatureCollection",
            features: [{
              type: "Feature",
              geometry: { type: "Point", coordinates: [lon, lat] },
              properties: { id, label: "Selected Site" },
            }],
          });
          // Auto-clear after 8 seconds
          setTimeout(() => {
            const s = map.getSource("land-highlight");
            if (s) s.setData({ type: "FeatureCollection", features: [] });
          }, 8000);
        }
      };
      window.addEventListener("princeps-land-highlight", landHighlightHandler);

      // ── Queue Depth circles at substations ──
      map.addLayer({
        id: "queue-depth-circles",
        type: "circle",
        source: "queue-depth",
        paint: {
          "circle-radius": [
            "interpolate", ["linear"], ["get", "queue_count"],
            1, 5, 5, 10, 15, 18, 30, 26,
          ],
          "circle-color": [
            "match", ["get", "queue_pressure"],
            "HIGH", "#e040fb",
            "MEDIUM", "#ab47bc",
            "LOW", "#7e57c2",
            "#888",
          ],
          "circle-opacity": 0.7,
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "rgba(255,255,255,0.5)",
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "queue-depth-labels",
        type: "symbol",
        source: "queue-depth",
        paint: {
          "text-color": "#f4f4f4",
          "text-halo-color": "rgba(0,0,0,0.8)",
          "text-halo-width": 1.5,
        },
        layout: {
          visibility: "none",
          "text-field": [
            "concat",
            ["get", "name"],
            "\n", ["to-string", ["get", "queue_count"]], " queued · ",
            ["to-string", ["get", "estimated_wait_months"]], "mo",
          ],
          "text-size": 10,
          "text-offset": [0, 2],
          "text-anchor": "top",
          "text-optional": true,
        },
        minzoom: 8,
      });

      map.on("click", "queue-depth-circles", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        new mapboxgl.Popup({ maxWidth: "280px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px">
            <strong>${p.name}</strong> (${p.dno})
            <br/>Voltage: ${p.voltage_kv} kV
            <br/>Queue: ${p.queue_count} projects (${p.queued_mw} MW)
            <br/>Connected: ${p.connected_count} (${p.connected_mw} MW)
            <br/>Headroom: ${p.headroom_mw} MW
            <br/>Est. wait: <strong>${p.estimated_wait_months} months</strong>
            <br/>Pressure: <span style="color:${p.queue_pressure === "HIGH" ? "#e040fb" : p.queue_pressure === "MEDIUM" ? "#ab47bc" : "#7e57c2"}">${p.queue_pressure}</span>
          </div>`)
          .addTo(map);
      });
      map.on("mouseenter", "queue-depth-circles", () => { if (!map._pickMode) map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "queue-depth-circles", () => { if (!map._pickMode) map.getCanvas().style.cursor = ""; });

      // ── DC Capacity circles (green-yellow-red by suitability) ──
      map.addLayer({
        id: "dc-capacity-circles",
        type: "circle",
        source: "dc-capacity",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 5, 10, 10, 14, 16],
          "circle-color": ["coalesce", ["get", "color"], "#D4A018"],
          "circle-opacity": 0.8,
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "rgba(255,255,255,0.5)",
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "dc-capacity-labels",
        type: "symbol",
        source: "dc-capacity",
        paint: { "text-color": "#f4f4f4", "text-halo-color": "rgba(0,0,0,0.8)", "text-halo-width": 1.5 },
        layout: {
          visibility: "none",
          "text-field": ["concat", ["get", "name"], "\n", ["to-string", ["round", ["coalesce", ["get", "headroom_mw"], 0]]], " MW"],
          "text-size": 10, "text-offset": [0, 1.8], "text-anchor": "top", "text-optional": true,
        },
        minzoom: 9,
      });
      map.on("click", "dc-capacity-circles", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        new mapboxgl.Popup({ maxWidth: "240px" }).setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${p.name||"Substation"}</strong><br/>Headroom: <strong>${p.headroom_mw||"--"} MW</strong><br/>Voltage: ${p.voltage_kv||"--"} kV<br/>Suitability: ${p.suitability||"--"}</div>`)
          .addTo(map);
      });
      map.on("mouseenter", "dc-capacity-circles", () => { if (!map._pickMode) map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "dc-capacity-circles", () => { if (!map._pickMode) map.getCanvas().style.cursor = ""; });

      // ── DC Fibre POP circles (purple) ──
      map.addLayer({
        id: "dc-fibre-circles",
        type: "circle",
        source: "dc-fibre",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 2, 10, 5, 14, 8],
          "circle-color": "#a855f7",
          "circle-opacity": 0.7,
          "circle-stroke-width": 1,
          "circle-stroke-color": "rgba(168,85,247,0.5)",
        },
        layout: { visibility: "none" },
      });

      // ── DC IXP circles (blue diamonds via circle) ──
      map.addLayer({
        id: "dc-ixp-circles",
        type: "circle",
        source: "dc-ixp",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 6, 10, 10, 14, 14],
          "circle-color": "#3b82f6",
          "circle-opacity": 0.8,
          "circle-stroke-width": 2,
          "circle-stroke-color": "#fff",
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "dc-ixp-labels",
        type: "symbol",
        source: "dc-ixp",
        paint: { "text-color": "#93c5fd", "text-halo-color": "rgba(0,0,0,0.8)", "text-halo-width": 1.5 },
        layout: {
          visibility: "none",
          "text-field": ["get", "name"],
          "text-size": 11, "text-offset": [0, 1.5], "text-anchor": "top", "text-optional": true,
        },
        minzoom: 8,
      });

      // ── Demand GSP circles ──
      map.addLayer({
        id: "demand-gsp-circles",
        type: "circle",
        source: "demand-gsps",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "peak_demand_mw"],
            40, 5, 200, 10, 500, 16],
          "circle-color": ["interpolate", ["linear"], ["get", "utilisation"],
            0, "#52c41a", 0.6, "#52c41a", 0.75, "#fa8c16", 0.9, "#f5222d"],
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "rgba(255,255,255,0.3)",
          "circle-opacity": 0.85,
        },
        layout: { visibility: "none" },
      });
      map.addLayer({
        id: "demand-gsp-labels",
        type: "symbol",
        source: "demand-gsps",
        layout: {
          "text-field": ["get", "gsp_name"],
          "text-size": 9,
          "text-offset": [0, 1.5],
          "text-anchor": "top",
          visibility: "none",
        },
        paint: {
          "text-color": "rgba(255,255,255,0.6)",
          "text-halo-color": "rgba(0,0,0,0.7)",
          "text-halo-width": 1,
        },
      });

      map.on("click", "demand-gsp-circles", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        const util = p.utilisation != null ? `<br/>Utilisation: <strong>${(p.utilisation * 100).toFixed(1)}%</strong>` : "";
        new mapboxgl.Popup({ maxWidth: "240px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${p.gsp_name}</strong> (${p.dno})<br/>Peak: ${p.peak_demand_mw} MW / Cap: ${p.capacity_mw} MW${util}</div>`)
          .addTo(map);
      });
      map.on("mouseenter", "demand-gsp-circles", () => { if (!map._pickMode) map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "demand-gsp-circles", () => { if (!map._pickMode) map.getCanvas().style.cursor = ""; });

      // ── ESO TEC Pipeline circles ──
      map.addLayer({
        id: "eso-tec-circles",
        type: "circle",
        source: "eso-tec-projects",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"],
            5, ["interpolate", ["linear"], ["coalesce", ["get", "capacity_mw"], 0], 0, 3, 100, 6, 500, 10, 2000, 16],
            10, ["interpolate", ["linear"], ["coalesce", ["get", "capacity_mw"], 0], 0, 5, 100, 10, 500, 18, 2000, 28],
            14, ["interpolate", ["linear"], ["coalesce", ["get", "capacity_mw"], 0], 0, 7, 100, 14, 500, 24, 2000, 36],
          ],
          "circle-color": [
            "match", ["coalesce", ["get", "plant_type"], "Other"],
            "Solar", "#fdd835",
            "Wind", "#00b0ff",
            "Battery", "#7cb342",
            "Gas", "#ff8f00",
            "Nuclear", "#e53935",
            "Hydro", "#1565c0",
            "Biomass", "#8d6e63",
            "Interconnector", "#ab47bc",
            "#0277bd"
          ],
          "circle-opacity": 0.82,
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "rgba(255,255,255,0.7)",
        },
        layout: { visibility: "none" },
      });

      // TEC labels
      map.addLayer({
        id: "eso-tec-labels",
        type: "symbol",
        source: "eso-tec-projects",
        paint: {
          "text-color": "#1a237e",
          "text-halo-color": "rgba(255,255,255,0.9)",
          "text-halo-width": 1.5,
        },
        layout: {
          visibility: "none",
          "text-field": ["concat", ["get", "name"], "\n", ["to-string", ["coalesce", ["get", "capacity_mw"], 0]], " MW"],
          "text-size": 10,
          "text-offset": [0, 1.5],
          "text-anchor": "top",
          "text-optional": true,
        },
        minzoom: 9,
      });

      // TEC click popup
      map.on("click", "eso-tec-circles", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        const cap = p.capacity_mw ? `<br/>Capacity: ${p.capacity_mw} MW` : "";
        const pt = p.plant_type ? `<br/>Type: ${p.plant_type}` : "";
        const st = p.status ? `<br/>Status: ${p.status}` : "";
        const host = p.host_to ? `<br/>TO: ${p.host_to}` : "";
        const site = p.connection_site ? `<br/>Site: ${p.connection_site}` : "";
        new mapboxgl.Popup({ maxWidth: "280px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${p.name || "TEC Project"}</strong>${pt}${cap}${st}${host}${site}</div>`)
          .addTo(map);
      });
      map.on("mouseenter", "eso-tec-circles", () => { if (!map._pickMode) map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "eso-tec-circles", () => { if (!map._pickMode) map.getCanvas().style.cursor = ""; });

      // ── REPD Project circles ──
      map.addLayer({
        id: "repd-circles",
        type: "circle",
        source: "repd-projects",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"],
            5, ["interpolate", ["linear"], ["coalesce", ["get", "capacity_mw"], 0], 0, 2, 5, 4, 50, 7, 200, 12],
            10, ["interpolate", ["linear"], ["coalesce", ["get", "capacity_mw"], 0], 0, 3, 5, 6, 50, 12, 200, 20],
            14, ["interpolate", ["linear"], ["coalesce", ["get", "capacity_mw"], 0], 0, 5, 5, 10, 50, 18, 200, 28],
          ],
          "circle-color": [
            "match", ["coalesce", ["get", "technology"], "Other"],
            "Solar Photovoltaics", "#fdd835",
            "Wind Onshore", "#00b0ff",
            "Wind Offshore", "#0277bd",
            "Battery", "#7cb342",
            "Biomass (dedicated)", "#8d6e63",
            "Landfill Gas", "#a1887f",
            "Anaerobic Digestion", "#6d4c41",
            "Small Hydro", "#1565c0",
            "Large Hydro", "#0d47a1",
            "EfW Incineration", "#e53935",
            "#ff6f00"
          ],
          "circle-opacity": 0.75,
          "circle-stroke-width": 1,
          "circle-stroke-color": "rgba(255,255,255,0.6)",
        },
        layout: { visibility: "none" },
      });

      // REPD labels
      map.addLayer({
        id: "repd-labels",
        type: "symbol",
        source: "repd-projects",
        paint: {
          "text-color": "#e65100",
          "text-halo-color": "rgba(255,255,255,0.9)",
          "text-halo-width": 1.5,
        },
        layout: {
          visibility: "none",
          "text-field": ["concat", ["get", "name"], "\n", ["to-string", ["coalesce", ["get", "capacity_mw"], 0]], " MW"],
          "text-size": 10,
          "text-offset": [0, 1.5],
          "text-anchor": "top",
          "text-optional": true,
        },
        minzoom: 10,
      });

      // REPD click popup
      map.on("click", "repd-circles", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        const cap = p.capacity_mw ? `<br/>Capacity: ${p.capacity_mw} MW` : "";
        const tech = p.technology ? `<br/>Tech: ${p.technology}` : "";
        const st = p.status ? `<br/>Status: ${p.status}` : "";
        const rgn = p.region ? `<br/>Region: ${p.region}` : "";
        const op = p.operator ? `<br/>Operator: ${p.operator}` : "";
        new mapboxgl.Popup({ maxWidth: "280px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${p.name || "REPD Site"}</strong>${tech}${cap}${st}${rgn}${op}</div>`)
          .addTo(map);
      });
      map.on("mouseenter", "repd-circles", () => { if (!map._pickMode) map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "repd-circles", () => { if (!map._pickMode) map.getCanvas().style.cursor = ""; });

      // ── GeeFlow Land Use / Opportunity layers ──
      map.addSource("geeflow-landuse", { type: "geojson", data: EMPTY_FC });
      map.addSource("geeflow-opportunities", { type: "geojson", data: EMPTY_FC });

      map.addLayer({
        id: "geeflow-landuse-fill",
        type: "fill",
        source: "geeflow-landuse",
        paint: {
          "fill-color": [
            "match", ["get", "class"],
            "water", "#2196f3",
            "trees", "#2e7d32",
            "grass", "#8bc34a",
            "crops", "#ffc107",
            "built", "#9e9e9e",
            "bare", "#d7ccc8",
            "shrub_and_scrub", "#795548",
            "#666"
          ],
          "fill-opacity": 0.5,
        },
        layout: { visibility: "none" },
      });

      map.addLayer({
        id: "geeflow-opp-circles",
        type: "circle",
        source: "geeflow-opportunities",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 4, 12, 10],
          "circle-color": [
            "match", ["get", "suitability"],
            "high", "#4caf50",
            "moderate", "#ff9800",
            "low", "#f44336",
            "#999"
          ],
          "circle-opacity": 0.8,
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 1,
        },
        layout: { visibility: "none" },
      });

      map.addLayer({
        id: "geeflow-opp-labels",
        type: "symbol",
        source: "geeflow-opportunities",
        paint: {
          "text-color": "#fff",
          "text-halo-color": "rgba(0,0,0,0.7)",
          "text-halo-width": 1.2,
        },
        layout: {
          visibility: "none",
          "text-field": ["concat", ["get", "substation"], "\n", ["get", "suitability"]],
          "text-size": 10,
          "text-offset": [0, 1.5],
          "text-anchor": "top",
          "text-optional": true,
        },
        minzoom: 9,
      });

      // ── Electricity Zones (Carbon Intensity) ──
      map.addSource("electricity-zones", { type: "geojson", data: EMPTY_FC });

      // Fill layer — colored by carbon intensity (green → yellow → red)
      map.addLayer({
        id: "electricity-zones-fill",
        type: "fill",
        source: "electricity-zones",
        paint: {
          "fill-color": [
            "interpolate", ["linear"],
            ["coalesce", ["get", "carbonIntensity"], 200],
            0, "rgba(76, 175, 80, 0.6)",     // green — very clean
            100, "rgba(139, 195, 74, 0.6)",
            200, "rgba(255, 235, 59, 0.6)",   // yellow — moderate
            400, "rgba(255, 152, 0, 0.6)",    // orange
            600, "rgba(244, 67, 54, 0.6)",    // red — dirty
            800, "rgba(183, 28, 28, 0.6)",
          ],
          "fill-opacity": 0.55,
        },
        layout: { visibility: "none" },
      });

      // Border lines
      map.addLayer({
        id: "electricity-zones-line",
        type: "line",
        source: "electricity-zones",
        paint: {
          "line-color": "rgba(255, 255, 255, 0.7)",
          "line-width": 1,
        },
        layout: { visibility: "none" },
      });

      // Zone labels with CO2 values
      map.addLayer({
        id: "electricity-zones-labels",
        type: "symbol",
        source: "electricity-zones",
        paint: {
          "text-color": "#212121",
          "text-halo-color": "rgba(255, 255, 255, 0.9)",
          "text-halo-width": 1.5,
        },
        layout: {
          "text-field": [
            "concat",
            ["get", "zoneName"],
            "\n",
            ["case",
              ["has", "carbonIntensity"],
              ["concat", ["to-string", ["round", ["get", "carbonIntensity"]]], " gCO\u2082"],
              "—"
            ],
          ],
          "text-font": ["Noto Sans Bold"],
          "text-size": 11,
          visibility: "none",
        },
        minzoom: 4,
      });

      // Zone click popup
      map.on("click", "electricity-zones-fill", (e) => {
        if (map._pickMode || !e.features?.length) return;
        const p = e.features[0].properties;
        const ci = p.carbonIntensity != null ? `${Math.round(p.carbonIntensity)} gCO\u2082/kWh` : "No data";
        const fossil = p.fossilFreePercentage != null ? `${Math.round(p.fossilFreePercentage)}%` : "—";
        const renewable = p.renewablePercentage != null ? `${Math.round(p.renewablePercentage)}%` : "—";
        new mapboxgl.Popup({ maxWidth: "240px" })
          .setLngLat(e.lngLat)
          .setHTML(
            `<div style="font-size:12px">` +
            `<strong>${p.zoneName || p.countryName || "Zone"}</strong><br/>` +
            `Carbon Intensity: <strong>${ci}</strong><br/>` +
            `Fossil-free: ${fossil}<br/>` +
            `Renewable: ${renewable}` +
            `</div>`
          )
          .addTo(map);
      });
      map.on("mouseenter", "electricity-zones-fill", () => { if (!map._pickMode) map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "electricity-zones-fill", () => { if (!map._pickMode) map.getCanvas().style.cursor = ""; });

      // Grid flow click popups
      map.on("click", "grid-flow-core", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        const pct = ((p.utilization || 0) * 100).toFixed(1);
        const vkv = p.voltage_kv ? ` (${p.voltage_kv}kV)` : "";
        new mapboxgl.Popup({ maxWidth: "260px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${p.from_node} → ${p.to_node}</strong>${vkv}<br/>Flow: ${p.flow_mw} MW<br/>Capacity: ${p.capacity_mva} MVA<br/>Utilization: <strong>${pct}%</strong></div>`)
          .addTo(map);
      });
      map.on("click", "grid-node-circles", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        const name = p.name || p.node_id;
        const vkv = p.voltage_kv ? `${p.voltage_kv}kV ` : "";
        new mapboxgl.Popup({ maxWidth: "220px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${name}</strong><br/>${vkv}${(p.node_type || "").toUpperCase()}<br/>Demand: ${p.demand_mw || p.load_mw || 0} MW</div>`)
          .addTo(map);
      });
      // Live grid click popups
      map.on("click", "grid-live-ic-core", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        new mapboxgl.Popup({ maxWidth: "240px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${p.label}</strong><br/>Flow: ${p.flow_mw} MW (${p.direction})</div>`)
          .addTo(map);
      });
      map.on("click", "grid-live-gen-circles", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        new mapboxgl.Popup({ maxWidth: "200px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${p.label}</strong><br/>Generation: ${p.generation_mw} MW</div>`)
          .addTo(map);
      });
      for (const lid of ["grid-flow-core", "grid-node-circles", "grid-live-ic-core", "grid-live-gen-circles"]) {
        map.on("mouseenter", lid, () => { if (!map._pickMode) map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", lid, () => { if (!map._pickMode) map.getCanvas().style.cursor = ""; });
      }

      // ── EPC click popups ──
      map.on("click", "epc-dom-circles", (e) => {
        if (map._pickMode) return;
        if (!e.features?.length) return;
        const p = e.features[0].properties;
        const rows = [
          ["Rating", `${p.cur_rate || "?"} (${p.cur_ee || "?"}/${p.per_ee || "?"})`],
          ["Type", `${p.b_type || ""} ${p.p_type || ""}`],
          ["Age", p.age], ["Tenure", p.tenure], ["Area", p.area ? `${p.area} m\u00B2` : ""],
          ["Walls", `${p.wall_d || ""} (${p.wall_ee || ""})`],
          ["Roof", `${p.roof_d || ""} (${p.roof_ee || ""})`],
          ["Floor", `${p.floor_d || ""} (${p.floor_ee || ""})`],
          ["Windows", `${p.wind_d || ""} (${p.wind_ee || ""})`],
          ["Heating", `${p.heat_d || ""} (${p.heat_ee || ""})`],
          ["Fuel", p.fuel], ["Solar PV", p.pv], ["Solar Thermal", p.sol_wat],
        ].filter(([, v]) => v && v !== " ()").map(([k, v]) => `<tr><td style="font-weight:600;padding:2px 6px">${k}</td><td style="padding:2px 6px">${v}</td></tr>`).join("");
        new mapboxgl.Popup({ maxWidth: "320px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:11px"><h4 style="margin:0 0 4px;font-size:13px">Domestic EPC</h4><div style="font-size:10px;color:#6b7c8d;margin-bottom:4px">${p.addr || ""}</div><table>${rows}</table></div>`)
          .addTo(map);
      });

      map.on("click", "epc-nondom-circles", (e) => {
        if (map._pickMode) return;
        if (!e.features?.length) return;
        const p = e.features[0].properties;
        const rows = [
          ["Rating", `${p.band || "?"} (${p.rating || "?"})`],
          ["Type", p.type], ["Transaction", p.transaction],
          ["Area", p.area ? `${p.area} m\u00B2` : ""], ["Fuel", p.fuel], ["Year", p.year],
        ].filter(([, v]) => v).map(([k, v]) => `<tr><td style="font-weight:600;padding:2px 6px">${k}</td><td style="padding:2px 6px">${v}</td></tr>`).join("");
        new mapboxgl.Popup({ maxWidth: "300px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:11px"><h4 style="margin:0 0 4px;font-size:13px">Non-Domestic EPC</h4><div style="font-size:10px;color:#6b7c8d;margin-bottom:4px">${p.adr2 || p.adr1 || ""}</div><table>${rows}</table></div>`)
          .addTo(map);
      });

      // Zone click
      map.on("click", "zones-fill", (e) => {
        if (map._pickMode) return;
        if (!e.features?.length) return;
        const p = e.features[0].properties;
        const lsoaId = p.LSOA21CD || p.LSOA11CD || p.DZ2011 || p.geo_code;
        if (lsoaId && map._onZoneClick) map._onZoneClick(lsoaId);
      });

      // Cursor feedback for clickable layers
      for (const lid of ["epc-dom-circles", "epc-nondom-circles", "zones-fill", "energy-assets-circle"]) {
        map.on("mouseenter", lid, () => { if (!map._pickMode) map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", lid, () => { if (!map._pickMode) map.getCanvas().style.cursor = ""; });
      }

      // Carbon popup
      map.on("click", "carbon-fill", (e) => {
        if (map._pickMode) return;
        if (!e.features?.length) return;
        const f = e.features[0].properties;
        const html = Object.entries(f)
          .filter(([k]) => !k.startsWith("_"))
          .slice(0, 8)
          .map(([k, v]) => `<strong>${k}:</strong> ${v}`)
          .join("<br>");
        new mapboxgl.Popup({ maxWidth: "280px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px;line-height:1.6">${html}</div>`)
          .addTo(map);
      });

      map.on("mouseenter", "carbon-fill", () => {
        if (!map._pickMode) map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "carbon-fill", () => {
        if (!map._pickMode) map.getCanvas().style.cursor = "";
      });

      }); // end safe("grid+osm+layers")

      // Location picker click handler (global — fires for any map click)
      map.on("click", (e) => {
        console.log("[MapView] click event — pickMode:", map._pickMode, "onPick:", !!map._onPick);
        if (!map._pickMode || !map._onPick) return;
        const { lng, lat } = e.lngLat;
        console.log("[MapView] pick fired:", { lat, lon: lng });
        map._onPick({ lat, lon: lng });
      });

      // ── Fetch grid data + drawing layers ──
      safe("data-fetch+draw", () => {
      fetch("/grid/topology")
        .then((r) => r.ok ? r.json() : null)
        .then((data) => {
          if (!data) return;
          const flowSrc = map.getSource("grid-flow-lines");
          const nodeSrc = map.getSource("grid-flow-nodes");
          if (flowSrc) flowSrc.setData(data.flows);
          if (nodeSrc) nodeSrc.setData(data.nodes);
        })
        .catch(() => {});

      fetch("/grid/live")
        .then((r) => r.ok ? r.json() : null)
        .then((data) => {
          if (!data) return;
          const icSrc = map.getSource("grid-live-interconnectors");
          const genSrc = map.getSource("grid-live-generation");
          if (icSrc && data.interconnectors) icSrc.setData(data.interconnectors);
          if (genSrc && data.generation) genSrc.setData(data.generation);
          map._gridLiveSummary = data.summary;
        })
        .catch(() => {});

      // Fetch Agile pricing regional map
      fetch("/grid/agile-map")
        .then((r) => r.ok ? r.json() : null)
        .then((data) => {
          if (!data) return;
          const src = map.getSource("agile-pricing");
          if (src) src.setData(data);
        })
        .catch(() => {});

      // ── Drawing layers (nebula.gl-style) ──
      map.addSource("draw-features", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("draw-tentative", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("draw-handles", { type: "geojson", data: { type: "FeatureCollection", features: [] } });

      // Completed features — fill
      map.addLayer({
        id: "draw-fill", type: "fill", source: "draw-features",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: {
          "fill-color": ["case", ["boolean", ["feature-state", "selected"], false], "rgba(0,210,255,0.25)", "rgba(0,255,136,0.15)"],
          "fill-outline-color": "rgba(0,210,255,0.6)",
        },
      });
      // Completed features — line
      map.addLayer({
        id: "draw-line", type: "line", source: "draw-features",
        filter: ["any", ["==", ["geometry-type"], "Polygon"], ["==", ["geometry-type"], "LineString"]],
        paint: { "line-color": "#00d2ff", "line-width": 2, "line-opacity": 0.9 },
      });
      // Completed features — points
      map.addLayer({
        id: "draw-points", type: "circle", source: "draw-features",
        filter: ["==", ["geometry-type"], "Point"],
        paint: { "circle-radius": 6, "circle-color": "#00d2ff", "circle-stroke-width": 2, "circle-stroke-color": "#fff" },
      });

      // Tentative (preview) — fill
      map.addLayer({
        id: "draw-tentative-fill", type: "fill", source: "draw-tentative",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: { "fill-color": "rgba(0,210,255,0.12)", "fill-outline-color": "rgba(0,210,255,0.5)" },
      });
      // Tentative — line
      map.addLayer({
        id: "draw-tentative-line", type: "line", source: "draw-tentative",
        filter: ["any", ["==", ["geometry-type"], "Polygon"], ["==", ["geometry-type"], "LineString"]],
        paint: { "line-color": "#00d2ff", "line-width": 2, "line-dasharray": [4, 3], "line-opacity": 0.7 },
      });
      // Tentative — point
      map.addLayer({
        id: "draw-tentative-point", type: "circle", source: "draw-tentative",
        filter: ["==", ["geometry-type"], "Point"],
        paint: { "circle-radius": 5, "circle-color": "#00d2ff", "circle-opacity": 0.5, "circle-stroke-width": 1.5, "circle-stroke-color": "#fff" },
      });

      // Edit handles
      map.addLayer({
        id: "draw-handles-circles", type: "circle", source: "draw-handles",
        paint: {
          "circle-radius": ["match", ["get", "handleType"], "midpoint", 4, 6],
          "circle-color": ["match", ["get", "handleType"], "first", "#4caf50", "midpoint", "#7c4dff", "#00d2ff"],
          "circle-stroke-width": 2,
          "circle-stroke-color": "#fff",
          "circle-opacity": ["match", ["get", "handleType"], "midpoint", 0.6, 1],
        },
      });

      // Drawing click handler
      map.on("click", (e) => {
        if (map._pickMode) return;
        if (!map._drawMode || map._drawMode === "view") return;

        const { lng, lat } = e.lngLat;

        // Check if clicked an edit handle (must happen before modify's feature selection)
        const handles = map.queryRenderedFeatures(e.point, { layers: ["draw-handles-circles"] });
        let handleIndex = -1;
        if (handles.length > 0) {
          handleIndex = handles[0].properties.positionIndex ?? -1;
          // Midpoint handle — insert vertex
          if (handles[0].properties.handleType === "midpoint" && map._onDrawDragVertex) {
            map._onDrawDragVertex("insert", handles[0].properties.featureIndex, handles[0].properties.insertAfter, [lng, lat]);
            return;
          }
        }

        if (map._drawMode === "modify") {
          // Check if clicked on a drawn feature
          const feats = map.queryRenderedFeatures(e.point, { layers: ["draw-fill", "draw-line", "draw-points"] });
          if (feats.length > 0 && map._onDrawSelectFeature) {
            // Find index by matching properties
            const clickedId = feats[0].properties.created;
            map._onDrawSelectFeature(clickedId);
          }
          return;
        }

        if (map._onDrawClick) map._onDrawClick([lng, lat], handleIndex);
      });

      // Drawing double-click handler
      map.on("dblclick", (e) => {
        if (!map._drawMode || map._drawMode === "view" || map._drawMode === "modify") return;
        e.preventDefault();
        if (map._onDrawDoubleClick) map._onDrawDoubleClick();
      });

      // Drawing mousemove handler
      map.on("mousemove", (e) => {
        if (!map._drawMode || map._drawMode === "view") return;
        const { lng, lat } = e.lngLat;
        if (map._onDrawMouseMove) map._onDrawMouseMove([lng, lat]);
      });

      // Vertex dragging for modify mode
      let draggingVertex = null;
      map.on("mousedown", "draw-handles-circles", (e) => {
        if (map._drawMode !== "modify") return;
        const props = e.features[0]?.properties;
        if (!props || props.handleType === "midpoint") return;
        draggingVertex = { featureIndex: props.featureIndex, vertexIndex: props.vertexIndex };
        map.getCanvas().style.cursor = "grabbing";
        e.preventDefault();
      });
      map.on("mousemove", (e) => {
        if (!draggingVertex) return;
        const { lng, lat } = e.lngLat;
        if (map._onDrawDragVertex) {
          map._onDrawDragVertex("move", draggingVertex.featureIndex, draggingVertex.vertexIndex, [lng, lat]);
        }
      });
      map.on("mouseup", () => {
        if (draggingVertex) {
          draggingVertex = null;
          map.getCanvas().style.cursor = "";
        }
      });

      }); // end safe("data-fetch+draw")

      map.addControl(new mapboxgl.NavigationControl(), "top-left");
      console.log("[MapView] setup complete");
      setMapReady(true);
    };

    map.on("load", setupMap);
    // Fallback if load never fires (e.g. network issues)
    setTimeout(() => { if (!map._setupDone) { console.warn("[MapView] load timeout — forcing setup"); setupMap(); } }, 5000);

    return () => map.remove();
  }, []);

  // Lazy raster layer configs — added on first toggle to avoid slow initial load
  const LAZY_RASTER = useRef({
    ndvi: {
      sourceId: "ndvi", layerId: "ndvi-layer",
      source: () => {
        const d = new Date(Date.now() - 10 * 86400000).toISOString().slice(0, 10);
        return { type: "raster", tiles: [`https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_NDVI_8Day/default/${d}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.png`], tileSize: 256, maxzoom: 9 };
      },
      layer: { type: "raster", paint: { "raster-opacity": 0.65 } },
    },
    satellite: {
      sourceId: "s2-cloudless", layerId: "satellite-layer",
      source: () => ({ type: "raster", tiles: ["https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2024_3857/default/g/{z}/{y}/{x}.jpg"], tileSize: 256, maxzoom: 14 }),
      layer: { type: "raster", paint: { "raster-opacity": 0.85 } },
    },
    lidarDtm: {
      sourceId: "ea-lidar-dtm", layerId: "lidar-dtm-layer",
      source: () => ({ type: "raster", tiles: ["https://environment.data.gov.uk/spatialdata/lidar-composite-digital-terrain-model-dtm-1m/wms?service=WMS&version=1.1.1&request=GetMap&layers=Lidar_Composite_Hillshade_DTM_1m&styles=&srs=EPSG:3857&bbox={bbox-epsg-3857}&width=256&height=256&format=image/png"], tileSize: 256 }),
      layer: { type: "raster", paint: { "raster-opacity": 0.7 } },
    },
    lidarDsm: {
      sourceId: "ea-lidar-dsm", layerId: "lidar-dsm-layer",
      source: () => ({ type: "raster", tiles: ["https://environment.data.gov.uk/spatialdata/lidar-composite-digital-surface-model-last-return-dsm-1m/wms?service=WMS&version=1.1.1&request=GetMap&layers=Lidar_Composite_Hillshade_LZ_DSM_1m&styles=&srs=EPSG:3857&bbox={bbox-epsg-3857}&width=256&height=256&format=image/png"], tileSize: 256 }),
      layer: { type: "raster", paint: { "raster-opacity": 0.7 } },
    },
    landsat: {
      sourceId: "landsat-weld", layerId: "landsat-layer",
      source: () => ({ type: "raster", tiles: ["https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/Landsat_WELD_CorrectedReflectance_TrueColor_Global_Annual/default/2023-01-01/GoogleMapsCompatible_Level12/{z}/{y}/{x}.jpg"], tileSize: 256, maxzoom: 12 }),
      layer: { type: "raster", paint: { "raster-opacity": 0.85 } },
    },
    viirs: {
      sourceId: "viirs-truecolor", layerId: "viirs-layer",
      source: () => {
        const d = new Date(Date.now() - 2 * 86400000).toISOString().slice(0, 10);
        return { type: "raster", tiles: [`https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_SNPP_CorrectedReflectance_TrueColor/default/${d}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg`], tileSize: 256, maxzoom: 9 };
      },
      layer: { type: "raster", paint: { "raster-opacity": 0.8 } },
    },
  });

  // Update layer visibility (with lazy raster loading)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const layerMap = {
      slope: ["slope-tiles"],
      carbon: ["carbon-fill", "carbon-line"],
      la: ["la-line", "la-fill"],
      transport: ["transport-fill", "transport-line"],
      hillshade: ["hillshade"],
      // contours removed (maplibre-contour not available with Mapbox GL)
      environment: ["energy-assets-circle", "energy-assets-echelon", "energy-assets-labels", "energy-assets-sub-labels"],
      gridFlow: ["grid-flow-glow", "grid-flow-core", "grid-flow-dash", "grid-node-glow", "grid-node-circles", "grid-node-labels",
                 "grid-live-ic-glow", "grid-live-ic-core", "grid-live-ic-dash", "grid-live-ic-labels",
                 "grid-live-gen-glow", "grid-live-gen-circles", "grid-live-gen-labels"],
      agilePricing: ["agile-price-glow", "agile-price-labels"],
      demandOverlay: ["demand-glow", "demand-circles", "demand-labels"],
      aerial: ["aerial-layer"],
      epcZones: ["zones-fill"],
      epcDom: ["epc-dom-circles"],
      epcNondom: ["epc-nondom-circles"],
      postcodes: ["postcodes-fill"],
      osmPower: ["osm-power-line-glow", "osm-power-line-core", "osm-power-line-labels",
                 "osm-substation-circles", "osm-substation-labels",
                 "osm-tower-dots", "osm-generator-circles", "osm-generator-labels"],
      ngedSubs: ["nged-sub-circles", "nged-sub-labels"],
      gridCapacity: ["gc-capacity-circles", "gc-capacity-labels", "gc-lines-glow", "gc-lines-core"],
      gridConstraints: ["constraint-zone-fill", "constraint-zone-outline", "constraint-zone-labels"],
      queueDepth: ["queue-depth-circles", "queue-depth-labels"],
      landParcels: ["land-parcels-fill", "land-parcels-outline", "land-parcels-labels", "land-available-markers"],
      demandGsps: ["demand-gsp-circles", "demand-gsp-labels"],
      tecPipeline: ["eso-tec-circles", "eso-tec-labels"],
      repdProjects: ["repd-circles", "repd-labels"],
      geeflowLandUse: ["geeflow-landuse-fill"],
      geeflowOpportunities: ["geeflow-opp-circles", "geeflow-opp-labels"],
      electricityZones: ["electricity-zones-fill", "electricity-zones-line", "electricity-zones-labels"],
      dcCapacity: ["dc-capacity-circles", "dc-capacity-labels"],
      dcFibre: ["dc-fibre-circles"],
      dcIxp: ["dc-ixp-circles", "dc-ixp-labels"],
    };

    // Handle lazy raster layers — add source+layer on first toggle on
    for (const [key, cfg] of Object.entries(LAZY_RASTER.current)) {
      if (layers[key] && !map.getSource(cfg.sourceId)) {
        map.addSource(cfg.sourceId, cfg.source());
        map.addLayer({ id: cfg.layerId, source: cfg.sourceId, ...cfg.layer, layout: { visibility: "visible" } });
      } else if (map.getLayer(cfg.layerId)) {
        map.setLayoutProperty(cfg.layerId, "visibility", layers[key] ? "visible" : "none");
      }
    }

    for (const [key, layerIds] of Object.entries(layerMap)) {
      const vis = layers[key] ? "visible" : "none";
      for (const lid of layerIds) {
        if (map.getLayer(lid)) {
          map.setLayoutProperty(lid, "visibility", vis);
        }
      }
    }
  }, [mapReady, layers]);

  // ── Stability simulation overlay ──
  // When stabilityData changes, update node colors + add stability heatmap source
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded() || !stabilityData?.nodes) return;

    // Build a lookup of stability scores by node name
    const scoreByName = {};
    for (const n of stabilityData.nodes) {
      scoreByName[n.name] = n.stability_score;
    }

    // Update existing grid-flow-nodes data with stability_score property
    const nodeSrc = map.getSource("grid-flow-nodes");
    if (nodeSrc) {
      const currentData = nodeSrc._data || { type: "FeatureCollection", features: [] };
      if (currentData.features) {
        for (const f of currentData.features) {
          const name = f.properties?.name;
          if (name && name in scoreByName) {
            f.properties.stability_score = scoreByName[name];
          }
        }
        nodeSrc.setData(currentData);
      }
    }

    // Update node circle colors to reflect stability (green → yellow → red)
    if (map.getLayer("grid-node-circles")) {
      map.setPaintProperty("grid-node-circles", "circle-color", [
        "case",
        ["has", "stability_score"],
        ["interpolate", ["linear"], ["get", "stability_score"],
          0.0, "#f44336",  // very unstable — red
          0.3, "#ff9800",  // unstable — orange
          0.5, "#ffeb3b",  // marginal — yellow
          0.7, "#8bc34a",  // stable — light green
          1.0, "#4caf50",  // very stable — green
        ],
        // Default (no stability data): original cyan
        ["match", ["get", "node_type"], "gsp", "#00e5ff", "#26c6da"],
      ]);
    }

    // Update glow color too
    if (map.getLayer("grid-node-glow")) {
      map.setPaintProperty("grid-node-glow", "circle-color", [
        "case",
        ["has", "stability_score"],
        ["interpolate", ["linear"], ["get", "stability_score"],
          0.0, "#f44336",
          0.3, "#ff9800",
          0.5, "#ffeb3b",
          0.7, "#8bc34a",
          1.0, "#4caf50",
        ],
        ["match", ["get", "node_type"], "gsp", "#00e5ff", "#00bcd4"],
      ]);
      // Boost glow for unstable nodes
      map.setPaintProperty("grid-node-glow", "circle-opacity", [
        "case",
        ["has", "stability_score"],
        ["interpolate", ["linear"], ["get", "stability_score"],
          0.0, 0.8,   // bright glow for unstable
          0.5, 0.45,
          1.0, 0.3,   // subtle glow for stable
        ],
        0.45,
      ]);
    }
  }, [stabilityData]);

  // Update slope opacity
  useEffect(() => {
    const map = mapRef.current;
    if (map && map.getLayer("slope-tiles")) {
      map.setPaintProperty("slope-tiles", "raster-opacity", slopeOpacity);
    }
  }, [slopeOpacity]);

  // Update EPC layer styling when field selectors change
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    if (map.getLayer("zones-fill") && epcFields.epcZones) {
      const expr = makeColourExpr(epcFields.epcZones, EPC_COLOURS.zones_match, EPC_COLOURS.zones_interp);
      map.setPaintProperty("zones-fill", "fill-color", expr);
    }
    if (map.getLayer("epc-dom-circles") && epcFields.epcDom) {
      const expr = makeColourExpr(epcFields.epcDom, EPC_COLOURS.epc_dom_match, EPC_COLOURS.epc_dom_interp);
      map.setPaintProperty("epc-dom-circles", "circle-color", expr);
    }
    if (map.getLayer("epc-nondom-circles") && epcFields.epcNondom) {
      const expr = makeColourExpr(epcFields.epcNondom, EPC_COLOURS.epc_nondom_match, EPC_COLOURS.epc_nondom_interp);
      map.setPaintProperty("epc-nondom-circles", "circle-color", expr);
    }
    if (map.getLayer("postcodes-fill") && epcFields.postcodes) {
      const expr = makeColourExpr(epcFields.postcodes, EPC_COLOURS.postcodes_match, null);
      map.setPaintProperty("postcodes-fill", "fill-color", expr);
    }
  }, [epcFields]);

  // Pick mode: toggle crosshair cursor and store callbacks on map instance
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    console.log("[MapView] pickMode effect:", pickMode, "onPick:", !!onPick);
    map._pickMode = pickMode;
    map._onPick = onPick;
    map._onZoneClick = onZoneClick;
    map.getCanvas().style.cursor = pickMode ? "crosshair" : "";
  }, [pickMode, onPick, onZoneClick]);

  // Update marker when picked location changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (pickedLocation) {
      if (markerRef.current) {
        markerRef.current.setLngLat([pickedLocation.lon, pickedLocation.lat]);
      } else {
        markerRef.current = new mapboxgl.Marker({ color: "#2e7d32" })
          .setLngLat([pickedLocation.lon, pickedLocation.lat])
          .addTo(map);
      }
    } else if (markerRef.current) {
      markerRef.current.remove();
      markerRef.current = null;
    }
  }, [pickedLocation]);

  // Fetch grid topology + live national grid data when layer toggled on
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !layers.gridFlow) return;
    let cancelled = false;

    // Fetch local feeder topology
    fetch("/grid/topology")
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (cancelled || !data) return;
        const flowSrc = map.getSource("grid-flow-lines");
        const nodeSrc = map.getSource("grid-flow-nodes");
        if (flowSrc) flowSrc.setData(data.flows);
        if (nodeSrc) nodeSrc.setData(data.nodes);
      })
      .catch(() => {});

    // Fetch live national grid data (generation mix, interconnectors)
    fetch("/grid/live")
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (cancelled || !data) return;
        const icSrc = map.getSource("grid-live-interconnectors");
        const genSrc = map.getSource("grid-live-generation");
        if (icSrc && data.interconnectors) icSrc.setData(data.interconnectors);
        if (genSrc && data.generation) genSrc.setData(data.generation);
        // Store summary for potential UI display
        map._gridLiveSummary = data.summary;
      })
      .catch(() => {});

    return () => { cancelled = true; };
  }, [mapReady, layers.gridFlow]);

  // OSM power infrastructure — viewport-based loading with debounce
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !layers.osmPower) return;

    let abortCtrl = new AbortController();
    let timer = null;

    const loadOsmPower = () => {
      abortCtrl.abort();
      abortCtrl = new AbortController();
      const bounds = map.getBounds();
      const zoom = map.getZoom();
      const bbox = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()];

      // Zoom-dependent voltage filter
      let minKv = 0;
      if (zoom < 8) minKv = 275;
      else if (zoom < 10) minKv = 132;
      else if (zoom < 12) minKv = 33;

      // Always fetch lines + substations
      api.grid.osmLines(bbox, minKv).then(data => {
        if (abortCtrl.signal.aborted || !data) return;
        const src = map.getSource("osm-power-lines");
        if (src) src.setData(data);
      }).catch(() => {});

      api.grid.osmSubstations(bbox).then(data => {
        if (abortCtrl.signal.aborted || !data) return;
        const src = map.getSource("osm-power-substations");
        if (src) src.setData(data);
      }).catch(() => {});

      // Towers only at zoom >= 12
      if (zoom >= 12) {
        api.grid.osmTowers(bbox).then(data => {
          if (abortCtrl.signal.aborted || !data) return;
          const src = map.getSource("osm-power-towers");
          if (src) src.setData(data);
        }).catch(() => {});
      } else {
        const src = map.getSource("osm-power-towers");
        if (src) src.setData(EMPTY_FC);
      }

      // Generators + plants at zoom >= 8
      if (zoom >= 8) {
        api.grid.osmGenerators(bbox).then(data => {
          if (abortCtrl.signal.aborted || !data) return;
          const src = map.getSource("osm-power-generators");
          if (src) src.setData(data);
        }).catch(() => {});
        api.grid.osmPlants(bbox).then(data => {
          if (abortCtrl.signal.aborted || !data) return;
          const src = map.getSource("osm-power-plants");
          if (src) src.setData(data);
        }).catch(() => {});
      } else {
        const gs = map.getSource("osm-power-generators");
        if (gs) gs.setData(EMPTY_FC);
        const ps = map.getSource("osm-power-plants");
        if (ps) ps.setData(EMPTY_FC);
      }
    };

    const debouncedLoad = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(loadOsmPower, 300);
    };

    // Load immediately on toggle + on every moveend
    loadOsmPower();
    map.on("moveend", debouncedLoad);

    return () => {
      abortCtrl.abort();
      if (timer) clearTimeout(timer);
      map.off("moveend", debouncedLoad);
      // Clear sources when layer turned off
      for (const id of ["osm-power-lines", "osm-power-substations", "osm-power-towers", "osm-power-generators", "osm-power-plants"]) {
        const src = map.getSource(id);
        if (src) src.setData(EMPTY_FC);
      }
    };
  }, [mapReady, layers.osmPower]);

  // NGED CIM substations — viewport-based loading with debounce
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layers.ngedSubs) return;

    let abortCtrl = new AbortController();
    let timer = null;

    const loadNgedSubs = () => {
      if (abortCtrl.signal.aborted) return;
      const bounds = map.getBounds();
      const bbox = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()];

      api.grid.ngedSubstations(bbox).then(data => {
        if (abortCtrl.signal.aborted || !data) return;
        const src = map.getSource("nged-substations");
        if (src) src.setData(data);
      }).catch(() => {});
    };

    const debouncedLoad = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(loadNgedSubs, 300);
    };

    loadNgedSubs();
    map.on("moveend", debouncedLoad);

    return () => {
      abortCtrl.abort();
      if (timer) clearTimeout(timer);
      map.off("moveend", debouncedLoad);
      const src = map.getSource("nged-substations");
      if (src) src.setData(EMPTY_FC);
    };
  }, [layers.ngedSubs]);

  // ESO TEC Pipeline — viewport-based loading with debounce
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layers.tecPipeline) return;

    let abortCtrl = new AbortController();
    let timer = null;

    const loadTec = () => {
      if (abortCtrl.signal.aborted) return;
      const bounds = map.getBounds();
      const bbox = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()];

      api.eso.tecGeojson(bbox).then(data => {
        if (abortCtrl.signal.aborted || !data) return;
        const src = map.getSource("eso-tec-projects");
        if (src) src.setData(data);
      }).catch(() => {});
    };

    const debouncedLoad = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(loadTec, 300);
    };

    loadTec();
    map.on("moveend", debouncedLoad);

    return () => {
      abortCtrl.abort();
      if (timer) clearTimeout(timer);
      map.off("moveend", debouncedLoad);
      const src = map.getSource("eso-tec-projects");
      if (src) src.setData(EMPTY_FC);
    };
  }, [layers.tecPipeline]);

  // REPD Projects — viewport-based loading with zoom-dependent min capacity
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layers.repdProjects) return;

    let abortCtrl = new AbortController();
    let timer = null;

    const loadRepd = () => {
      if (abortCtrl.signal.aborted) return;
      const bounds = map.getBounds();
      const zoom = map.getZoom();
      const bbox = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()];

      // Zoom-dependent filtering to avoid clutter at low zoom
      let minMw = 0;
      if (zoom < 7) minMw = 50;
      else if (zoom < 9) minMw = 10;
      else if (zoom < 11) minMw = 1;

      api.repd.geojson(bbox, null, null, minMw).then(data => {
        if (abortCtrl.signal.aborted || !data) return;
        const src = map.getSource("repd-projects");
        if (src) src.setData(data);
      }).catch(() => {});
    };

    const debouncedLoad = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(loadRepd, 300);
    };

    loadRepd();
    map.on("moveend", debouncedLoad);

    return () => {
      abortCtrl.abort();
      if (timer) clearTimeout(timer);
      map.off("moveend", debouncedLoad);
      const src = map.getSource("repd-projects");
      if (src) src.setData(EMPTY_FC);
    };
  }, [layers.repdProjects]);

  // Grid connection capacity map — viewport-based loading
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layers.gridCapacity) return;

    let abortCtrl = new AbortController();
    let timer = null;

    const loadCapacity = async () => {
      const bounds = map.getBounds();
      const bbox = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()];

      try {
        const [subsData, linesData] = await Promise.all([
          api.grid.capacityMap(bbox),
          api.grid.gridLines(bbox),
        ]);
        if (abortCtrl.signal.aborted) return;
        const subsSrc = map.getSource("gc-capacity-subs");
        if (subsSrc && subsData) subsSrc.setData(subsData);
        const linesSrc = map.getSource("gc-grid-lines");
        if (linesSrc && linesData) linesSrc.setData(linesData);
      } catch (err) {
        if (err.name !== "AbortError") console.warn("Grid capacity load error:", err);
      }
    };

    const debouncedLoad = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(loadCapacity, 300);
    };

    loadCapacity();
    map.on("moveend", debouncedLoad);

    return () => {
      abortCtrl.abort();
      if (timer) clearTimeout(timer);
      map.off("moveend", debouncedLoad);
      const s1 = map.getSource("gc-capacity-subs");
      if (s1) s1.setData(EMPTY_FC);
      const s2 = map.getSource("gc-grid-lines");
      if (s2) s2.setData(EMPTY_FC);
    };
  }, [layers.gridCapacity]);

  // Grid constraint overlay — fetch boundary zones with congestion risk
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !layers.gridConstraints) return;
    let cancelled = false;

    fetch("/api/grid/constraints?hours_ahead=48")
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (cancelled || !data) return;
        const src = map.getSource("grid-constraints");
        if (src) src.setData({ type: "FeatureCollection", features: data.features || [] });
      })
      .catch(() => {});

    return () => {
      cancelled = true;
      const src = map.getSource("grid-constraints");
      if (src) src.setData(EMPTY_FC);
    };
  }, [mapReady, layers.gridConstraints]);

  // Queue depth per substation — fetch ECR queue metrics
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !layers.queueDepth) return;
    let cancelled = false;

    fetch("/api/grid/queue-depth")
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (cancelled || !data) return;
        const src = map.getSource("queue-depth");
        if (src) src.setData(data);
      })
      .catch(() => {});

    return () => {
      cancelled = true;
      const src = map.getSource("queue-depth");
      if (src) src.setData(EMPTY_FC);
    };
  }, [mapReady, layers.queueDepth]);

  // Land registry parcels — viewport-based loading (zoom 12+)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !layers.landParcels) return;
    let timer = null;

    const loadParcels = async () => {
      if (map.getZoom() < 12) {
        const src = map.getSource("land-parcels");
        if (src) src.setData(EMPTY_FC);
        return;
      }
      const bounds = map.getBounds();
      const bbox = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()];
      try {
        const data = await api.land.parcels(bbox);
        if (data) {
          const src = map.getSource("land-parcels");
          if (src) src.setData(data);
        }
      } catch (err) {
        console.warn("Land parcels load error:", err);
      }
    };

    const debouncedLoad = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(loadParcels, 400);
    };

    loadParcels();
    map.on("moveend", debouncedLoad);

    return () => {
      if (timer) clearTimeout(timer);
      map.off("moveend", debouncedLoad);
      const src = map.getSource("land-parcels");
      if (src) src.setData(EMPTY_FC);
    };
  }, [mapReady, layers.landParcels]);

  // DC capacity map — viewport-based loading
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layers.dcCapacity) return;

    let abortCtrl = new AbortController();
    let timer = null;

    const loadDC = async () => {
      const bounds = map.getBounds();
      const bbox = `west=${bounds.getWest()}&south=${bounds.getSouth()}&east=${bounds.getEast()}&north=${bounds.getNorth()}`;
      try {
        const res = await fetch(`/api/dc/capacity-map?profile=colocation&min_headroom_mw=5&${bbox}`);
        if (abortCtrl.signal.aborted || !res.ok) return;
        const data = await res.json();
        const src = map.getSource("dc-capacity");
        if (src && data) src.setData(data);
      } catch (err) {
        if (err.name !== "AbortError") console.warn("DC capacity load error:", err);
      }
    };

    const debouncedLoad = () => { if (timer) clearTimeout(timer); timer = setTimeout(loadDC, 300); };
    loadDC();
    map.on("moveend", debouncedLoad);

    return () => {
      abortCtrl.abort();
      if (timer) clearTimeout(timer);
      map.off("moveend", debouncedLoad);
      const s = map.getSource("dc-capacity");
      if (s) s.setData(EMPTY_FC);
    };
  }, [layers.dcCapacity]);

  // DC fibre POPs — load on toggle
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layers.dcFibre) return;
    let cancel = false;
    (async () => {
      const lat = map.getCenter().lat, lon = map.getCenter().lng;
      try {
        const res = await fetch(`/api/dc/infrastructure?lat=${lat}&lon=${lon}&radius_km=100`);
        if (cancel || !res.ok) return;
        const data = await res.json();
        const fc = { type: "FeatureCollection", features: (data.fibre_pops || []).map(p => ({
          type: "Feature", geometry: { type: "Point", coordinates: [p.lon, p.lat] },
          properties: { name: p.name, operator: p.operator },
        })) };
        const src = map.getSource("dc-fibre");
        if (src) src.setData(fc);
      } catch (e) { console.warn("DC fibre load:", e); }
    })();
    return () => { cancel = true; const s = map.getSource("dc-fibre"); if (s) s.setData(EMPTY_FC); };
  }, [layers.dcFibre]);

  // DC IXP nodes — load on toggle
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layers.dcIxp) return;
    let cancel = false;
    (async () => {
      const lat = map.getCenter().lat, lon = map.getCenter().lng;
      try {
        const res = await fetch(`/api/dc/infrastructure?lat=${lat}&lon=${lon}&radius_km=500`);
        if (cancel || !res.ok) return;
        const data = await res.json();
        const fc = { type: "FeatureCollection", features: (data.ixp_nodes || []).map(p => ({
          type: "Feature", geometry: { type: "Point", coordinates: [p.lon, p.lat] },
          properties: { name: p.name, participants: p.participants },
        })) };
        const src = map.getSource("dc-ixp");
        if (src) src.setData(fc);
      } catch (e) { console.warn("DC IXP load:", e); }
    })();
    return () => { cancel = true; const s = map.getSource("dc-ixp"); if (s) s.setData(EMPTY_FC); };
  }, [layers.dcIxp]);

  // Grid connection — highlight selected candidate substation
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const src = map.getSource("gc-highlight-sub");
    if (!src) return;

    if (gridHighlightSub && gridHighlightSub.lon != null && gridHighlightSub.lat != null) {
      src.setData({
        type: "FeatureCollection",
        features: [{
          type: "Feature",
          geometry: { type: "Point", coordinates: [gridHighlightSub.lon, gridHighlightSub.lat] },
          properties: { name: gridHighlightSub.name || "" },
        }],
      });
    } else {
      src.setData(EMPTY_FC);
    }
  }, [gridHighlightSub]);

  // Demand GSPs — load GSP locations with utilisation
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layers.demandGsps) return;

    let cancelled = false;
    (async () => {
      try {
        const data = await api.demand.summary();
        if (cancelled || !data?.profiles) return;
        const fc = {
          type: "FeatureCollection",
          features: data.profiles.map(p => ({
            type: "Feature",
            geometry: { type: "Point", coordinates: [p.lon, p.lat] },
            properties: {
              gsp_id: p.gsp_id,
              gsp_name: p.gsp_name,
              dno: p.dno,
              peak_demand_mw: p.peak_demand_mw || p.recent_peak_mw,
              capacity_mw: p.capacity_mw,
              utilisation: p.utilisation || (p.peak_demand_mw / p.capacity_mw),
            },
          })),
        };
        const src = map.getSource("demand-gsps");
        if (src) src.setData(fc);
      } catch (err) {
        console.warn("Demand GSP load error:", err);
      }
    })();

    return () => {
      cancelled = true;
      const src = map.getSource("demand-gsps");
      if (src) src.setData(EMPTY_FC);
    };
  }, [layers.demandGsps]);

  // Electricity zones — load zone boundaries + fetch live carbon intensity data
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layers.electricityZones) return;

    let cancelled = false;
    let refreshTimer = null;

    const refreshElectricityZones = async () => {
      try {
        const data = await api.electricity.carbonIntensityAll();
        if (cancelled || !data?.zones) return;

        // Merge live data into GeoJSON features
        const enriched = {
          ...electricityZonesGeoJSON,
          features: electricityZonesGeoJSON.features.map(f => {
            const zone = f.properties.zoneName;
            const live = data.zones[zone];
            if (live && !live.error) {
              return {
                ...f,
                properties: {
                  ...f.properties,
                  carbonIntensity: live.carbonIntensity,
                  fossilFreePercentage: live.fossilFreePercentage,
                  renewablePercentage: live.renewablePercentage,
                },
              };
            }
            return f;
          }),
        };

        const src = map.getSource("electricity-zones");
        if (src) src.setData(enriched);
      } catch (err) {
        console.warn("Failed to fetch electricity zone data:", err);
        // Still show boundaries without live data
        const src = map.getSource("electricity-zones");
        if (src) src.setData(electricityZonesGeoJSON);
      }
    };

    // Load immediately + set up 5-minute auto-refresh
    refreshElectricityZones();
    refreshTimer = setInterval(refreshElectricityZones, 300000);

    return () => {
      cancelled = true;
      if (refreshTimer) clearInterval(refreshTimer);
      const src = map.getSource("electricity-zones");
      if (src) src.setData(EMPTY_FC);
    };
  }, [layers.electricityZones]);

  // Animate dash offset + node pulse when grid flow layer is visible
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !layers.gridFlow) return;
    let animId;
    let step = 0;
    const animate = (timestamp) => {
      step = (step + 1) % 1000;
      if (!map.isStyleLoaded()) { animId = requestAnimationFrame(animate); return; }

      // Dash animation
      const dashLen = 3;
      const gapLen = 4;
      const offset = (step * 0.15) % (dashLen + gapLen);
      const dashArr = [offset, gapLen, Math.max(dashLen - offset, 0.01)];
      if (map.getLayer("grid-flow-dash")) {
        map.setPaintProperty("grid-flow-dash", "line-dasharray", dashArr);
      }
      if (map.getLayer("grid-live-ic-dash")) {
        map.setPaintProperty("grid-live-ic-dash", "line-dasharray", dashArr);
      }

      // Node pulse animation (breathing glow)
      const pulse = 0.3 + 0.15 * Math.sin(timestamp / 800);
      if (map.getLayer("grid-node-glow")) {
        map.setPaintProperty("grid-node-glow", "circle-opacity", pulse);
      }

      // Flow glow pulse (subtle)
      const flowPulse = 0.4 + 0.1 * Math.sin(timestamp / 1200);
      if (map.getLayer("grid-flow-glow")) {
        map.setPaintProperty("grid-flow-glow", "line-opacity", flowPulse);
      }

      animId = requestAnimationFrame(animate);
    };
    animId = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animId);
  }, [mapReady, layers.gridFlow]);

  // Sync chat layers to map
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    // Track which chat layer IDs currently exist on the map
    const existingIds = new Set();
    for (const src of Object.keys(map.style?.sourceCaches || {})) {
      if (src.startsWith("chat-")) existingIds.add(src);
    }

    const wantedIds = new Set(chatLayers.map(l => l.id));

    // Remove layers/sources no longer needed
    for (const id of existingIds) {
      if (!wantedIds.has(id)) {
        if (map.getLayer(id + "-labels")) map.removeLayer(id + "-labels");
        if (map.getLayer(id + "-outline")) map.removeLayer(id + "-outline");
        if (map.getLayer(id + "-layer")) map.removeLayer(id + "-layer");
        if (map.getSource(id)) map.removeSource(id);
      }
    }

    // Add or update chat layers
    for (const cl of chatLayers) {
      const srcId = cl.id;
      const layerId = cl.id + "-layer";
      const geojson = cl.geojson || { type: "FeatureCollection", features: [] };
      const style = cl.style || {};

      if (map.getSource(srcId)) {
        map.getSource(srcId).setData(geojson);
      } else {
        map.addSource(srcId, { type: "geojson", data: geojson });

        const layerType = cl.layer_type || "circle";
        const color = cl.color || "#00e5ff";
        const opacity = style.opacity ?? 0.85;

        if (layerType === "circle") {
          map.addLayer({
            id: layerId, type: "circle", source: srcId,
            paint: {
              "circle-radius": style.radius || 6,
              "circle-color": (style.color_field && style.color_map)
                ? ["match", ["get", style.color_field],
                    ...Object.entries(style.color_map).flat(),
                    color]
                : color,
              "circle-stroke-width": 1, "circle-stroke-color": "#fff",
              "circle-opacity": opacity,
            },
          });
        } else if (layerType === "fill") {
          const fillColor = Array.isArray(color) ? color : color;
          const outlineColor = Array.isArray(color) ? "#333" : color;
          map.addLayer({
            id: layerId, type: "fill", source: srcId,
            paint: { "fill-color": fillColor, "fill-opacity": style.opacity ?? 0.35, "fill-outline-color": outlineColor },
          });
          const hasLabels = geojson.features?.some(f => f.properties?.label);
          if (hasLabels) {
            map.addLayer({
              id: srcId + "-labels", type: "symbol", source: srcId,
              layout: { "text-field": ["get", "label"], "text-size": 10, "text-allow-overlap": false, "text-padding": 4 },
              paint: { "text-color": "#fff", "text-halo-color": "#000", "text-halo-width": 1 },
            });
          }

        } else if (layerType === "fill-pattern") {
          // Hatched / patterned fill for constraint zones (flood, AONB, green belt, etc.)
          const patternName = style.pattern || "hatch-blue";
          map.addLayer({
            id: layerId, type: "fill", source: srcId,
            paint: {
              "fill-pattern": patternName,
              "fill-opacity": style.opacity ?? 0.5,
            },
          });
          // Add outline
          map.addLayer({
            id: srcId + "-outline", type: "line", source: srcId,
            paint: { "line-color": color, "line-width": 1.5, "line-opacity": 0.7 },
          });
          const hasLabels = geojson.features?.some(f => f.properties?.label);
          if (hasLabels) {
            map.addLayer({
              id: srcId + "-labels", type: "symbol", source: srcId,
              layout: { "text-field": ["get", "label"], "text-size": 11, "text-font": ["Open Sans Bold", "Arial Unicode MS Bold"], "text-allow-overlap": false, "text-padding": 6 },
              paint: { "text-color": color, "text-halo-color": "#fff", "text-halo-width": 1.5 },
            });
          }

        } else if (layerType === "symbol") {
          // Icon-based point layer (substations, exchanges, hazards, etc.)
          const iconName = style.icon || "icon-substation";
          const iconPrefix = iconName.startsWith("icon-") ? iconName : `icon-${iconName}`;
          // If data-driven icon: use color_field to pick icon per feature
          const iconImage = (style.icon_field)
            ? ["concat", "icon-", ["get", style.icon_field]]
            : iconPrefix;
          map.addLayer({
            id: layerId, type: "symbol", source: srcId,
            layout: {
              "icon-image": iconImage,
              "icon-size": style.icon_size || 0.55,
              "icon-allow-overlap": true,
              "icon-anchor": "center",
              "text-field": style.label_field ? ["get", style.label_field] : "",
              "text-size": 10,
              "text-offset": [0, 1.8],
              "text-anchor": "top",
              "text-optional": true,
            },
            paint: {
              "text-color": "#333",
              "text-halo-color": "#fff",
              "text-halo-width": 1,
            },
          });

        } else if (layerType === "line") {
          // Enhanced line with optional dashing and data-driven color
          const lineColor = (style.color_field && style.color_map)
            ? ["match", ["get", style.color_field],
                ...Object.entries(style.color_map).flat(),
                color]
            : color;
          const paintProps = {
            "line-color": lineColor,
            "line-width": style.line_width || 2,
            "line-opacity": style.opacity ?? 0.8,
          };
          const layoutProps = {};
          if (style.dash_array) {
            paintProps["line-dasharray"] = style.dash_array;
          }
          if (style.line_cap) {
            layoutProps["line-cap"] = style.line_cap;
          }
          map.addLayer({
            id: layerId, type: "line", source: srcId,
            paint: paintProps,
            layout: layoutProps,
          });

        } else if (layerType === "heatmap") {
          map.addLayer({
            id: layerId, type: "heatmap", source: srcId,
            paint: { "heatmap-radius": 20, "heatmap-opacity": 0.7, "heatmap-intensity": 1 },
          });
        }
      }
    }
  }, [chatLayers]);

  // Sync drawing state to map sources
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded() || !drawState) return;

    // Update callbacks on map instance
    map._drawMode = drawState.mode;
    map._onDrawClick = onDrawClick;
    map._onDrawDoubleClick = onDrawDoubleClick;
    map._onDrawMouseMove = onDrawMouseMove;
    map._onDrawSelectFeature = onDrawSelectFeature;
    map._onDrawDragVertex = onDrawDragVertex;

    // Disable double-click zoom while drawing (prevents zoom when finishing shapes)
    const drawing = drawState.mode && drawState.mode !== "view" && drawState.mode !== "modify";
    if (drawing) {
      map.doubleClickZoom.disable();
    } else {
      map.doubleClickZoom.enable();
    }

    // Update features source
    const featSrc = map.getSource("draw-features");
    if (featSrc) featSrc.setData(drawState.features);

    // Update tentative guide source
    const tentSrc = map.getSource("draw-tentative");
    if (tentSrc) {
      const guides = getTentativeGuides(drawState);
      const tentativeOnly = {
        type: "FeatureCollection",
        features: guides.features.filter(f => f.properties.guideType === "tentative"),
      };
      tentSrc.setData(tentativeOnly);

      // Handles source
      const handleSrc = map.getSource("draw-handles");
      if (handleSrc) {
        const editHandles = guides.features.filter(f => f.properties.guideType === "editHandle");
        const modifyHandles = getModifyGuides(drawState).features;
        handleSrc.setData({
          type: "FeatureCollection",
          features: [...editHandles, ...modifyHandles],
        });
      }
    }

    // Set cursor (getCursor returns "" for VIEW mode, which resets to default)
    if (!pickMode) {
      map.getCanvas().style.cursor = getCursor(drawState.mode);
    }
  }, [drawState, pickMode]);

  return (
    <div ref={containerRef} className={`mapContainer ${pickMode ? "pick-mode" : ""}`} />
  );
}
