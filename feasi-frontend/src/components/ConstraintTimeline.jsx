import React, { useState, useEffect, useRef, useCallback } from "react";

/**
 * ConstraintTimeline — 48h time-slider for the constraint cost overlay.
 *
 * When active, fetches the full constraint forecast once, then lets users
 * scrub hour-by-hour to see how boundary loading changes. Updates the
 * grid-constraints map source in real-time as the slider moves.
 *
 * Also shows a mini heatmap strip of constraint probability across all boundaries.
 */

const HOUR_LABELS = [];
for (let i = 0; i < 48; i++) {
  const h = i % 24;
  HOUR_LABELS.push(h === 0 ? "00" : h < 10 ? `0${h}` : `${h}`);
}

function riskColor(prob) {
  if (prob > 0.6) return "#f44336";
  if (prob > 0.3) return "#ff9800";
  return "#4caf50";
}

export default function ConstraintTimeline({ map, visible }) {
  const [data, setData] = useState(null);
  const [hour, setHour] = useState(0);
  const [playing, setPlaying] = useState(false);
  const playRef = useRef(null);
  const canvasRef = useRef(null);

  // Fetch full forecast once when layer becomes visible
  useEffect(() => {
    if (!visible) {
      setData(null);
      setHour(0);
      setPlaying(false);
      return;
    }
    fetch("/api/grid/constraints?hours_ahead=48")
      .then((r) => r.ok ? r.json() : null)
      .then((d) => {
        if (d) setData(d);
      })
      .catch(() => {});
  }, [visible]);

  // Update map source when hour changes
  const updateMapForHour = useCallback(
    (h) => {
      if (!data || !map) return;
      const ts = data.timeseries || {};
      const features = (data.features || []).map((f) => {
        const bId = f.properties.boundary_id;
        const hourly = ts[bId];
        const entry = hourly && hourly[h];
        if (!entry) return f;
        return {
          ...f,
          properties: {
            ...f.properties,
            loading_pct: entry.load,
            constraint_prob: entry.prob,
            risk_level: entry.risk,
            datetime: entry.dt,
          },
        };
      });
      const src = map.getSource("grid-constraints");
      if (src) src.setData({ type: "FeatureCollection", features });
    },
    [data, map],
  );

  useEffect(() => {
    updateMapForHour(hour);
  }, [hour, updateMapForHour]);

  // Play animation
  useEffect(() => {
    if (!playing) {
      if (playRef.current) clearInterval(playRef.current);
      return;
    }
    playRef.current = setInterval(() => {
      setHour((h) => {
        const next = h + 1;
        if (next >= 48) {
          setPlaying(false);
          return 0;
        }
        return next;
      });
    }, 400);
    return () => clearInterval(playRef.current);
  }, [playing]);

  // Draw heatmap strip
  useEffect(() => {
    if (!data || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    const ts = data.timeseries || {};
    const bIds = Object.keys(ts);
    const rowH = Math.max(4, Math.floor(canvas.height / bIds.length));
    const colW = canvas.width / 48;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    bIds.forEach((bId, row) => {
      const hours = ts[bId] || [];
      hours.forEach((entry, col) => {
        ctx.fillStyle = riskColor(entry.prob);
        ctx.globalAlpha = 0.3 + entry.prob * 0.7;
        ctx.fillRect(col * colW, row * rowH, colW + 0.5, rowH);
      });
    });
    ctx.globalAlpha = 1;

    // Draw playhead
    ctx.fillStyle = "#fff";
    ctx.fillRect(hour * colW, 0, 1.5, canvas.height);
  }, [data, hour]);

  if (!visible || !data) return null;

  const ts = data.timeseries || {};
  const bIds = Object.keys(ts);
  const currentEntry = bIds.length > 0 && ts[bIds[0]] ? ts[bIds[0]][hour] : null;

  return (
    <div className="constraint-timeline">
      <div className="constraint-timeline-header">
        <span className="constraint-timeline-title">
          Constraint Forecast
        </span>
        <span className="constraint-timeline-time">
          {currentEntry ? currentEntry.dt : `+${hour}h`}
        </span>
        <span className="constraint-timeline-summary">
          {data.summary?.boundaries_at_risk ?? 0} boundaries at risk
        </span>
      </div>

      {/* Mini heatmap — rows = boundaries, cols = hours */}
      <canvas
        ref={canvasRef}
        width={384}
        height={bIds.length * 6}
        className="constraint-timeline-heatmap"
      />

      <div className="constraint-timeline-controls">
        <button
          className="constraint-timeline-btn"
          onClick={() => setPlaying(!playing)}
          title={playing ? "Pause" : "Play"}
        >
          {playing ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="4" width="4" height="16" rx="1" />
              <rect x="14" y="4" width="4" height="16" rx="1" />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <polygon points="5,3 19,12 5,21" />
            </svg>
          )}
        </button>

        <input
          type="range"
          min="0"
          max="47"
          value={hour}
          onChange={(e) => {
            setHour(parseInt(e.target.value, 10));
            setPlaying(false);
          }}
          className="constraint-timeline-slider"
        />

        <span className="constraint-timeline-hour">
          +{hour}h
        </span>
      </div>

      {/* Per-boundary stats for current hour */}
      <div className="constraint-timeline-boundaries">
        {bIds.map((bId) => {
          const entry = ts[bId]?.[hour];
          if (!entry) return null;
          return (
            <div key={bId} className="constraint-timeline-row">
              <span
                className="constraint-timeline-dot"
                style={{ background: riskColor(entry.prob) }}
              />
              <span className="constraint-timeline-bid">{bId}</span>
              <span className="constraint-timeline-load">
                {entry.load.toFixed(0)}%
              </span>
              <div className="constraint-timeline-bar-bg">
                <div
                  className="constraint-timeline-bar"
                  style={{
                    width: `${Math.min(100, entry.load)}%`,
                    background: riskColor(entry.prob),
                  }}
                />
              </div>
              <span
                className="constraint-timeline-risk"
                style={{ color: riskColor(entry.prob) }}
              >
                {entry.risk}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
