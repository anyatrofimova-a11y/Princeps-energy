/**
 * TimeContext — shared timeline state for all time-aware deck.gl layers.
 *
 * Usage:
 *   <TimeProvider>
 *      <TimeScrubber />
 *      <GridTwin />   // any dyn_* layer reads via useTime()
 *   </TimeProvider>
 *
 * The provider exposes:
 *   timestamp  — number, ms since epoch (UTC). The single source of truth.
 *   setTimestamp(ms)
 *   pathway    — FES pathway id for post-2024 projections.
 *   setPathway(id)
 *   isLive     — true when timestamp tracks wall-clock.
 *   setLive(on)
 *   year, setYear(n) — convenience derived view (Jan-01 of year).
 *
 * The setters are debounced to 250ms so scrubbing a slider does not
 * saturate downstream `useEffect` listeners. The _raw_ setter
 * (setTimestampImmediate) is also exposed for programmatic jumps.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

export const PATHWAYS = [
  { id: "baseline",                 label: "Baseline" },
  { id: "leading_the_way",          label: "Leading the Way" },
  { id: "consumer_transformation",  label: "Consumer Transform" },
  { id: "system_transformation",    label: "System Transform" },
  { id: "falling_short",            label: "Falling Short" },
];

export const MIN_YEAR = 2020;
export const MAX_YEAR = 2050;
export const HISTORICAL_CUTOFF = 2024; // inclusive -> pre-2024 = historical

const TimeContext = createContext(null);

function debounce(fn, ms) {
  let handle = null;
  const wrapped = (...args) => {
    if (handle) clearTimeout(handle);
    handle = setTimeout(() => fn(...args), ms);
  };
  wrapped.cancel = () => { if (handle) clearTimeout(handle); };
  return wrapped;
}

export function TimeProvider({ children, initialTimestamp = null, initialPathway = "baseline" }) {
  const [timestamp, setTimestampState] = useState(
    initialTimestamp != null ? initialTimestamp : Date.now()
  );
  const [pathway, setPathwayState] = useState(initialPathway);
  const [isLive, setLiveState] = useState(true);
  const liveTickRef = useRef(null);

  // Live clock advances timestamp every 30s when isLive=true.
  useEffect(() => {
    if (!isLive) return undefined;
    setTimestampState(Date.now());
    liveTickRef.current = setInterval(() => {
      setTimestampState(Date.now());
    }, 30_000);
    return () => {
      if (liveTickRef.current) clearInterval(liveTickRef.current);
    };
  }, [isLive]);

  // Debounced setter (for sliders)
  const debouncedSet = useMemo(
    () => debounce((ms) => setTimestampState(ms), 250),
    []
  );
  useEffect(() => () => debouncedSet.cancel(), [debouncedSet]);

  const setTimestamp = useCallback((ms) => {
    setLiveState(false);
    debouncedSet(ms);
  }, [debouncedSet]);

  const setTimestampImmediate = useCallback((ms) => {
    setLiveState(false);
    debouncedSet.cancel();
    setTimestampState(ms);
  }, [debouncedSet]);

  const setPathway = useCallback((id) => {
    setPathwayState(id);
  }, []);

  const setLive = useCallback((on) => {
    setLiveState(on);
    if (on) setTimestampState(Date.now());
  }, []);

  const setYear = useCallback((y) => {
    const clamped = Math.max(MIN_YEAR, Math.min(MAX_YEAR, Number(y) || HISTORICAL_CUTOFF));
    const ms = Date.UTC(clamped, 0, 1, 12, 0, 0);
    setTimestampImmediate(ms);
  }, [setTimestampImmediate]);

  const year = new Date(timestamp).getUTCFullYear();
  const isHistorical = year <= HISTORICAL_CUTOFF;

  const value = useMemo(() => ({
    timestamp,
    setTimestamp,
    setTimestampImmediate,
    pathway,
    setPathway,
    isLive,
    setLive,
    year,
    setYear,
    isHistorical,
    pathways: PATHWAYS,
    minYear: MIN_YEAR,
    maxYear: MAX_YEAR,
    historicalCutoff: HISTORICAL_CUTOFF,
  }), [timestamp, pathway, isLive, year, isHistorical,
       setTimestamp, setTimestampImmediate, setPathway, setLive, setYear]);

  return <TimeContext.Provider value={value}>{children}</TimeContext.Provider>;
}

/** Hook — safe no-op defaults when the provider is not mounted, so
 *  layers can still mount in storybook / smoke harness. */
export function useTime() {
  const ctx = useContext(TimeContext);
  if (ctx) return ctx;
  const now = Date.now();
  return {
    timestamp: now,
    setTimestamp: () => {},
    setTimestampImmediate: () => {},
    pathway: "baseline",
    setPathway: () => {},
    isLive: true,
    setLive: () => {},
    year: new Date(now).getUTCFullYear(),
    setYear: () => {},
    isHistorical: false,
    pathways: PATHWAYS,
    minYear: MIN_YEAR,
    maxYear: MAX_YEAR,
    historicalCutoff: HISTORICAL_CUTOFF,
  };
}

export default TimeContext;
