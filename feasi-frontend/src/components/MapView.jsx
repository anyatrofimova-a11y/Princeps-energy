import React, { useEffect, useRef, useCallback } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Protocol } from "pmtiles";

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

export default function MapView({ slopeOpacity = 0.6, layers = {}, pickMode = false, onPick, pickedLocation, onZoneClick, epcFields = {} }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);

  useEffect(() => {
    if (!protocolAdded) {
      const protocol = new Protocol();
      maplibregl.addProtocol("pmtiles", protocol.tile);
      protocolAdded = true;
    }

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "&copy; OpenStreetMap contributors",
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
        },
        layers: [
          { id: "osm", type: "raster", source: "osm" },
          {
            id: "hillshade",
            type: "hillshade",
            source: "hillshadeSource",
            paint: {
              "hillshade-shadow-color": "#473B24",
              "hillshade-illumination-anchor": "map",
              "hillshade-exaggeration": 0.6,
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
        paint: {
          "fill-color": "#00bcd4",
          "fill-opacity": 0.25,
        },
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

      // ── Retrofit / EPC layers (from PBCC Retrofit Explorer) ──

      // Neighbourhood zones (LSOA-level EPC aggregates)
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

      // ── EPC click popups ──

      // Domestic EPC popup
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
          .setHTML(`<div style="font-size:11px"><h4 style="margin:0 0 4px;font-size:13px">Domestic EPC</h4><div style="font-size:10px;color:#666;margin-bottom:4px">${p.addr || ""}</div><table>${rows}</table></div>`)
          .addTo(map);
      });

      // Non-domestic EPC popup
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
          .setHTML(`<div style="font-size:11px"><h4 style="margin:0 0 4px;font-size:13px">Non-Domestic EPC</h4><div style="font-size:10px;color:#666;margin-bottom:4px">${p.adr2 || p.adr1 || ""}</div><table>${rows}</table></div>`)
          .addTo(map);
      });

      // Zone click → pass LSOA ID to parent for EPC summary
      map.on("click", "zones-fill", (e) => {
        if (map._pickMode) return;
        if (!e.features?.length) return;
        const p = e.features[0].properties;
        const lsoaId = p.LSOA21CD || p.LSOA11CD || p.DZ2011 || p.geo_code;
        if (lsoaId && map._onZoneClick) map._onZoneClick(lsoaId);
      });

      // Cursor feedback for EPC layers
      for (const lid of ["epc-dom-circles", "epc-nondom-circles", "zones-fill"]) {
        map.on("mouseenter", lid, () => { if (!map._pickMode) map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", lid, () => { if (!map._pickMode) map.getCanvas().style.cursor = ""; });
      }

      // Carbon popup on click (only when not in pick mode)
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

      // Cursor feedback (only when not in pick mode)
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

      map.addControl(new maplibregl.NavigationControl(), "top-left");
      map.addControl(
        new maplibregl.TerrainControl({ source: "terrainSource", exaggeration: 2.0 }),
        "top-right"
      );
    });

    return () => map.remove();
  }, []);

  // Update layer visibility
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const layerMap = {
      slope: ["slope-tiles"],
      carbon: ["carbon-fill", "carbon-line"],
      la: ["la-line", "la-fill"],
      transport: ["transport-fill", "transport-line"],
      hillshade: ["hillshade"],
      epcZones: ["zones-fill"],
      epcDom: ["epc-dom-circles"],
      epcNondom: ["epc-nondom-circles"],
      postcodes: ["postcodes-fill"],
    };

    for (const [key, layerIds] of Object.entries(layerMap)) {
      const vis = layers[key] ? "visible" : "none";
      for (const lid of layerIds) {
        if (map.getLayer(lid)) {
          map.setLayoutProperty(lid, "visibility", vis);
        }
      }
    }
  }, [layers]);

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

    // Zones
    if (map.getLayer("zones-fill") && epcFields.epcZones) {
      const expr = makeColourExpr(epcFields.epcZones, EPC_COLOURS.zones_match, EPC_COLOURS.zones_interp);
      map.setPaintProperty("zones-fill", "fill-color", expr);
    }
    // Domestic EPC
    if (map.getLayer("epc-dom-circles") && epcFields.epcDom) {
      const expr = makeColourExpr(epcFields.epcDom, EPC_COLOURS.epc_dom_match, EPC_COLOURS.epc_dom_interp);
      map.setPaintProperty("epc-dom-circles", "circle-color", expr);
    }
    // Non-domestic EPC
    if (map.getLayer("epc-nondom-circles") && epcFields.epcNondom) {
      const expr = makeColourExpr(epcFields.epcNondom, EPC_COLOURS.epc_nondom_match, EPC_COLOURS.epc_nondom_interp);
      map.setPaintProperty("epc-nondom-circles", "circle-color", expr);
    }
    // Postcodes
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

  // Show/update marker at picked location
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (pickedLocation) {
      if (markerRef.current) {
        markerRef.current.setLngLat([pickedLocation.lon, pickedLocation.lat]);
      } else {
        markerRef.current = new maplibregl.Marker({ color: "#4caf50" })
          .setLngLat([pickedLocation.lon, pickedLocation.lat])
          .addTo(map);
      }
    } else if (markerRef.current) {
      markerRef.current.remove();
      markerRef.current = null;
    }
  }, [pickedLocation]);

  return <div ref={containerRef} className={`mapContainer ${pickMode ? "pick-mode" : ""}`} />;
}
