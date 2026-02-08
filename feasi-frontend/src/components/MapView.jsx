import React, { useEffect, useRef, useCallback } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Protocol } from "pmtiles";
import mlcontour from "maplibre-contour";
import { getTentativeGuides, getModifyGuides, getCursor } from "../lib/draw-modes";
import { useSite } from "../SiteContext";
import api from "../services/api";

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
  drawState, onDrawClick, onDrawDoubleClick, onDrawMouseMove, onDrawSelectFeature, onDrawDragVertex }) {
  const { stabilityData } = useSite();
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);

  useEffect(() => {
    if (!protocolAdded) {
      const protocol = new Protocol();
      maplibregl.addProtocol("pmtiles", protocol.tile);
      protocolAdded = true;
    }

    // Create contour source using maplibre-contour
    const demUrl = `${PROXY}/DTM.pmtiles`.replace("pmtiles://", "");
    const contourSource = new mlcontour.DemSource({
      url: demUrl,
      encoding: "mapbox",
      maxzoom: 14,
      worker: true,
    });
    contourSource.setupMaplibre(maplibregl);

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          // Light basemap
          "carto-light": {
            type: "raster",
            tiles: ["https://basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}@2x.png"],
            tileSize: 256,
            attribution: "&copy; CartoDB &copy; OpenStreetMap",
          },
          "carto-labels": {
            type: "raster",
            tiles: ["https://basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}@2x.png"],
            tileSize: 256,
          },
          terrainSource: {
            type: "raster-dem",
            url: `${PROXY}/DTM.pmtiles`,
            tileSize: 512,
            minzoom: 0,
            maxzoom: 14,
            encoding: "mapbox",
            attribution: '<a href="https://doi.org/10.1177/23998083251401613">GBDEM</a>',
          },
          hillshadeSource: {
            type: "raster-dem",
            url: `${PROXY}/DTM.pmtiles`,
            tileSize: 512,
            minzoom: 0,
            maxzoom: 11,
            encoding: "mapbox",
          },
          contourSourceFeet: {
            type: "vector",
            tiles: [
              contourSource.contourProtocolUrl({
                multiplier: 1,
                overzoom: 1,
                thresholds: { 11: [50, 200], 12: [25, 100], 13: [10, 50], 14: [5, 25] },
                elevationKey: "ele",
                levelKey: "level",
                contourLayer: "contours",
              }),
            ],
            maxzoom: 16,
          },
        },
        layers: [
          { id: "light-base", type: "raster", source: "carto-light" },
          {
            id: "hillshade",
            type: "hillshade",
            source: "hillshadeSource",
            paint: {
              "hillshade-shadow-color": "#8a9a8a",
              "hillshade-highlight-color": "#ffffff",
              "hillshade-accent-color": "#2e7d32",
              "hillshade-illumination-anchor": "map",
              "hillshade-exaggeration": 0.4,
            },
          },
        ],
        terrain: {
          source: "terrainSource",
          exaggeration: 2.0,
        },
      },
      center: [-1.5, 52.5],
      zoom: 7,
      pitch: 45,
      bearing: -10,
      maxPitch: 85,
    });

    mapRef.current = map;

    map.on("load", () => {
      // ── Contour lines (green glow) ──
      map.addLayer({
        id: "contour-lines",
        type: "line",
        source: "contourSourceFeet",
        "source-layer": "contours",
        paint: {
          "line-color": [
            "interpolate", ["linear"], ["get", "level"],
            0, "rgba(46, 125, 50, 0.2)",
            1, "rgba(46, 125, 50, 0.5)",
          ],
          "line-width": ["interpolate", ["linear"], ["get", "level"], 0, 0.5, 1, 1.2],
          "line-blur": 1,
        },
        layout: {
          visibility: layers.contours !== false ? "visible" : "none",
        },
        minzoom: 9,
      });

      // Contour labels
      map.addLayer({
        id: "contour-labels",
        type: "symbol",
        source: "contourSourceFeet",
        "source-layer": "contours",
        filter: ["==", ["get", "level"], 1],
        paint: {
          "text-color": "rgba(46, 125, 50, 0.7)",
          "text-halo-color": "rgba(255, 255, 255, 0.8)",
          "text-halo-width": 1.5,
        },
        layout: {
          "symbol-placement": "line",
          "text-field": ["concat", ["get", "ele"], "m"],
          "text-font": ["Noto Sans Regular"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 11, 8, 14, 10],
          visibility: layers.contours !== false ? "visible" : "none",
        },
        minzoom: 11,
      });

      // Labels layer (above contours, below data layers)
      map.addLayer({ id: "base-labels", type: "raster", source: "carto-labels" });

      // ── ESRI Aerial imagery (inserted early so data layers draw on top) ──
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
        new maplibregl.Popup({ maxWidth: "260px" })
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

      // PBCC Carbon vector overlay
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

      // ── Grid flow network (FlowmapBlue-style) — on top of all data layers ──
      map.addSource("grid-flow-lines", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("grid-flow-nodes", { type: "geojson", data: { type: "FeatureCollection", features: [] } });

      // Live national grid sources
      map.addSource("grid-live-interconnectors", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("grid-live-generation", { type: "geojson", data: { type: "FeatureCollection", features: [] } });

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
        new maplibregl.Popup({ maxWidth: "220px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${p.label}</strong><br/>Agile price: <strong>${p.price_pence}p/kWh</strong><br/>Category: ${p.price_category}</div>`)
          .addTo(map);
      });
      map.on("mouseenter", "agile-price-glow", () => { if (!map._pickMode) map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "agile-price-glow", () => { if (!map._pickMode) map.getCanvas().style.cursor = ""; });

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

      // Grid flow click popups
      map.on("click", "grid-flow-core", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        const pct = ((p.utilization || 0) * 100).toFixed(1);
        const vkv = p.voltage_kv ? ` (${p.voltage_kv}kV)` : "";
        new maplibregl.Popup({ maxWidth: "260px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${p.from_node} → ${p.to_node}</strong>${vkv}<br/>Flow: ${p.flow_mw} MW<br/>Capacity: ${p.capacity_mva} MVA<br/>Utilization: <strong>${pct}%</strong></div>`)
          .addTo(map);
      });
      map.on("click", "grid-node-circles", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        const name = p.name || p.node_id;
        const vkv = p.voltage_kv ? `${p.voltage_kv}kV ` : "";
        new maplibregl.Popup({ maxWidth: "220px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${name}</strong><br/>${vkv}${(p.node_type || "").toUpperCase()}<br/>Demand: ${p.demand_mw || p.load_mw || 0} MW</div>`)
          .addTo(map);
      });
      // Live grid click popups
      map.on("click", "grid-live-ic-core", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        new maplibregl.Popup({ maxWidth: "240px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px"><strong>${p.label}</strong><br/>Flow: ${p.flow_mw} MW (${p.direction})</div>`)
          .addTo(map);
      });
      map.on("click", "grid-live-gen-circles", (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        new maplibregl.Popup({ maxWidth: "200px" })
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
        new maplibregl.Popup({ maxWidth: "320px" })
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
        new maplibregl.Popup({ maxWidth: "300px" })
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
        new maplibregl.Popup({ maxWidth: "280px" })
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

      // Location picker click handler
      map.on("click", (e) => {
        if (!map._pickMode || !map._onPick) return;
        const { lng, lat } = e.lngLat;
        map._onPick({ lat, lon: lng });
      });

      // ── Fetch grid data immediately on load ──
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

      map.addControl(new maplibregl.NavigationControl(), "top-left");
      map.addControl(
        new maplibregl.TerrainControl({ source: "terrainSource", exaggeration: 2.0 }),
        "top-right"
      );
    });

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
    if (!map || !map.isStyleLoaded()) return;

    const layerMap = {
      slope: ["slope-tiles"],
      carbon: ["carbon-fill", "carbon-line"],
      la: ["la-line", "la-fill"],
      transport: ["transport-fill", "transport-line"],
      hillshade: ["hillshade"],
      contours: ["contour-lines", "contour-labels"],
      environment: ["energy-assets-circle", "energy-assets-echelon", "energy-assets-labels", "energy-assets-sub-labels"],
      gridFlow: ["grid-flow-glow", "grid-flow-core", "grid-flow-dash", "grid-node-glow", "grid-node-circles", "grid-node-labels",
                 "grid-live-ic-glow", "grid-live-ic-core", "grid-live-ic-dash", "grid-live-ic-labels",
                 "grid-live-gen-glow", "grid-live-gen-circles", "grid-live-gen-labels"],
      agilePricing: ["agile-price-glow", "agile-price-labels"],
      aerial: ["aerial-layer"],
      epcZones: ["zones-fill"],
      epcDom: ["epc-dom-circles"],
      epcNondom: ["epc-nondom-circles"],
      postcodes: ["postcodes-fill"],
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
  }, [layers]);

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
        markerRef.current = new maplibregl.Marker({ color: "#2e7d32" })
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
    if (!map || !layers.gridFlow) return;
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
  }, [layers.gridFlow]);

  // Animate dash offset + node pulse when grid flow layer is visible
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layers.gridFlow) return;
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
  }, [layers.gridFlow]);

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

  return <div ref={containerRef} className={`mapContainer ${pickMode ? "pick-mode" : ""}`} />;
}
