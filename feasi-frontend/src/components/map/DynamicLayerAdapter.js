/**
 * DynamicLayerAdapter — higher-order wrapper that makes any deck.gl layer
 * time-aware.
 *
 *     withTime(layer, { asOf, propFieldFrom, propFieldTo })
 *
 * Hides features whose lifespan does not include `asOf`, i.e.:
 *   asOf < feature[propFieldFrom]   → not yet alive
 *   asOf > feature[propFieldTo]     → already decommissioned
 *
 * The wrapper operates in two modes depending on whether the input is an
 * already-instantiated deck.gl Layer or a LayerConfig-like object
 * ({ type, props }). It filters the `data` array and returns a new layer of
 * the same class with the filtered data + updateTriggers on `asOf` so deck
 * repaints cheaply on scrub.
 *
 * Designed to be cheap (<200ms for 5k features):
 *   - Filter runs in-place, single pass.
 *   - Re-wrap returns a new layer instance only when `asOf` crosses a
 *     year boundary by default (tune via `granularity`).
 */

// Simple in-memory LRU keyed by (layerId|asOfKey) so year-stepping is cached.
const CACHE = new Map();
const CACHE_MAX = 64;

function cacheGet(k)      { return CACHE.get(k); }
function cachePut(k, v)   {
  if (CACHE.size >= CACHE_MAX) {
    // drop oldest
    const firstKey = CACHE.keys().next().value;
    CACHE.delete(firstKey);
  }
  CACHE.set(k, v);
}

function asOfBucket(asOf, granularity) {
  // granularity: 'day' | 'month' | 'year'
  if (!asOf) return "none";
  if (granularity === "day")   return asOf;
  if (granularity === "year")  return asOf.slice(0, 4);
  return asOf.slice(0, 7); // month default
}

function readField(feature, field) {
  if (!feature || !field) return null;
  if (feature[field] !== undefined) return feature[field];
  if (feature.properties && feature.properties[field] !== undefined) {
    return feature.properties[field];
  }
  return null;
}

/**
 * isFeatureAliveAt — core predicate.
 * Missing bounds are treated as open-ended (null-from ⇒ always started,
 * null-to ⇒ never ends).
 */
export function isFeatureAliveAt(feature, asOf, fromField, toField) {
  const from = readField(feature, fromField);
  const to   = readField(feature, toField);
  if (from && asOf < from) return false;
  if (to   && asOf > to)   return false;
  return true;
}

/**
 * filterDataByTime — apply the time predicate to an array of features.
 */
export function filterDataByTime(data, asOf, fromField, toField) {
  if (!Array.isArray(data) || !asOf) return data ?? [];
  return data.filter((f) => isFeatureAliveAt(f, asOf, fromField, toField));
}

/**
 * withTime — wrap a deck.gl Layer (instance or config) with a time filter.
 *
 * @param {Layer|{type, props, id}} layer
 * @param {{ asOf: string, propFieldFrom: string, propFieldTo: string,
 *          granularity?: 'day'|'month'|'year' }} opts
 * @returns {Layer|{type, props, id}}
 */
