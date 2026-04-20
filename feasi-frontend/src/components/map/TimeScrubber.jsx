/**
 * TimeScrubber — horizontal timeline docked at the map footer.
 *
 *  Range:        2020-01-01 → 2050-12-31
 *  Default:      today (clamped into range)
 *  Ticks:        major every 5 years, minor every 1 year
 *  Playback:     0.5× / 1× / 2× / 4× with auto-loop
 *  Pinch zoom:   pinch/wheel+ctrl to zoom into a decade
 *  Readout:      JetBrains Mono tabular nums, gold accent
 *  Keyboard:     ←/→ month, shift+←/→ year, space toggles play
 *  Reserved zones:
 *    2020-2025   ivory (historic)
 *    2026-2035   gold gradient (near-term)
 *    2035-2050   ink gradient (FES scenario)
 *
 *  onChange(iso) fires throttled at 60fps while dragging and instantly on click.
 */

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import styles from "./TimeScrubber.module.css";
import { useMapTime, PLAYBACK_SPEEDS, TIME_RANGE } from "../../hooks/useMapTime";

// ── Date helpers ───────────────────────────────────────────────────────────
function toMs(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, (m || 1) - 1, d || 1);
}
function fromMs(ms) {
  const dt = new Date(ms);
  const y = dt.getUTCFullYear();
  const m = String(dt.getUTCMonth() + 1).padStart(2, "0");
  const d = String(dt.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}
function addMonths(iso, months) {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1 + months, d));
  return fromMs(dt.getTime());
}
function addYears(iso, years) {
  return addMonths(iso, years * 12);
}
function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

