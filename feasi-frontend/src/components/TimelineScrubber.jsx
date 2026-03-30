/**
 * TimelineScrubber — 4D temporal playback bar for the command center.
 *
 * Provides a bottom timeline bar with:
 *   - Time range modes: 24h, 7d, 30d, forecast (2024-2050)
 *   - Draggable playhead synced to all data layers
 *   - Play/pause with variable speed (1x, 2x, 5x, 10x)
 *   - Tick marks for significant events (demand peaks, constraints)
 *   - Current timestamp display
 *
 * Props:
 *   onTimeChange(isoString)  — called when playhead moves
 *   onModeChange(mode)       — called when range mode changes
 *   gridState                — current grid state (for event markers)
 *   liveMode                 — whether in live mode
 *   onLiveModeChange(bool)   — toggle live
 */
import React, { useState, useEffect, useRef, useCallback } from "react";

const RANGES = [
  { id: "live", label: "LIVE", hours: 0 },
  { id: "24h", label: "24H", hours: 24 },
  { id: "7d", label: "7D", hours: 168 },
  { id: "30d", label: "30D", hours: 720 },
  { id: "forecast", label: "FWD", hours: 0 },
];

const SPEEDS = [1, 2, 5, 10, 30];

function fmtTime(d) {
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}
function fmtDate(d) {
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}
function fmtFull(d) {
  return `${fmtDate(d)} ${fmtTime(d)}`;
}

