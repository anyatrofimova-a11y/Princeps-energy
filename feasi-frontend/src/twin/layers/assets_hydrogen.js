/**
 * Twin layer plugin — Hydrogen / electrolyser sites.
 *
 * Merges gu_hydrogen_opportunities (colocation-derived electrolyser sizing)
 * with REPD "other" projects whose technology mentions hydrogen / fuel cell.
 * Rendered as an IconLayer with an H₂ glyph; glyph size tracks
 * electrolyser_mw (or capacity_mw fallback).
 */

import { IconLayer } from "@deck.gl/layers";
import {
  statusColor, iconDef, formatTooltip,
  capacityToPixelSize, bboxFromViewState,
} from "../data/asset_icons";

const ENDPOINT = "/api/twin/assets/hydrogen";

async function fetchH2({ bbox, limit = 1000, signal } = {}) {
  if (!bbox) return { type: "FeatureCollection", features: [] };
  const url = `${ENDPOINT}?bbox=${encodeURIComponent(bbox)}&limit=${limit}`;
  const resp = await fetch(url, { signal });
  if (!resp.ok) throw new Error(`h2 fetch ${resp.status}`);
  return resp.json();
}

function dataHook({ viewState, signal } = {}) {
  const bbox = bboxFromViewState(viewState);
  return fetchH2({ bbox, signal });
}

function sizeMw(props) {
  return props.electrolyser_mw || props.capacity_mw || 0;
}

function layerFactory(ctx = {}) {
  const {
    data,
    visible = true,
    onClick = () => {},
    pickable = true,
  } = ctx;

  if (!data || !data.features || data.features.length === 0) return null;

  return new IconLayer({
    id: "twin-assets-hydrogen",
    data: data.features,
    visible,
    pickable,
    getIcon: () => iconDef("hydrogen"),
    getPosition: f => f.geometry.coordinates,
    getSize: f => capacityToPixelSize(sizeMw(f.properties), { min: 20, max: 44, cap: 200 }),
    sizeUnits: "pixels",
    getColor: f => {
      // gu_hydrogen rows have no status; tint by wobbe_ok: green ok, grey unknown
      if (f.properties.source === "gu_hydrogen") {
        return f.properties.wobbe_ok === true
          ? [3, 169, 244, 230]   // cyan — viable
          : [150, 150, 150, 200]; // grey — wobbe uncertain
      }
      return statusColor(f.properties.status_bucket);
    },
    onClick,
    updateTriggers: {
      getSize: [data.features.length],
      getColor: [data.features.length],
    },
  });
}

export default {
  id: "assets_hydrogen",
  menuLabel: "Hydrogen / electrolyser",
  defaultVisible: false,
  category: "storage",
  icon: "hydrogen",
  tooltip: formatTooltip,
  layerFactory,
  dataHook,
  statusNote: data => {
    if (!data) return null;
    if ((data.features || []).length === 0) {
      return data.note || "No hydrogen sites in view";
    }
    return null;
  },
  legend: [
    { label: "Viable (Wobbe ok)", color: [3, 169, 244, 230] },
    { label: "Wobbe uncertain",   color: [150, 150, 150, 200] },
    { label: "REPD consented",    bucket: "consented" },
    { label: "REPD operational",  bucket: "operational" },
  ],
};
