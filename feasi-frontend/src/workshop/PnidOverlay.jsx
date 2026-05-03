import {useState, useRef, useEffect} from 'react';

/**
 * Pattern (c) — P&ID / Single-line diagram overlay with live tag bubbles.
 *
 * Loads an SVG (P&ID, electrical SLD, mechanical drawing) into the DOM and
 * absolute-positions one bubble per tag at (tag.x, tag.y) coordinates that
 * are pre-extracted from the source drawing (% of viewBox or absolute SVG
 * coords — caller decides via coordinateMode).
 *
 * Each bubble shows current measured value + alarm state. Click → fires
 * onTagClick(tagId) so the workspace can drill into that sensor.
 *
 * Tag shape:
 *   {id, x, y, value, unit, alarmState ('ok'|'warn'|'alarm'|'unknown'), label?}
 *
 * Update strategy: parent re-renders with fresh tags on the SSE/WS tick;
 * the SVG itself is loaded once.
 */
export function PnidOverlay({svgUrl, tags = [], coordinateMode = 'percent', onTagClick}) {
  const [svgMarkup, setSvgMarkup] = useState(null);
  const containerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    setSvgMarkup(null);
    fetch(svgUrl)
      .then((r) => r.text())
      .then((txt) => {
        if (!cancelled) setSvgMarkup(txt);
      })
      .catch((err) => {
        if (!cancelled) {
          console.warn('PnidOverlay: failed to load svg', err);
          setSvgMarkup('<!-- failed -->');
        }
      });
    return () => { cancelled = true; };
  }, [svgUrl]);

  return (
    <div className="px-pnid-overlay" ref={containerRef}>
      <div className="px-pnid-svg" dangerouslySetInnerHTML={{__html: svgMarkup ?? ''}} />
      <div className="px-pnid-bubbles">
        {tags.map((t) => (
          <TagBubble
            key={t.id}
            tag={t}
            coordinateMode={coordinateMode}
            onClick={() => onTagClick?.(t.id, t)}
          />
        ))}
      </div>
    </div>
  );
}

function TagBubble({tag, coordinateMode, onClick}) {
  const {id, x, y, value, unit, alarmState = 'unknown', label} = tag;
  const positionStyle =
    coordinateMode === 'percent'
      ? {left: `${x}%`, top: `${y}%`}
      : {left: x, top: y};
  return (
    <button
      type="button"
      className={`px-pnid-bubble px-alarm-${alarmState}`}
      style={positionStyle}
      onClick={onClick}
      title={label ?? id}
      aria-label={`${label ?? id}: ${value} ${unit ?? ''}`}
    >
      <span className="px-pnid-bubble-value">{formatValue(value)}</span>
      {unit ? <span className="px-pnid-bubble-unit">{unit}</span> : null}
    </button>
  );
}

function formatValue(v) {
  if (v == null) return '—';
  if (typeof v === 'number') {
    if (Math.abs(v) >= 1000) return v.toFixed(0);
    if (Math.abs(v) >= 10) return v.toFixed(1);
    return v.toFixed(2);
  }
  return String(v);
}