export default function TimelineScrubber({
  onTimeChange,
  onModeChange,
  gridState,
  liveMode,
  onLiveModeChange,
}) {
  const [range, setRange] = useState("live");
  const [position, setPosition] = useState(1); // 0-1 normalized
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [dragging, setDragging] = useState(false);
  const trackRef = useRef(null);
  const animRef = useRef(null);

  // Compute start/end times for current range
  const now = useRef(new Date());
  useEffect(() => { now.current = new Date(); }, [range]);

  const getTimeRange = useCallback(() => {
    const n = now.current;
    const r = RANGES.find(r => r.id === range);
    if (range === "live") return { start: new Date(n - 3600000), end: n };
    if (range === "forecast") return { start: n, end: new Date(n.getTime() + 365 * 24 * 3600000) };
    return { start: new Date(n - r.hours * 3600000), end: n };
  }, [range]);

  const positionToTime = useCallback((pos) => {
    const { start, end } = getTimeRange();
    return new Date(start.getTime() + pos * (end.getTime() - start.getTime()));
  }, [getTimeRange]);

  const currentTime = positionToTime(position);

  // Emit time changes
  useEffect(() => {
    if (range !== "live") {
      onTimeChange?.(currentTime.toISOString());
    }
  }, [position, range]); // eslint-disable-line

  // Animation loop
  useEffect(() => {
    if (!playing || range === "live") return;
    const { start, end } = getTimeRange();
    const totalMs = end.getTime() - start.getTime();
    // Complete timeline in 60s at 1x speed
    const stepMs = (totalMs / 60000) * speed;

    const tick = () => {
      setPosition(prev => {
        const next = prev + (stepMs / totalMs) * (16 / 1000);
        if (next >= 1) { setPlaying(false); return 1; }
        return next;
      });
      animRef.current = requestAnimationFrame(tick);
    };
    animRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animRef.current);
  }, [playing, speed, range, getTimeRange]);

  // Mouse drag on track
  const handleTrackMouse = useCallback((e) => {
    const track = trackRef.current;
    if (!track) return;
    const rect = track.getBoundingClientRect();
    const pos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    setPosition(pos);
    if (range === "live") {
      setRange("24h");
      onLiveModeChange?.(false);
      onModeChange?.("24h");
    }
  }, [range, onLiveModeChange, onModeChange]);

  const onMouseDown = (e) => {
    setDragging(true);
    setPlaying(false);
    handleTrackMouse(e);
  };

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e) => handleTrackMouse(e);
    const onUp = () => setDragging(false);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging, handleTrackMouse]);

  // Range change
  const changeRange = (id) => {
    setRange(id);
    setPosition(id === "live" ? 1 : 0);
    setPlaying(false);
    if (id === "live") {
      onLiveModeChange?.(true);
    } else {
      onLiveModeChange?.(false);
    }
    onModeChange?.(id);
  };

  // Event markers from grid state
  const eventMarkers = [];
  if (gridState && range !== "live") {
    // Mark high-utilisation moments
    for (const s of (gridState.substations || []).filter(s => s.utilisation >= 0.85)) {
      eventMarkers.push({
        pos: 0.3 + Math.random() * 0.4, // placeholder positions
        color: s.utilisation >= 0.95 ? "#f5222d" : "#fa8c16",
        label: `${s.name} ${(s.utilisation * 100).toFixed(0)}%`,
        type: "constraint",
      });
    }
    for (const l of (gridState.lines || []).filter(l => l.congested)) {
      eventMarkers.push({
        pos: 0.2 + Math.random() * 0.6,
        color: "#f5222d",
        label: `${l.from}-${l.to} congested`,
        type: "congestion",
      });
    }
  }

  // Tick marks
  const ticks = [];
  if (range === "24h") {
    for (let i = 0; i <= 24; i += 3) {
      ticks.push({ pos: i / 24, label: `${i}h` });
    }
  } else if (range === "7d") {
    for (let i = 0; i <= 7; i++) {
      const d = new Date(now.current - (7 - i) * 86400000);
      ticks.push({ pos: i / 7, label: d.toLocaleDateString("en-GB", { weekday: "short" }) });
    }
  } else if (range === "30d") {
    for (let i = 0; i <= 30; i += 5) {
      const d = new Date(now.current - (30 - i) * 86400000);
      ticks.push({ pos: i / 30, label: `${d.getDate()}/${d.getMonth() + 1}` });
    }
  }

  return (
    <div className="tl-scrubber">
      {/* Left controls */}
      <div className="tl-controls">
        {/* Play/Pause */}
        <button
          className="tl-play-btn"
          onClick={() => {
            if (range === "live") { changeRange("24h"); }
            setPlaying(!playing);
          }}
          title={playing ? "Pause" : "Play"}
        >
          {playing ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <polygon points="5,3 19,12 5,21"/>
            </svg>
          )}
        </button>

        {/* Speed */}
        <button
          className="tl-speed-btn"
          onClick={() => setSpeed(prev => SPEEDS[(SPEEDS.indexOf(prev) + 1) % SPEEDS.length])}
          title="Playback speed"
        >
          {speed}x
        </button>
      </div>

      {/* Range selectors */}
      <div className="tl-ranges">
        {RANGES.map(r => (
          <button
            key={r.id}
            className={`tl-range-btn ${range === r.id ? "active" : ""}`}
            onClick={() => changeRange(r.id)}
          >
            {r.id === "live" && <span className="tl-live-dot" />}
            {r.label}
          </button>
        ))}
      </div>

      {/* Timeline track */}
      <div className="tl-track-container">
        <div className="tl-track" ref={trackRef} onMouseDown={onMouseDown}>
          {/* Filled region */}
          <div className="tl-track-fill" style={{ width: `${position * 100}%` }} />

          {/* Tick marks */}
          {ticks.map((t, i) => (
            <div key={i} className="tl-tick" style={{ left: `${t.pos * 100}%` }}>
              <div className="tl-tick-mark" />
              <span className="tl-tick-label">{t.label}</span>
            </div>
          ))}

          {/* Event markers */}
          {eventMarkers.slice(0, 20).map((m, i) => (
            <div
              key={i}
              className="tl-event-marker"
              style={{ left: `${m.pos * 100}%`, background: m.color }}
              title={m.label}
            />
          ))}

          {/* Playhead */}
          <div
            className="tl-playhead"
            style={{ left: `${position * 100}%` }}
          >
            <div className="tl-playhead-line" />
            <div className="tl-playhead-handle" />
          </div>
        </div>
      </div>

      {/* Current time display */}
      <div className="tl-time-display">
        <span className="tl-time-date">{fmtDate(currentTime)}</span>
        <span className="tl-time-clock">{fmtTime(currentTime)}</span>
      </div>
    </div>
  );
}
