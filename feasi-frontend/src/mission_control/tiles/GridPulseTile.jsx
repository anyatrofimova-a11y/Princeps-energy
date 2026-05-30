import React from "react";
import ProvenanceFooter, { WarmingState, TileSkeleton } from "./ProvenanceFooter";

/**
 * GridPulseTile — BMRS prices + carbon intensity + frequency dial.
 *
 * Pure-SVG sparklines, no chart lib. Three sparklines (price, carbon
 * forecast, carbon actual) + one frequency dial.
 */
function Sparkline({ values, color = "#F5B731", height = 32, width = 140 }) {
  if (!values || values.length < 2) {
    return <div className="mcv2-skeleton" style={{ height, width }} />;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const stepX = width / (values.length - 1);
  const points = values.map((v, i) => {
    const x = i * stepX;
    const y = height - ((v - min) / range) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const areaPoints = `0,${height} ${points} ${width},${height}`;
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <polygon points={areaPoints} fill={color} fillOpacity="0.16" />
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

function FrequencyDial({ hz }) {
  // Healthy band 49.95-50.05, soft 49.8-50.2, hard 49.5-50.5.
  const safe = hz >= 49.95 && hz <= 50.05;
  const warn = !safe && hz >= 49.8 && hz <= 50.2;
  const color = safe ? "#16A34A" : warn ? "#E8A012" : "#DC2626";
  const valueText = (hz != null && Number.isFinite(hz))
    ? `${hz.toFixed(3)} Hz`
    : "—";
  return (
    <div className="mcv2-dial">
      <svg width="80" height="44" viewBox="0 0 80 44">
        <path d="M6,40 A34,34 0 0 1 74,40" fill="none" stroke="#ECE7DA" strokeWidth="6" strokeLinecap="round" />
        {/* Needle: nominal 50.00 -> centre. Map 49.5..50.5 -> 0..pi. */}
        {(() => {
          const t = Math.max(0, Math.min(1, ((hz ?? 50) - 49.5)));
          const angle = Math.PI * (1 - t);
          const cx = 40, cy = 40, r = 28;
          const nx = cx + Math.cos(angle) * r;
          const ny = cy - Math.sin(angle) * r;
          return (
            <line x1={cx} y1={cy} x2={nx} y2={ny} stroke={color} strokeWidth="2.4" strokeLinecap="round" />
          );
        })()}
        <circle cx="40" cy="40" r="2.6" fill={color} />
      </svg>
      <div className="mcv2-dial-value" style={{ color }}>{valueText}</div>
      <div className="mcv2-dial-label">System frequency</div>
    </div>
  );
}

export default function GridPulseTile({ data, loading = false }) {
  const prices = (data && data.prices_24h) || [];
  const priceVals = prices.map(p => p.gbp_per_mwh).filter(v => Number.isFinite(v));
  const lastPrice = priceVals.length ? priceVals[priceVals.length - 1] : null;

  const carbon = (data && data.carbon) || {};
  const freq = (data && data.frequency) || { hz: null };

  // Carbon: a single point doesn't render a sparkline — synthesise a tiny
  // horizontal line from forecast → actual so the user sees the delta. If
  // both are null, fall back to a flat skeleton.
  const carbonVals = [carbon.forecast_g_co2_per_kwh, carbon.actual_g_co2_per_kwh]
    .filter(v => Number.isFinite(v));

  const hasAny = priceVals.length > 0 || carbonVals.length > 0 ||
                 (freq.hz != null && Number.isFinite(freq.hz));

  return (
    <div className="mcv2-tile mcv2-area-pulse">
      <div className="mcv2-tile-head">
        <div className="mcv2-tile-title">Live grid pulse</div>
        <div className="mcv2-tile-tag">24h</div>
      </div>
      <div className="mcv2-tile-body">
        {loading && !data ? (
          <TileSkeleton rows={4} />
        ) : !data ? (
          <WarmingState />
        ) : !hasAny ? (
          <WarmingState label="Awaiting BMRS / ESO refresh — feed warming" />
        ) : (
        <div className="mcv2-sparks">
          <div className="mcv2-spark">
            <div className="mcv2-spark-label">System buy price</div>
            <div className="mcv2-spark-value">
              {lastPrice != null ? `£${Math.round(lastPrice)}` : "—"}
              <span style={{ fontSize: 10, color: "#8A9099", marginLeft: 4 }}>/MWh</span>
            </div>
            <Sparkline values={priceVals} color="#F5B731" />
          </div>
          <div className="mcv2-spark">
            <div className="mcv2-spark-label">Carbon intensity</div>
            <div className="mcv2-spark-value">
              {carbon.actual_g_co2_per_kwh != null
                ? `${Math.round(carbon.actual_g_co2_per_kwh)}`
                : (carbon.forecast_g_co2_per_kwh != null
                    ? `${Math.round(carbon.forecast_g_co2_per_kwh)}`
                    : "—")}
              <span style={{ fontSize: 10, color: "#8A9099", marginLeft: 4 }}>g CO2/kWh</span>
            </div>
            <Sparkline values={carbonVals.length >= 2 ? carbonVals : [...carbonVals, ...carbonVals]} color="#16A34A" />
          </div>
          <div className="mcv2-spark" style={{ gridColumn: "1 / -1", display: "grid", gridTemplateColumns: "1fr 110px", gap: 12 }}>
            <div>
              <div className="mcv2-spark-label">Wholesale spread (24h)</div>
              <div className="mcv2-spark-value">
                {priceVals.length >= 2
                  ? `£${Math.round(Math.max(...priceVals) - Math.min(...priceVals))}`
                  : "—"}
                <span style={{ fontSize: 10, color: "#8A9099", marginLeft: 4 }}>peak−trough</span>
              </div>
              <Sparkline values={priceVals.map((v,i,arr) => v - (arr[i-1] ?? v))} color="#E8A012" />
            </div>
            <FrequencyDial hz={freq.hz} />
          </div>
        </div>
        )}
      </div>
      <ProvenanceFooter
        source="BMRS Insights API · National Grid ESO Carbon Intensity API"
        generatedAt={data?.provenance?.generated_at}
      />
    </div>
  );
}
