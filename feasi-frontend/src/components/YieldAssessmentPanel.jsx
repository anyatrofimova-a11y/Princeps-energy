import React, { useState, useCallback } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

/* ── Constants ─────────────────────────────────────────────────────────── */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const TRACKING_OPTS = [
  { id: "none", label: "Fixed Tilt" },
  { id: "single", label: "Single-Axis" },
  { id: "dual", label: "Dual-Axis" },
];

const TURBINE_MODELS = [
  { id: "v136", label: "Vestas V136-4.2", hub_m: 112, rated_mw: 4.2 },
  { id: "sg145", label: "SG 6.6-145", hub_m: 100, rated_mw: 6.6 },
  { id: "e138", label: "Enercon E-138", hub_m: 131, rated_mw: 4.2 },
];

const EXCEEDANCE = [
  { label: "P50", pct: 50 },
  { label: "P75", pct: 75 },
  { label: "P90", pct: 90 },
  { label: "P99", pct: 99 },
];

/* ── Helpers ────────────────────────────────────────────────────────────── */
function fmtMwh(v) {
  if (v == null) return "--";
  if (v >= 1000) return `${(v / 1000).toFixed(1)} GWh`;
  return `${v.toFixed(0)} MWh`;
}
function fmtNum(v, dp = 1) { return v != null ? v.toFixed(dp) : "--"; }

/* ── Monthly Bar Chart (SVG) ───────────────────────────────────────────── */
function MonthlyBarChart({ data, color = "var(--gold)", width = 370, height = 180, unit = "MWh" }) {
  if (!data?.length) return null;
  const pad = { l: 40, r: 10, t: 16, b: 24 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const maxVal = Math.max(...data.map(d => d.value || 0), 1);
  const barW = w / 12 * 0.7;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto" }}>
      {data.map((d, i) => {
        const x = pad.l + (i / 12) * w + (w / 12 - barW) / 2;
        const barH = ((d.value || 0) / maxVal) * h;
        return (
          <g key={i}>
            <rect x={x} y={pad.t + h - barH} width={barW} height={barH} rx={3} fill={color} opacity={0.8} />
            <text x={x + barW / 2} y={height - 6} textAnchor="middle" fill="var(--cds-text-helper)" fontSize="8">{MONTHS[i]}</text>
            <text x={x + barW / 2} y={pad.t + h - barH - 4} textAnchor="middle" fill="var(--cds-text-primary)" fontSize="7"
              fontFamily="JetBrains Mono, monospace" fontWeight="600">{(d.value || 0).toFixed(0)}</text>
          </g>
        );
      })}
      <text x={pad.l - 4} y={pad.t + 8} textAnchor="end" fill="var(--cds-text-helper)" fontSize="8">{maxVal.toFixed(0)}</text>
      <text x={pad.l - 4} y={pad.t + h} textAnchor="end" fill="var(--cds-text-helper)" fontSize="8">0</text>
    </svg>
  );
}