const MONTH_LABEL = [
  "JAN","FEB","MAR","APR","MAY","JUN",
  "JUL","AUG","SEP","OCT","NOV","DEC",
];
function formatReadout(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d} ${MONTH_LABEL[Number(m) - 1] || "?"} ${y}`;
}

const ICON_PLAY = (
  <svg viewBox="0 0 10 12" className={styles.playIcon} aria-hidden="true">
    <path d="M1 1 L9 6 L1 11 Z" fill="currentColor" />
  </svg>
);
const ICON_PAUSE = (
  <svg viewBox="0 0 10 12" className={styles.playIcon} aria-hidden="true">
    <rect x="1" y="1" width="2.8" height="10" fill="currentColor" />
    <rect x="6.2" y="1" width="2.8" height="10" fill="currentColor" />
  </svg>
);

// ── Component ──────────────────────────────────────────────────────────────
export default function TimeScrubber({ onChange }) {
  const {
    asOf,
    isPlaying,
    speed,
    setAsOf,
    play,
    pause,
    toggle,
    setSpeed,
  } = useMapTime();

  // Pinch/ctrl-wheel zoom: adjust visible window (all within the global range).
  const [viewStart, setViewStart] = useState(TIME_RANGE.start);
  const [viewEnd,   setViewEnd]   = useState(TIME_RANGE.end);

  const trackRef     = useRef(null);
  const isDragging   = useRef(false);
  const pendingIso   = useRef(asOf);
  const rafId        = useRef(0);
  const lastEmitTime = useRef(0);
  const pinchStart   = useRef(null);

  // ── ISO ↔ pixel helpers bound to current view ────────────────────────────
  const msStart = useMemo(() => toMs(viewStart), [viewStart]);
  const msEnd   = useMemo(() => toMs(viewEnd),   [viewEnd]);
  const spanMs  = Math.max(1, msEnd - msStart);

  const isoToPct = useCallback((iso) => {
    const ms = toMs(iso);
    return clamp((ms - msStart) / spanMs, 0, 1);
  }, [msStart, spanMs]);

  const xToIso = useCallback((clientX) => {
    const el = trackRef.current;
    if (!el) return asOf;
    const rect = el.getBoundingClientRect();
    const pct = clamp((clientX - rect.left) / rect.width, 0, 1);
    return fromMs(msStart + pct * spanMs);
  }, [asOf, msStart, spanMs]);

  // ── Throttled emit for drag (60fps) ──────────────────────────────────────
  const scheduleEmit = useCallback((iso) => {
    pendingIso.current = iso;
    if (rafId.current) return;
    rafId.current = requestAnimationFrame(() => {
      rafId.current = 0;
      const now = performance.now();
      if (now - lastEmitTime.current >= 16) {
        lastEmitTime.current = now;
        setAsOf(pendingIso.current);
        if (onChange) onChange(pendingIso.current);
      } else {
        // still within frame budget — re-schedule
        rafId.current = requestAnimationFrame(() => {
          rafId.current = 0;
          lastEmitTime.current = performance.now();
          setAsOf(pendingIso.current);
          if (onChange) onChange(pendingIso.current);
        });
      }
    });
  }, [setAsOf, onChange]);

  // Fire onChange instantly (for click / keyboard)
  const emitInstant = useCallback((iso) => {
    setAsOf(iso);
    if (onChange) onChange(iso);
  }, [setAsOf, onChange]);

  // ── Pointer interactions ─────────────────────────────────────────────────
  const handlePointerDown = useCallback((e) => {
    // 2-finger (pinch) start — track initial distance
    if (e.pointerType === "touch") {
      pinchStart.current = pinchStart.current || {};
      pinchStart.current[e.pointerId] = e.clientX;
      const ids = Object.keys(pinchStart.current);
      if (ids.length >= 2) return; // handled in onPointerMove via wheel fallback
    }

    const el = trackRef.current;
    if (!el) return;
    el.setPointerCapture?.(e.pointerId);
    isDragging.current = true;
    emitInstant(xToIso(e.clientX));
    e.preventDefault();
  }, [emitInstant, xToIso]);

  const handlePointerMove = useCallback((e) => {
    if (pinchStart.current && e.pointerType === "touch") {
      pinchStart.current[e.pointerId] = e.clientX;
      const xs = Object.values(pinchStart.current);
      if (xs.length >= 2) {
        const dist = Math.abs(xs[0] - xs[1]);
        const prev = pinchStart.current.__dist || dist;
        const delta = dist - prev;
        pinchStart.current.__dist = dist;
        if (Math.abs(delta) > 2) {
          zoomView(delta > 0 ? 0.9 : 1.1, (xs[0] + xs[1]) / 2);
        }
        return;
      }
    }
    if (!isDragging.current) return;
    scheduleEmit(xToIso(e.clientX));
  }, [scheduleEmit, xToIso]);

  const endDrag = useCallback((e) => {
    if (e?.pointerType === "touch" && pinchStart.current) {
      delete pinchStart.current[e.pointerId];
      if (Object.keys(pinchStart.current).filter((k) => k !== "__dist").length < 2) {
        pinchStart.current = null;
      }
    }
    if (!isDragging.current) return;
    isDragging.current = false;
    // flush final value immediately
    if (rafId.current) {
      cancelAnimationFrame(rafId.current);
      rafId.current = 0;
    }
    emitInstant(pendingIso.current || asOf);
  }, [asOf, emitInstant]);

  // ── Zoom (wheel+ctrl = pinch on Mac) ─────────────────────────────────────
  const zoomView = useCallback((factor, centerX) => {
    const el = trackRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const pct = clamp((centerX - rect.left) / rect.width, 0, 1);
    const nowStart = toMs(viewStart);
    const nowEnd   = toMs(viewEnd);
    const center   = nowStart + pct * (nowEnd - nowStart);
    const half     = ((nowEnd - nowStart) * factor) / 2;
    const HARD_START = toMs(TIME_RANGE.start);
    const HARD_END   = toMs(TIME_RANGE.end);
    // don't zoom tighter than ~2 years or wider than full range
    const MIN_SPAN = 2 * 365 * 24 * 3600 * 1000;
    const MAX_SPAN = HARD_END - HARD_START;
    const span = clamp(half * 2, MIN_SPAN, MAX_SPAN);
    const h = span / 2;
    let ns = clamp(center - h, HARD_START, HARD_END - span);
    let ne = ns + span;
    setViewStart(fromMs(ns));
    setViewEnd(fromMs(ne));
  }, [viewStart, viewEnd]);

  const handleWheel = useCallback((e) => {
    // Ctrl (or Cmd) + wheel ⇒ zoom; plain wheel ⇒ ignore so page can scroll.
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    zoomView(e.deltaY < 0 ? 0.85 : 1.15, e.clientX);
  }, [zoomView]);

  // ── Keyboard ─────────────────────────────────────────────────────────────
  useEffect(() => {
    const keydown = (e) => {
      // ignore when user is typing in an input
      const tag = (e.target && e.target.tagName) || "";
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) || e.target?.isContentEditable) return;
      if (e.key === " ") {
        e.preventDefault();
        toggle();
        return;
      }
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        const dir = e.key === "ArrowRight" ? 1 : -1;
        const next = e.shiftKey ? addYears(asOf, dir) : addMonths(asOf, dir);
        emitInstant(next);
      }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [asOf, emitInstant, toggle]);

  // ── Playback loop ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!isPlaying) return;
    let raf = 0;
    let last = performance.now();
    const HARD_END_MS = toMs(TIME_RANGE.end);
    const HARD_START_MS = toMs(TIME_RANGE.start);
    // 1× = 1 year / 6 seconds in the map. Tune as you like.
    const MS_PER_SEC_AT_1X = (365 * 24 * 3600 * 1000) / 6;

    const tick = (t) => {
      const dt = (t - last) / 1000;
      last = t;
      const deltaDateMs = dt * MS_PER_SEC_AT_1X * speed;
      let next = toMs(pendingIso.current || asOf) + deltaDateMs;
      if (next > HARD_END_MS) {
        // auto-loop
        next = HARD_START_MS + (next - HARD_END_MS);
      }
      const iso = fromMs(next);
      pendingIso.current = iso;
      setAsOf(iso);
      if (onChange) onChange(iso);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPlaying, speed]);

  // keep pendingIso aligned with external asOf changes
  useEffect(() => { pendingIso.current = asOf; }, [asOf]);

  // ── Tick computation ─────────────────────────────────────────────────────
  const ticks = useMemo(() => {
    const [ys] = viewStart.split("-").map(Number);
    const [ye] = viewEnd.split("-").map(Number);
    const out = [];
    for (let y = ys; y <= ye; y++) {
      const iso = `${y}-01-01`;
      const pct = isoToPct(iso) * 100;
      if (pct < -0.5 || pct > 100.5) continue;
      const isMajor = y % 5 === 0;
      out.push({ y, pct, isMajor });
    }
    return out;
  }, [viewStart, viewEnd, isoToPct]);

  // ── Reserved zone geometry (as % of current view) ────────────────────────
  const zoneHistoric = useMemo(() => {
    const a = isoToPct("2020-01-01") * 100;
    const b = isoToPct("2026-01-01") * 100;
    return { left: `${a}%`, width: `${Math.max(0, b - a)}%` };
  }, [isoToPct]);

  const zoneNearTerm = useMemo(() => {
    const a = isoToPct("2026-01-01") * 100;
    const b = isoToPct("2035-01-01") * 100;
    return { left: `${a}%`, width: `${Math.max(0, b - a)}%` };
  }, [isoToPct]);

  const zoneFes = useMemo(() => {
    const a = isoToPct("2035-01-01") * 100;
    const b = isoToPct("2051-01-01") * 100;
    return { left: `${a}%`, width: `${Math.max(0, b - a)}%` };
  }, [isoToPct]);

  const thumbPct = isoToPct(asOf) * 100;
  const progressPct = thumbPct;

  return (
    <div
      className={styles.root}
      role="group"
      aria-label="Map time scrubber"
    >
      <button
        type="button"
        className={`${styles.playBtn} ${isPlaying ? styles.playBtnPlaying : ""}`}
        onClick={toggle}
        aria-pressed={isPlaying}
        aria-label={isPlaying ? "Pause playback" : "Play playback"}
        title={isPlaying ? "Pause (Space)" : "Play (Space)"}
      >
        {isPlaying ? ICON_PAUSE : ICON_PLAY}
      </button>

      <label className={styles.speed}>
        <span>Speed</span>
        <select
          className={styles.speedSelect}
          value={speed}
          onChange={(e) => setSpeed(Number(e.target.value))}
          aria-label="Playback speed"
        >
          {PLAYBACK_SPEEDS.map((s) => (
            <option key={s} value={s}>{s}x</option>
          ))}
        </select>
      </label>

      <div className={styles.trackWrap}>
        <div
          ref={trackRef}
          className={styles.track}
          tabIndex={0}
          role="slider"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(thumbPct)}
          aria-valuetext={formatReadout(asOf)}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onPointerLeave={(e) => { if (isDragging.current) endDrag(e); }}
          onWheel={handleWheel}
        >
          {/* reserved zones */}
          <div className={styles.zoneHistoric}  style={zoneHistoric} />
          <div className={styles.zoneNearTerm}  style={zoneNearTerm} />
          <div className={styles.zoneFes}       style={zoneFes} />

          {/* progress fill */}
          <div
            className={styles.progress}
            style={{ width: `${progressPct}%` }}
          />

          {/* ticks */}
          <div className={styles.ticks}>
            {ticks.map((t) => (
              <React.Fragment key={t.y}>
                <div
                  className={t.isMajor ? styles.tickMajor : styles.tickMinor}
                  style={{ left: `${t.pct}%` }}
                />
                {t.isMajor && (
                  <div
                    className={styles.tickLabel}
                    style={{ left: `${t.pct}%` }}
                  >{t.y}</div>
                )}
              </React.Fragment>
            ))}
          </div>

          {/* thumb */}
          <div
            className={`${styles.thumb} ${isDragging.current ? styles.thumbDragging : ""}`}
            style={{ left: `${thumbPct}%` }}
            aria-hidden="true"
          />
        </div>
      </div>

      <div className={styles.readout} title="Current map date">
        <span className={styles.readoutAccent}>As of</span>{" "}
        {formatReadout(asOf)}
      </div>
    </div>
  );
}