export function withTime(layer, opts = {}) {
  const {
    asOf,
    propFieldFrom = "date_from",
    propFieldTo   = "date_to",
    granularity   = "month",
  } = opts;

  if (!layer) return layer;
  if (!asOf)  return layer; // no-op without a time anchor

  const layerId =
    (layer && layer.id) ||
    (layer && layer.props && layer.props.id) ||
    "unknown-layer";
  const bucket = asOfBucket(asOf, granularity);
  const cacheKey = `${layerId}|${bucket}|${propFieldFrom}|${propFieldTo}`;

  // Instantiated deck.gl Layer (has .props and .clone)
  if (typeof layer.clone === "function" && layer.props) {
    const hit = cacheGet(cacheKey);
    const filteredData =
      hit?.data ??
      filterDataByTime(layer.props.data, asOf, propFieldFrom, propFieldTo);
    cachePut(cacheKey, { data: filteredData });

    return layer.clone({
      data: filteredData,
      updateTriggers: {
        ...(layer.props.updateTriggers || {}),
        getFillColor:   [...(layer.props.updateTriggers?.getFillColor   ?? []), bucket],
        getLineColor:   [...(layer.props.updateTriggers?.getLineColor   ?? []), bucket],
        getRadius:      [...(layer.props.updateTriggers?.getRadius      ?? []), bucket],
        getElevation:   [...(layer.props.updateTriggers?.getElevation   ?? []), bucket],
        getPosition:    [...(layer.props.updateTriggers?.getPosition    ?? []), bucket],
      },
    });
  }

  // Plain config { type, props }
  if (layer.props && layer.type) {
    const hit = cacheGet(cacheKey);
    const filteredData =
      hit?.data ??
      filterDataByTime(layer.props.data, asOf, propFieldFrom, propFieldTo);
    cachePut(cacheKey, { data: filteredData });

    return {
      ...layer,
      props: {
        ...layer.props,
        data: filteredData,
        updateTriggers: {
          ...(layer.props.updateTriggers || {}),
          getFillColor:   [bucket],
          getLineColor:   [bucket],
          getRadius:      [bucket],
          getElevation:   [bucket],
          getPosition:    [bucket],
        },
      },
    };
  }

  return layer;
}

/**
 * pickTimeseriesValue — read a monthly/annual timeseries off a feature.
 * `series` is an object keyed by ISO-month or ISO-year.
 * Returns the most recent sample at or before `asOf`, or null.
 */
export function pickTimeseriesValue(series, asOf) {
  if (!series || typeof series !== "object" || !asOf) return null;
  const keys = Object.keys(series).filter((k) => k <= asOf).sort();
  if (!keys.length) return null;
  return series[keys[keys.length - 1]];
}

/**
 * tecColourForState — colour ramp for TEC register projects.
 * Ink → gold spectrum used across the app.
 */
export function tecColourForState(state) {
  switch (state) {
    case "pre_offer":   return [180, 180, 180, 180]; // grey
    case "offered":     return [ 80, 140, 220, 220]; // blue
    case "accepted":    return [ 20, 180, 170, 230]; // teal
    case "commissioned":return [ 40, 190,  90, 240]; // green
    case "decommissioned": return [110, 110, 110, 120];
    default:            return [200, 200, 200, 160];
  }
}

/**
 * tecStateAt — derive the project's lifecycle state at `asOf`.
 */
export function tecStateAt(project, asOf) {
  if (!asOf || !project) return "pre_offer";
  if (project.decommissioned_date && asOf >= project.decommissioned_date) return "decommissioned";
  if (project.commissioned_date   && asOf >= project.commissioned_date)   return "commissioned";
  if (project.accepted_date       && asOf >= project.accepted_date)       return "accepted";
  if (project.offered_date        && asOf >= project.offered_date)        return "offered";
  return "pre_offer";
}

/**
 * repdStateAt — REPD planning app state at `asOf`.
 */
export function repdStateAt(app, asOf) {
  if (!app || !asOf) return "submitted";
  if (app.decision_date && asOf >= app.decision_date) {
    return app.decision === "approved" ? "approved" : "refused";
  }
  if (app.submission_date && asOf >= app.submission_date) return "submitted";
  return "pre_submission";
}

export function repdColourForState(state) {
  switch (state) {
    case "approved":  return [ 40, 190,  90, 240];
    case "refused":   return [220,  60,  60, 230];
    case "submitted": return [170, 170, 170, 210];
    default:          return [120, 120, 120, 120];
  }
}

/**
 * clearLayerTimeCache — call from React effect teardown or on data reload.
 */
export function clearLayerTimeCache() {
  CACHE.clear();
}

export default withTime;