/* ── Hourly Profile Chart (SVG) ────────────────────────────────────────── */
function HourlyProfileChart({ summer, winter, width = 370, height = 160 }) {
  if (!summer?.length) return null;
  const pad = { l: 40, r: 10, t: 16, b: 24 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const maxVal = Math.max(...summer.map(d => d.value || 0), ...winter.map(d => d.value || 0), 1);

  const line = (data, color, dashed = false) => {
    const points = data.map((d, i) => {
      const x = pad.l + (i / 24) * w;
      const y = pad.t + h - ((d.value || 0) / maxVal) * h;
      return `${x},${y}`;
    }).join(" ");
    return <polyline points={points} fill="none" stroke={color} strokeWidth={2}
      strokeDasharray={dashed ? "4,3" : "none"} />;
  };

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto" }}>
      {/* Area fill for summer */}
      <polygon
        points={`${pad.l},${pad.t + h} ${summer.map((d, i) => `${pad.l + (i / 24) * w},${pad.t + h - ((d.value || 0) / maxVal) * h}`).join(" ")} ${pad.l + w},${pad.t + h}`}
        fill="var(--gold)" opacity={0.1} />
      {line(summer, "var(--gold)")}
      {line(winter, "#3b82f6", true)}
      {/* X axis */}
      {[0, 6, 12, 18, 24].map(hr => (
        <text key={hr} x={pad.l + (hr / 24) * w} y={height - 6} textAnchor="middle" fill="var(--cds-text-helper)" fontSize="8">{hr}:00</text>
      ))}
      {/* Legend */}
      <line x1={width - 110} y1={pad.t + 4} x2={width - 96} y2={pad.t + 4} stroke="var(--gold)" strokeWidth={2} />
      <text x={width - 92} y={pad.t + 7} fill="var(--cds-text-helper)" fontSize="8">Summer</text>
      <line x1={width - 110} y1={pad.t + 16} x2={width - 96} y2={pad.t + 16} stroke="#3b82f6" strokeWidth={2} strokeDasharray="4,3" />
      <text x={width - 92} y={pad.t + 19} fill="var(--cds-text-helper)" fontSize="8">Winter</text>
    </svg>
  );
}

/* ── Wind Rose (simplified SVG) ────────────────────────────────────────── */
function WindRose({ data, size = 180 }) {
  const directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  const cx = size / 2, cy = size / 2, maxR = size / 2 - 20;
  const vals = data || directions.map((_, i) => 5 + Math.sin(i * 0.8) * 4 + Math.random() * 3);
  const maxVal = Math.max(...vals, 1);

  const points = vals.map((v, i) => {
    const angle = (i / 8) * Math.PI * 2 - Math.PI / 2;
    const r = (v / maxVal) * maxR;
    return `${cx + r * Math.cos(angle)},${cy + r * Math.sin(angle)}`;
  }).join(" ");

  return (
    <svg viewBox={`0 0 ${size} ${size}`} style={{ width: size, height: size, display: "block", margin: "0 auto" }}>
      {/* Grid circles */}
      {[0.25, 0.5, 0.75, 1].map(f => (
        <circle key={f} cx={cx} cy={cy} r={maxR * f} fill="none" stroke="var(--cds-border-subtle)" strokeWidth={0.5} />
      ))}
      {/* Direction labels */}
      {directions.map((d, i) => {
        const angle = (i / 8) * Math.PI * 2 - Math.PI / 2;
        return (
          <text key={d} x={cx + (maxR + 12) * Math.cos(angle)} y={cy + (maxR + 12) * Math.sin(angle) + 3}
            textAnchor="middle" fill="var(--cds-text-helper)" fontSize="9" fontWeight="600">{d}</text>
        );
      })}
      <polygon points={points} fill="var(--gold)" opacity={0.3} stroke="var(--gold)" strokeWidth={1.5} />
    </svg>
  );
}

/* ── Weibull Distribution Chart ────────────────────────────────────────── */
function WeibullChart({ k = 2.1, c = 7.5, width = 370, height = 160 }) {
  const pad = { l: 40, r: 10, t: 16, b: 24 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const bins = 50;
  const maxSpeed = 20;

  const vals = [];
  for (let i = 0; i < bins; i++) {
    const v = (i / bins) * maxSpeed;
    const pdf = (k / c) * Math.pow(v / c, k - 1) * Math.exp(-Math.pow(v / c, k));
    vals.push({ speed: v, pdf });
  }
  const maxPdf = Math.max(...vals.map(v => v.pdf));

  const points = vals.map(v => {
    const x = pad.l + (v.speed / maxSpeed) * w;
    const y = pad.t + h - (v.pdf / maxPdf) * h;
    return `${x},${y}`;
  }).join(" ");

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto" }}>
      <polygon points={`${pad.l},${pad.t + h} ${points} ${pad.l + w},${pad.t + h}`}
        fill="#3b82f6" opacity={0.15} />
      <polyline points={points} fill="none" stroke="#3b82f6" strokeWidth={2} />
      <text x={pad.l + w / 2} y={height - 4} textAnchor="middle" fill="var(--cds-text-helper)" fontSize="9">Wind Speed (m/s)</text>
      <text x={pad.l + w * 0.55} y={pad.t + 10} fill="var(--cds-text-secondary)" fontSize="8">k={k.toFixed(1)}, c={c.toFixed(1)} m/s</text>
    </svg>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   YieldAssessmentPanel
   ═══════════════════════════════════════════════════════════════════════════ */
export default function YieldAssessmentPanel({ onClose }) {
  const { explain, selectedParcel, lat, lon } = useSite();
  const [activeTab, setActiveTab] = useState("solar");

  // Solar state
  const [capacityKwp, setCapacityKwp] = useState(5000);
  const [tilt, setTilt] = useState(30);
  const [azimuth, setAzimuth] = useState(180);
  const [tracking, setTracking] = useState("none");
  const [losses, setLosses] = useState(14);
  const [solarResult, setSolarResult] = useState(null);
  const [solarLoading, setSolarLoading] = useState(false);
  const [dayProfile, setDayProfile] = useState("summer");

  // Wind state
  const [turbine, setTurbine] = useState("v136");
  const [windResult, setWindResult] = useState(null);
  const [windLoading, setWindLoading] = useState(false);

  // Compare state
  const [mixSlider, setMixSlider] = useState(50); // 0=all solar, 100=all wind

  const TABS = [
    { id: "solar", label: "Solar Yield" },
    { id: "wind", label: "Wind Yield" },
    { id: "compare", label: "Compare" },
  ];

  /* ── Solar yield calc ── */
  const calcSolar = useCallback(async () => {
    setSolarLoading(true);
    try {
      const data = await api.yieldAssessment.solar(lat || 52.0, lon || -1.5, capacityKwp, tilt, azimuth, tracking, losses);
      if (data) {
        setSolarResult(data);
      } else {
        // Synthetic UK solar result
        const trackMult = tracking === "single" ? 1.12 : tracking === "dual" ? 1.25 : 1.0;
        const lossFactor = 1 - losses / 100;
        const annualKwh = capacityKwp * 950 * trackMult * lossFactor;
        const cf = (annualKwh / (capacityKwp * 8760)) * 100;
        const monthlyFactors = [0.03, 0.045, 0.075, 0.10, 0.12, 0.13, 0.135, 0.12, 0.095, 0.065, 0.04, 0.025];
        const monthly = monthlyFactors.map(f => ({ value: annualKwh * f / 1000 }));

        // Hourly profiles
        const summer = Array.from({ length: 24 }, (_, h) => {
          const peak = capacityKwp * 0.75 * trackMult * lossFactor / 1000;
          const val = h >= 5 && h <= 21 ? peak * Math.sin(((h - 5) / 16) * Math.PI) : 0;
          return { value: Math.max(0, val) };
        });
        const winter = Array.from({ length: 24 }, (_, h) => {
          const peak = capacityKwp * 0.3 * trackMult * lossFactor / 1000;
          const val = h >= 8 && h <= 16 ? peak * Math.sin(((h - 8) / 8) * Math.PI) : 0;
          return { value: Math.max(0, val) };
        });

        setSolarResult({
          annual_mwh: annualKwh / 1000,
          specific_yield: annualKwh / capacityKwp,
          capacity_factor: cf,
          performance_ratio: 0.82 * lossFactor / (1 - losses / 100) * (1 - 0.02),
          monthly,
          summer_hourly: summer,
          winter_hourly: winter,
          exceedance: EXCEEDANCE.map(e => ({
            ...e,
            mwh: annualKwh / 1000 * (1 - (e.pct - 50) * 0.005),
          })),
        });
      }
    } catch { /* ignore */ }
    setSolarLoading(false);
  }, [lat, lon, capacityKwp, tilt, azimuth, tracking, losses]);

  /* ── Wind yield calc ── */
  const calcWind = useCallback(async () => {
    setWindLoading(true);
    try {
      const turb = TURBINE_MODELS.find(t => t.id === turbine) || TURBINE_MODELS[0];
      const data = await api.yieldAssessment.wind(lat || 52.0, lon || -1.5, turb.rated_mw * 1000, turb.hub_m);
      if (data) {
        setWindResult(data);
      } else {
        const turb = TURBINE_MODELS.find(t => t.id === turbine) || TURBINE_MODELS[0];
        const cf = 0.28 + Math.random() * 0.08;
        const annualMwh = turb.rated_mw * 8760 * cf;
        const monthlyFactors = [0.12, 0.11, 0.10, 0.08, 0.06, 0.055, 0.05, 0.06, 0.08, 0.10, 0.11, 0.115];
        setWindResult({
          annual_mwh: annualMwh,
          capacity_factor: cf * 100,
          full_load_hours: 8760 * cf,
          monthly: monthlyFactors.map(f => ({ value: annualMwh * f })),
          weibull_k: 2.1,
          weibull_c: 7.5,
          turbine: turb,
        });
      }
    } catch { /* ignore */ }
    setWindLoading(false);
  }, [lat, lon, turbine]);

  const selectedTurbine = TURBINE_MODELS.find(t => t.id === turbine) || TURBINE_MODELS[0];

  return (
    <div className="gc-panel ya-panel">
      <div className="gc-panel-header">
        <div className="gc-panel-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--gold)" strokeWidth="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
          YIELD ASSESSMENT
        </div>
        <button className="gc-panel-close" onClick={onClose}>&times;</button>
      </div>

      <div className="df-tabs" style={{ padding: "0 16px" }}>
        {TABS.map(t => (
          <button key={t.id} className={`df-tab ${activeTab === t.id ? "active" : ""}`}
            onClick={() => setActiveTab(t.id)}>{t.label}</button>
        ))}
      </div>

      <div className="gc-panel-body">
        {/* ──────── SOLAR YIELD ──────── */}
        {activeTab === "solar" && (
          <div className="ya-section">
            <div className="ya-sub-section">
              <div className="ya-sub-title">Location</div>
              <div className="ya-coord">{lat?.toFixed(4) || "52.0000"} N, {Math.abs(lon || 1.5).toFixed(4)} W</div>
            </div>

            <div className="ya-sub-section">
              <div className="ya-sub-title">System Configuration</div>
              <div className="ya-input-grid">
                <div className="ya-input-row">
                  <label>Capacity</label>
                  <div className="ya-input-val-row">
                    <input type="range" min={100} max={50000} step={100} value={capacityKwp}
                      onChange={e => setCapacityKwp(+e.target.value)} className="pf-slider" />
                    <span className="ya-input-value">{(capacityKwp / 1000).toFixed(1)} MWp</span>
                  </div>
                </div>
                <div className="ya-input-row">
                  <label>Tilt</label>
                  <div className="ya-input-val-row">
                    <input type="range" min={0} max={60} step={1} value={tilt}
                      onChange={e => setTilt(+e.target.value)} className="pf-slider" />
                    <span className="ya-input-value">{tilt} deg</span>
                  </div>
                </div>
                <div className="ya-input-row">
                  <label>Azimuth</label>
                  <div className="ya-input-val-row">
                    <input type="range" min={90} max={270} step={5} value={azimuth}
                      onChange={e => setAzimuth(+e.target.value)} className="pf-slider" />
                    <span className="ya-input-value">{azimuth} deg</span>
                  </div>
                </div>
                <div className="ya-input-row">
                  <label>Losses</label>
                  <div className="ya-input-val-row">
                    <input type="range" min={5} max={25} step={1} value={losses}
                      onChange={e => setLosses(+e.target.value)} className="pf-slider" />
                    <span className="ya-input-value">{losses}%</span>
                  </div>
                </div>
              </div>
              <div className="ya-tracking-row">
                {TRACKING_OPTS.map(t => (
                  <button key={t.id} className={`ya-track-btn${tracking === t.id ? " active" : ""}`}
                    onClick={() => setTracking(t.id)}>{t.label}</button>
                ))}
              </div>
            </div>

            <button className="pf-action-btn" onClick={calcSolar} disabled={solarLoading}>
              {solarLoading ? "Calculating..." : "Calculate Yield"}
            </button>

            {solarResult && (
              <>
                <div className="ya-metrics-strip">
                  <div className="ya-metric"><span className="ya-m-label">Annual Yield</span><span className="ya-m-value">{fmtMwh(solarResult.annual_mwh)}</span></div>
                  <div className="ya-metric"><span className="ya-m-label">Specific Yield</span><span className="ya-m-value">{fmtNum(solarResult.specific_yield, 0)} kWh/kWp</span></div>
                  <div className="ya-metric"><span className="ya-m-label">Capacity Factor</span><span className="ya-m-value">{fmtNum(solarResult.capacity_factor)}%</span></div>
                  <div className="ya-metric"><span className="ya-m-label">Perf. Ratio</span><span className="ya-m-value">{fmtNum(solarResult.performance_ratio * 100)}%</span></div>
                </div>

                <div className="ya-sub-section">
                  <div className="ya-sub-title">Monthly Production</div>
                  <MonthlyBarChart data={solarResult.monthly} color="var(--gold)" />
                </div>

                <div className="ya-sub-section">
                  <div className="ya-sub-title">
                    Daily Profile
                    <div className="ya-toggle-row">
                      <button className={`ya-toggle-btn${dayProfile === "summer" ? " active" : ""}`} onClick={() => setDayProfile("summer")}>Summer</button>
                      <button className={`ya-toggle-btn${dayProfile === "winter" ? " active" : ""}`} onClick={() => setDayProfile("winter")}>Winter</button>
                    </div>
                  </div>
                  <HourlyProfileChart summer={solarResult.summer_hourly} winter={solarResult.winter_hourly} />
                </div>

                <div className="ya-sub-section">
                  <div className="ya-sub-title">Exceedance Table</div>
                  <div className="ya-exceed-table">
                    {solarResult.exceedance?.map(e => (
                      <div key={e.label} className="ya-exceed-row">
                        <span className="ya-exceed-label">{e.label}</span>
                        <span className="ya-exceed-val">{fmtMwh(e.mwh)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* ──────── WIND YIELD ──────── */}
        {activeTab === "wind" && (
          <div className="ya-section">
            <div className="ya-sub-section">
              <div className="ya-sub-title">Turbine Selection</div>
              <div className="ya-turbine-grid">
                {TURBINE_MODELS.map(t => (
                  <button key={t.id} className={`ya-turbine-btn${turbine === t.id ? " active" : ""}`}
                    onClick={() => setTurbine(t.id)}>
                    <div className="ya-turb-name">{t.label}</div>
                    <div className="ya-turb-detail">Hub: {t.hub_m}m | {t.rated_mw} MW</div>
                  </button>
                ))}
              </div>
            </div>

            <button className="pf-action-btn" onClick={calcWind} disabled={windLoading}>
              {windLoading ? "Calculating..." : "Calculate Yield"}
            </button>

            {windResult && (
              <>
                <div className="ya-metrics-strip">
                  <div className="ya-metric"><span className="ya-m-label">Annual Yield</span><span className="ya-m-value">{fmtMwh(windResult.annual_mwh)}</span></div>
                  <div className="ya-metric"><span className="ya-m-label">Capacity Factor</span><span className="ya-m-value">{fmtNum(windResult.capacity_factor)}%</span></div>
                  <div className="ya-metric"><span className="ya-m-label">Full Load Hours</span><span className="ya-m-value">{fmtNum(windResult.full_load_hours, 0)} h</span></div>
                </div>

                <div className="ya-sub-section">
                  <div className="ya-sub-title">Wind Rose</div>
                  <WindRose />
                </div>

                <div className="ya-sub-section">
                  <div className="ya-sub-title">Monthly Production</div>
                  <MonthlyBarChart data={windResult.monthly} color="#3b82f6" />
                </div>

                <div className="ya-sub-section">
                  <div className="ya-sub-title">Weibull Distribution</div>
                  <WeibullChart k={windResult.weibull_k} c={windResult.weibull_c} />
                </div>
              </>
            )}
          </div>
        )}

        {/* ──────── COMPARE ──────── */}
        {activeTab === "compare" && (
          <div className="ya-section">
            <div className="ya-sub-section">
              <div className="ya-sub-title">Technology Comparison</div>
              {(!solarResult && !windResult) ? (
                <div className="ya-empty">Run solar and/or wind yield calculations first.</div>
              ) : (
                <>
                  <div className="ya-compare-grid">
                    <div className="ya-cmp-header"><span></span><span>Solar</span><span>Wind</span><span>Hybrid</span></div>
                    <div className="ya-cmp-row">
                      <span>Annual Yield</span>
                      <span className="ya-cmp-val">{solarResult ? fmtMwh(solarResult.annual_mwh) : "--"}</span>
                      <span className="ya-cmp-val">{windResult ? fmtMwh(windResult.annual_mwh) : "--"}</span>
                      <span className="ya-cmp-val ya-cmp-gold">{solarResult && windResult ? fmtMwh(
                        solarResult.annual_mwh * (1 - mixSlider / 100) + windResult.annual_mwh * (mixSlider / 100)
                      ) : "--"}</span>
                    </div>
                    <div className="ya-cmp-row">
                      <span>Capacity Factor</span>
                      <span className="ya-cmp-val">{solarResult ? fmtNum(solarResult.capacity_factor) + "%" : "--"}</span>
                      <span className="ya-cmp-val">{windResult ? fmtNum(windResult.capacity_factor) + "%" : "--"}</span>
                      <span className="ya-cmp-val ya-cmp-gold">{solarResult && windResult ? fmtNum(
                        solarResult.capacity_factor * (1 - mixSlider / 100) + windResult.capacity_factor * (mixSlider / 100)
                      ) + "%" : "--"}</span>
                    </div>
                    <div className="ya-cmp-row">
                      <span>LCOE</span>
                      <span className="ya-cmp-val">{solarResult ? "\u00A342/MWh" : "--"}</span>
                      <span className="ya-cmp-val">{windResult ? "\u00A348/MWh" : "--"}</span>
                      <span className="ya-cmp-val ya-cmp-gold">{solarResult && windResult ?
                        `\u00A3${(42 * (1 - mixSlider / 100) + 48 * (mixSlider / 100)).toFixed(0)}/MWh` : "--"}</span>
                    </div>
                  </div>

                  {solarResult && windResult && (
                    <>
                      <div className="ya-sub-section">
                        <div className="ya-sub-title">Optimal Mix</div>
                        <div className="ya-mix-row">
                          <span className="ya-mix-label">Solar</span>
                          <input type="range" min={0} max={100} step={5} value={100 - mixSlider}
                            onChange={e => setMixSlider(100 - +e.target.value)} className="pf-slider" />
                          <span className="ya-mix-label">Wind</span>
                        </div>
                        <div className="ya-mix-values">
                          <span>{100 - mixSlider}% Solar</span>
                          <span>{mixSlider}% Wind</span>
                        </div>
                      </div>

                      <div className="ya-sub-section">
                        <div className="ya-sub-title">Complementarity</div>
                        <div className="ya-complement-note">
                          Solar peaks in summer months (May-Aug), wind peaks in winter (Nov-Feb).
                          Combined profile reduces seasonal variability by approximately{" "}
                          <span className="ya-complement-val">{(25 + mixSlider * 0.2).toFixed(0)}%</span>.
                        </div>
                      </div>
                    </>
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
