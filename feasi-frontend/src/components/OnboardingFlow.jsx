import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import mapboxgl from "mapbox-gl";

/**
 * OnboardingFlow — 4-step first-run experience for Princeps.
 *
 * Steps:
 *  1. "What are you developing?" — technology card selection
 *  2. "Where?" — inline map picker or postcode/coordinate entry
 *  3. "How big?" — capacity slider with live cost/revenue preview
 *  4. "Here's your instant assessment" — calls /api/grid/assess, shows verdict
 *
 * Design: white bg, gold (#D4A018) accents, DM Sans, centered card layout.
 * Persists to localStorage so returning users skip onboarding.
 */

const LS_KEY = "princeps_onboarding_complete";
const LS_DATA_KEY = "princeps_onboarding_data";
const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || "";

// ── Brand tokens ──
const GOLD = "#D4A018";
const GOLD_LIGHT = "rgba(212, 160, 24, 0.10)";
const GOLD_BORDER = "rgba(212, 160, 24, 0.30)";
const DARK = "#111827";
const MUTED = "#6B7280";
const LIGHT_BG = "#F9FAFB";
const FONT = "'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

const VERDICT_COLORS = {
  GO: { bg: "rgba(22, 163, 74, 0.08)", border: "#16a34a", text: "#15803d", label: "GO" },
  CAUTION: { bg: "rgba(212, 160, 24, 0.08)", border: "#D4A018", text: "#a16207", label: "CAUTION" },
  "NO-GO": { bg: "rgba(220, 38, 38, 0.08)", border: "#dc2626", text: "#dc2626", label: "NO-GO" },
};

// ── Technology options ──
const TECHNOLOGIES = [
  {
    id: "solar",
    label: "Solar",
    icon: (
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
      </svg>
    ),
    desc: "Ground-mount or rooftop PV",
    benchmarks: { capex_per_mw: 550000, revenue_per_mw: 55000, cf: 0.11 },
  },
  {
    id: "wind",
    label: "Wind",
    icon: (
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M9.59 4.59A2 2 0 1 1 11 8H2m10.59 11.41A2 2 0 1 0 14 16H2m15.73-8.27A2.5 2.5 0 1 1 19.5 12H2" />
      </svg>
    ),
    desc: "Onshore or offshore turbines",
    benchmarks: { capex_per_mw: 1200000, revenue_per_mw: 95000, cf: 0.28 },
  },
  {
    id: "bess",
    label: "BESS",
    icon: (
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="6" y="7" width="12" height="14" rx="2" />
        <path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
        <line x1="10" y1="11" x2="10" y2="17" />
        <line x1="14" y1="11" x2="14" y2="17" />
      </svg>
    ),
    desc: "Battery energy storage",
    benchmarks: { capex_per_mw: 450000, revenue_per_mw: 75000, cf: null },
  },
  {
    id: "dc",
    label: "Data Centre",
    icon: (
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="4" width="18" height="6" rx="1" />
        <rect x="3" y="14" width="18" height="6" rx="1" />
        <circle cx="7" cy="7" r="1" fill="currentColor" />
        <circle cx="7" cy="17" r="1" fill="currentColor" />
      </svg>
    ),
    desc: "Hyperscale or edge facility",
    benchmarks: { capex_per_mw: 8000000, revenue_per_mw: 600000, cf: null },
  },
  {
    id: "hydrogen",
    label: "Hydrogen",
    icon: (
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="8" cy="8" r="4" />
        <circle cx="16" cy="16" r="4" />
        <path d="M12 4v16" />
      </svg>
    ),
    desc: "Green hydrogen electrolyser",
    benchmarks: { capex_per_mw: 1500000, revenue_per_mw: 80000, cf: null },
  },
];

// ── Utility: format GBP ──
function fmtGBP(v) {
  if (v >= 1e9) return "\u00A3" + (v / 1e9).toFixed(1) + "B";
  if (v >= 1e6) return "\u00A3" + (v / 1e6).toFixed(1) + "M";
  if (v >= 1e3) return "\u00A3" + (v / 1e3).toFixed(0) + "k";
  return "\u00A3" + v.toFixed(0);
}

// ── UK postcode regex ──
const UK_POSTCODE = /^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$/i;

// ── Geocode postcode via Mapbox ──
async function geocodePostcode(input) {
  const trimmed = input.trim();
  // Check for coordinate pair: lat,lon or lat lon
  const coordMatch = trimmed.match(/^(-?\d+\.?\d*)[,\s]+(-?\d+\.?\d*)$/);
  if (coordMatch) {
    const lat = parseFloat(coordMatch[1]);
    const lon = parseFloat(coordMatch[2]);
    if (lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
      return { lat, lon, label: `${lat.toFixed(4)}, ${lon.toFixed(4)}` };
    }
  }
  if (!MAPBOX_TOKEN) return null;
  try {
    const res = await fetch(
      `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(trimmed)}.json?country=gb&limit=1&access_token=${MAPBOX_TOKEN}`
    );
    const data = await res.json();
    if (data.features?.length > 0) {
      const [lon, lat] = data.features[0].center;
      return { lat, lon, label: data.features[0].place_name };
    }
  } catch { /* silent */ }
  return null;
}


// ═══════════════════════════════════════════════════
// Step 1: Technology selection
// ═══════════════════════════════════════════════════
function StepTechnology({ selected, onSelect }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 40 }}>
      <div style={{ textAlign: "center" }}>
        <h2 style={{ fontSize: 28, fontWeight: 700, color: DARK, margin: 0, letterSpacing: "-0.02em" }}>
          What are you developing?
        </h2>
        <p style={{ fontSize: 15, color: MUTED, marginTop: 10, maxWidth: 400, lineHeight: 1.5 }}>
          Select your technology type. This helps us tailor the feasibility analysis to your project.
        </p>
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
        gap: 14,
        width: "100%",
        maxWidth: 780,
      }}>
        {TECHNOLOGIES.map((tech) => {
          const active = selected === tech.id;
          return (
            <button
              key={tech.id}
              onClick={() => onSelect(tech.id)}
              style={{
                display: "flex", flexDirection: "column", alignItems: "center",
                gap: 10, padding: "24px 16px",
                background: active ? GOLD_LIGHT : "#fff",
                border: `1.5px solid ${active ? GOLD : "#E5E7EB"}`,
                borderRadius: 14,
                cursor: "pointer",
                transition: "all 0.2s ease",
                color: active ? GOLD : MUTED,
                fontFamily: FONT,
                outline: "none",
              }}
              onMouseEnter={(e) => {
                if (!active) {
                  e.currentTarget.style.borderColor = GOLD_BORDER;
                  e.currentTarget.style.background = "rgba(212, 160, 24, 0.03)";
                }
              }}
              onMouseLeave={(e) => {
                if (!active) {
                  e.currentTarget.style.borderColor = "#E5E7EB";
                  e.currentTarget.style.background = "#fff";
                }
              }}
            >
              <div style={{ color: active ? GOLD : "#9CA3AF" }}>{tech.icon}</div>
              <span style={{ fontSize: 15, fontWeight: 600, color: active ? DARK : "#374151" }}>
                {tech.label}
              </span>
              <span style={{ fontSize: 12, color: MUTED, textAlign: "center", lineHeight: 1.3 }}>
                {tech.desc}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════
// Step 2: Location picker (map + postcode)
// ═══════════════════════════════════════════════════
function StepLocation({ location, onSelect }) {
  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const [inputVal, setInputVal] = useState("");
  const [geocoding, setGeocoding] = useState(false);
  const [geocodeError, setGeocodeError] = useState(null);

  // Initialize map
  useEffect(() => {
    if (!mapContainerRef.current || !MAPBOX_TOKEN) return;
    mapboxgl.accessToken = MAPBOX_TOKEN;
    const map = new mapboxgl.Map({
      container: mapContainerRef.current,
      style: "mapbox://styles/mapbox/light-v11",
      center: [location?.lon ?? -1.5, location?.lat ?? 52.5],
      zoom: location ? 10 : 5.5,
      attributionControl: false,
    });
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");

    map.on("click", (e) => {
      const { lat, lng: lon } = e.lngLat;
      onSelect({ lat, lon, label: `${lat.toFixed(4)}, ${lon.toFixed(4)}` });
    });

    mapRef.current = map;
    return () => map.remove();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Sync marker
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !location) return;
    if (markerRef.current) markerRef.current.remove();
    const el = document.createElement("div");
    el.style.cssText = `width:20px;height:20px;border-radius:50%;background:${GOLD};border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,0.25);`;
    markerRef.current = new mapboxgl.Marker({ element: el }).setLngLat([location.lon, location.lat]).addTo(map);
    map.flyTo({ center: [location.lon, location.lat], zoom: 11, duration: 1200 });
  }, [location]);

  const handleGeocode = useCallback(async () => {
    if (!inputVal.trim()) return;
    setGeocoding(true);
    setGeocodeError(null);
    const result = await geocodePostcode(inputVal);
    if (result) {
      onSelect(result);
    } else {
      setGeocodeError("Could not find that location. Try a UK postcode or coordinates.");
    }
    setGeocoding(false);
  }, [inputVal, onSelect]);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 32 }}>
      <div style={{ textAlign: "center" }}>
        <h2 style={{ fontSize: 28, fontWeight: 700, color: DARK, margin: 0, letterSpacing: "-0.02em" }}>
          Where is your site?
        </h2>
        <p style={{ fontSize: 15, color: MUTED, marginTop: 10, maxWidth: 440, lineHeight: 1.5 }}>
          Click on the map or enter a postcode / coordinates below.
        </p>
      </div>

      {/* Search bar */}
      <div style={{ display: "flex", gap: 8, width: "100%", maxWidth: 480 }}>
        <input
          value={inputVal}
          onChange={(e) => setInputVal(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleGeocode()}
          placeholder="e.g. OX14 1SE or 52.76, -1.47"
          style={{
            flex: 1, padding: "10px 14px", fontSize: 14, fontFamily: FONT,
            border: "1.5px solid #E5E7EB", borderRadius: 10, outline: "none",
            transition: "border-color 0.2s",
            color: DARK, background: "#fff",
          }}
          onFocus={(e) => (e.target.style.borderColor = GOLD)}
          onBlur={(e) => (e.target.style.borderColor = "#E5E7EB")}
        />
        <button
          onClick={handleGeocode}
          disabled={geocoding}
          style={{
            padding: "10px 20px", fontSize: 14, fontWeight: 600, fontFamily: FONT,
            background: GOLD, color: "#fff", border: "none", borderRadius: 10,
            cursor: geocoding ? "wait" : "pointer", opacity: geocoding ? 0.7 : 1,
            transition: "opacity 0.2s",
          }}
        >
          {geocoding ? "..." : "Find"}
        </button>
      </div>
      {geocodeError && (
        <p style={{ fontSize: 13, color: "#dc2626", margin: "-16px 0 0 0" }}>{geocodeError}</p>
      )}

      {/* Map */}
      <div style={{
        width: "100%", maxWidth: 640, height: 320, borderRadius: 14,
        overflow: "hidden", border: "1.5px solid #E5E7EB",
        background: LIGHT_BG,
      }}>
        {MAPBOX_TOKEN ? (
          <div ref={mapContainerRef} style={{ width: "100%", height: "100%" }} />
        ) : (
          <div style={{
            width: "100%", height: "100%", display: "flex", alignItems: "center",
            justifyContent: "center", color: MUTED, fontSize: 13,
          }}>
            Map unavailable — enter coordinates above
          </div>
        )}
      </div>

      {location && (
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "8px 16px", background: GOLD_LIGHT, borderRadius: 8, border: `1px solid ${GOLD_BORDER}`,
        }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill={GOLD} stroke="none">
            <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5a2.5 2.5 0 0 1 0-5 2.5 2.5 0 0 1 0 5z" />
          </svg>
          <span style={{ fontSize: 13, color: DARK, fontWeight: 500 }}>
            {location.label || `${location.lat.toFixed(4)}, ${location.lon.toFixed(4)}`}
          </span>
        </div>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════
// Step 3: Capacity slider with live preview
// ═══════════════════════════════════════════════════
function StepCapacity({ technology, capacity, onCapacityChange }) {
  const tech = TECHNOLOGIES.find((t) => t.id === technology) || TECHNOLOGIES[0];
  const bm = tech.benchmarks;

  const capex = capacity * bm.capex_per_mw;
  const revenue = capacity * bm.revenue_per_mw;
  const annualEnergy = bm.cf ? Math.round(capacity * bm.cf * 8760) : null;

  // Logarithmic-ish tick marks
  const ticks = [1, 5, 10, 25, 50, 100, 200, 500];

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 40 }}>
      <div style={{ textAlign: "center" }}>
        <h2 style={{ fontSize: 28, fontWeight: 700, color: DARK, margin: 0, letterSpacing: "-0.02em" }}>
          How big is your project?
        </h2>
        <p style={{ fontSize: 15, color: MUTED, marginTop: 10, maxWidth: 400, lineHeight: 1.5 }}>
          Drag to set capacity. Cost and revenue estimates update in real time.
        </p>
      </div>

      {/* Capacity display */}
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: 56, fontWeight: 800, color: DARK, letterSpacing: "-0.03em", lineHeight: 1 }}>
          {capacity}
          <span style={{ fontSize: 22, fontWeight: 500, color: MUTED, marginLeft: 6 }}>MW</span>
        </div>
      </div>

      {/* Slider */}
      <div style={{ width: "100%", maxWidth: 520 }}>
        <input
          type="range"
          min={1}
          max={500}
          step={1}
          value={capacity}
          onChange={(e) => onCapacityChange(parseInt(e.target.value, 10))}
          style={{
            width: "100%", height: 6, appearance: "none", WebkitAppearance: "none",
            background: `linear-gradient(to right, ${GOLD} ${(capacity / 500) * 100}%, #E5E7EB ${(capacity / 500) * 100}%)`,
            borderRadius: 3, outline: "none", cursor: "pointer",
            accentColor: GOLD,
          }}
        />
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
          {ticks.map((t) => (
            <button
              key={t}
              onClick={() => onCapacityChange(t)}
              style={{
                background: "none", border: "none", cursor: "pointer",
                fontSize: 11, color: capacity === t ? GOLD : MUTED, fontWeight: capacity === t ? 700 : 400,
                fontFamily: FONT, padding: "2px 4px",
              }}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Live metrics */}
      <div style={{
        display: "grid", gridTemplateColumns: annualEnergy ? "1fr 1fr 1fr" : "1fr 1fr",
        gap: 20, width: "100%", maxWidth: 520,
      }}>
        <MetricBox label="Est. CAPEX" value={fmtGBP(capex)} sub="total project cost" />
        <MetricBox label="Annual Revenue" value={fmtGBP(revenue)} sub="estimated gross" />
        {annualEnergy && (
          <MetricBox label="Annual Energy" value={`${annualEnergy.toLocaleString()} MWh`} sub={`${(bm.cf * 100).toFixed(0)}% capacity factor`} />
        )}
      </div>
    </div>
  );
}

function MetricBox({ label, value, sub }) {
  return (
    <div style={{
      padding: "20px 16px", background: LIGHT_BG, borderRadius: 12,
      border: "1px solid #E5E7EB", textAlign: "center",
    }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: MUTED, textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: DARK, marginTop: 6, letterSpacing: "-0.01em" }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 11, color: MUTED, marginTop: 4 }}>{sub}</div>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════
// Step 4: Instant assessment result
// ═══════════════════════════════════════════════════
function StepAssessment({ technology, location, capacity, onDeepDive }) {
  const [loading, setLoading] = useState(true);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({
          lat: location.lat,
          lon: location.lon,
          capacity_mw: capacity,
          technology: technology === "dc" ? "solar" : technology === "hydrogen" ? "solar" : technology,
        });
        const res = await fetch(`/api/grid/assess?${params}`, { method: "POST" });
        if (!res.ok) throw new Error(`Server returned ${res.status}`);
        const data = await res.json();
        if (!cancelled) setResult(data);
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [technology, location, capacity]);

  const verdict = result?.verdict || result?.grid_assessment?.verdict || "CAUTION";
  const vc = VERDICT_COLORS[verdict] || VERDICT_COLORS.CAUTION;

  // Extract key metrics from response
  const headroom = result?.candidates?.[0]?.headroom_mw
    ?? result?.grid_assessment?.headroom_mw
    ?? result?.nearest_substation?.headroom_mw
    ?? null;
  const nearestSub = result?.candidates?.[0]?.name
    ?? result?.grid_assessment?.substation_name
    ?? result?.nearest_substation?.name
    ?? null;
  const distKm = result?.candidates?.[0]?.distance_km
    ?? result?.grid_assessment?.distance_km
    ?? result?.nearest_substation?.distance_km
    ?? null;
  const costEst = result?.connection_cost?.p50_gbp
    ?? result?.candidates?.[0]?.connection_cost?.p50_gbp
    ?? null;
  const constraints = result?.constraints || result?.environmental_constraints || [];
  const constraintCount = Array.isArray(constraints) ? constraints.length : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 32 }}>
      <div style={{ textAlign: "center" }}>
        <h2 style={{ fontSize: 28, fontWeight: 700, color: DARK, margin: 0, letterSpacing: "-0.02em" }}>
          Your instant assessment
        </h2>
        <p style={{ fontSize: 15, color: MUTED, marginTop: 10, maxWidth: 440, lineHeight: 1.5 }}>
          Based on grid data, constraints, and your project parameters.
        </p>
      </div>

      {loading ? (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16, padding: "48px 0" }}>
          <div style={{
            width: 36, height: 36, border: `3px solid #E5E7EB`, borderTopColor: GOLD,
            borderRadius: "50%", animation: "onboarding-spin 0.8s linear infinite",
          }} />
          <span style={{ fontSize: 14, color: MUTED }}>Analysing site feasibility...</span>
        </div>
      ) : error ? (
        <div style={{
          padding: "32px 40px", background: "rgba(220, 38, 38, 0.05)", borderRadius: 14,
          border: "1px solid rgba(220, 38, 38, 0.2)", textAlign: "center", maxWidth: 440,
        }}>
          <p style={{ fontSize: 14, color: "#dc2626", margin: 0 }}>
            Could not reach the assessment service. You can still explore the platform manually.
          </p>
          <p style={{ fontSize: 12, color: MUTED, marginTop: 8 }}>{error}</p>
        </div>
      ) : (
        <>
          {/* Verdict badge */}
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 12,
            padding: "16px 32px", background: vc.bg, borderRadius: 14,
            border: `1.5px solid ${vc.border}`,
          }}>
            <div style={{
              width: 14, height: 14, borderRadius: "50%", background: vc.border,
              boxShadow: `0 0 12px ${vc.border}40`,
            }} />
            <span style={{ fontSize: 28, fontWeight: 800, color: vc.text, letterSpacing: "0.04em" }}>
              {vc.label}
            </span>
          </div>

          {/* Metrics grid */}
          <div style={{
            display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14,
            width: "100%", maxWidth: 480,
          }}>
            {headroom !== null && (
              <AssessMetric
                label="Grid Headroom"
                value={`${headroom.toFixed?.(0) ?? headroom} MW`}
                good={headroom >= capacity}
              />
            )}
            {nearestSub && (
              <AssessMetric
                label="Nearest Substation"
                value={nearestSub}
                sub={distKm != null ? `${distKm.toFixed?.(1) ?? distKm} km away` : null}
              />
            )}
            {costEst !== null && (
              <AssessMetric label="Connection Cost (P50)" value={fmtGBP(costEst)} />
            )}
            {constraintCount > 0 && (
              <AssessMetric
                label="Constraints Found"
                value={`${constraintCount}`}
                good={false}
              />
            )}
            {headroom === null && nearestSub === null && costEst === null && constraintCount === 0 && (
              <div style={{ gridColumn: "1 / -1", textAlign: "center", padding: 16, color: MUTED, fontSize: 13 }}>
                Assessment returned limited data. Use Deep Dive for a full analysis.
              </div>
            )}
          </div>

          {/* Deep dive CTA */}
          <button
            onClick={onDeepDive}
            style={{
              padding: "14px 36px", fontSize: 15, fontWeight: 700, fontFamily: FONT,
              background: GOLD, color: "#fff", border: "none", borderRadius: 12,
              cursor: "pointer", transition: "all 0.2s",
              boxShadow: "0 2px 12px rgba(212, 160, 24, 0.3)",
              letterSpacing: "0.01em",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.boxShadow = "0 4px 20px rgba(212, 160, 24, 0.45)")}
            onMouseLeave={(e) => (e.currentTarget.style.boxShadow = "0 2px 12px rgba(212, 160, 24, 0.3)")}
          >
            Deep Dive Analysis
          </button>
        </>
      )}
    </div>
  );
}

function AssessMetric({ label, value, sub, good }) {
  return (
    <div style={{
      padding: "16px 18px", background: "#fff", borderRadius: 12,
      border: "1px solid #E5E7EB",
    }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: MUTED, textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {label}
      </div>
      <div style={{
        fontSize: 17, fontWeight: 700, marginTop: 6, letterSpacing: "-0.01em",
        color: good === true ? "#16a34a" : good === false ? "#D4A018" : DARK,
      }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 11, color: MUTED, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}


// ═══════════════════════════════════════════════════
// Progress dots
// ═══════════════════════════════════════════════════
function ProgressDots({ current, total }) {
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      {Array.from({ length: total }, (_, i) => (
        <div
          key={i}
          style={{
            width: i === current ? 24 : 8,
            height: 8,
            borderRadius: 4,
            background: i === current ? GOLD : i < current ? GOLD : "#E5E7EB",
            opacity: i < current ? 0.4 : 1,
            transition: "all 0.3s ease",
          }}
        />
      ))}
    </div>
  );
}


// ═══════════════════════════════════════════════════
// Main: OnboardingFlow
// ═══════════════════════════════════════════════════
export function isOnboardingComplete() {
  try { return localStorage.getItem(LS_KEY) === "true"; } catch { return false; }
}

export function resetOnboarding() {
  try {
    localStorage.removeItem(LS_KEY);
    localStorage.removeItem(LS_DATA_KEY);
  } catch { /* silent */ }
}

export default function OnboardingFlow({ onComplete, onSkip }) {
  const [step, setStep] = useState(0);
  const [technology, setTechnology] = useState(null);
  const [location, setLocation] = useState(null);
  const [capacity, setCapacity] = useState(50);

  const STEP_COUNT = 4;
  const STEP_LABELS = ["Technology", "Location", "Capacity", "Assessment"];

  const canAdvance = useMemo(() => {
    if (step === 0) return !!technology;
    if (step === 1) return !!location;
    if (step === 2) return capacity >= 1;
    return true;
  }, [step, technology, location, capacity]);

  const finish = useCallback((data) => {
    try {
      localStorage.setItem(LS_KEY, "true");
      if (data) localStorage.setItem(LS_DATA_KEY, JSON.stringify(data));
    } catch { /* silent */ }
    onComplete?.(data);
  }, [onComplete]);

  const handleSkip = useCallback(() => {
    try { localStorage.setItem(LS_KEY, "true"); } catch { /* silent */ }
    onSkip?.();
  }, [onSkip]);

  const handleNext = useCallback(() => {
    if (step < STEP_COUNT - 1) {
      setStep((s) => s + 1);
    }
  }, [step]);

  const handleBack = useCallback(() => {
    if (step > 0) setStep((s) => s - 1);
  }, [step]);

  const handleDeepDive = useCallback(() => {
    finish({ technology, location, capacity });
  }, [technology, location, capacity, finish]);

  // Auto-advance on technology selection
  const handleTechSelect = useCallback((id) => {
    setTechnology(id);
    // Brief delay so the user sees their selection highlight before advancing
    setTimeout(() => setStep(1), 300);
  }, []);

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 99999,
      background: "#fff",
      display: "flex", flexDirection: "column",
      fontFamily: FONT,
      overflow: "auto",
    }}>
      {/* Keyframes for spinner */}
      <style>{`
        @keyframes onboarding-spin { to { transform: rotate(360deg); } }
        input[type="range"]::-webkit-slider-thumb {
          -webkit-appearance: none; appearance: none;
          width: 22px; height: 22px; border-radius: 50%;
          background: ${GOLD}; border: 3px solid #fff;
          box-shadow: 0 1px 6px rgba(0,0,0,0.18);
          cursor: pointer;
        }
        input[type="range"]::-moz-range-thumb {
          width: 22px; height: 22px; border-radius: 50%;
          background: ${GOLD}; border: 3px solid #fff;
          box-shadow: 0 1px 6px rgba(0,0,0,0.18);
          cursor: pointer;
        }
      `}</style>

      {/* Header */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "20px 32px", flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 7, background: GOLD,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="#fff" stroke="none">
              <path d="M13 3L4 14h7l-1 7 9-11h-7l1-7z" />
            </svg>
          </div>
          <span style={{ fontSize: 16, fontWeight: 700, color: DARK, letterSpacing: "-0.02em" }}>
            Princeps
          </span>
        </div>
        <button
          onClick={handleSkip}
          style={{
            background: "none", border: "none", cursor: "pointer",
            fontSize: 13, color: MUTED, fontFamily: FONT, fontWeight: 500,
            padding: "6px 12px", borderRadius: 6,
            transition: "color 0.2s",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.color = DARK)}
          onMouseLeave={(e) => (e.currentTarget.style.color = MUTED)}
        >
          Skip setup
        </button>
      </div>

      {/* Content area */}
      <div style={{
        flex: 1, display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        padding: "0 32px 32px",
        minHeight: 0,
      }}>
        <div style={{ width: "100%", maxWidth: 800 }}>
          {step === 0 && (
            <StepTechnology selected={technology} onSelect={handleTechSelect} />
          )}
          {step === 1 && (
            <StepLocation location={location} onSelect={setLocation} />
          )}
          {step === 2 && (
            <StepCapacity technology={technology} capacity={capacity} onCapacityChange={setCapacity} />
          )}
          {step === 3 && (
            <StepAssessment
              technology={technology}
              location={location}
              capacity={capacity}
              onDeepDive={handleDeepDive}
            />
          )}
        </div>
      </div>

      {/* Footer: dots + nav buttons */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "20px 32px", flexShrink: 0,
        borderTop: "1px solid #F3F4F6",
      }}>
        <div style={{ width: 80 }}>
          {step > 0 && (
            <button
              onClick={handleBack}
              style={{
                background: "none", border: "1.5px solid #E5E7EB", borderRadius: 10,
                padding: "8px 18px", fontSize: 13, fontWeight: 600, fontFamily: FONT,
                color: MUTED, cursor: "pointer", transition: "all 0.2s",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = GOLD_BORDER; e.currentTarget.style.color = DARK; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = "#E5E7EB"; e.currentTarget.style.color = MUTED; }}
            >
              Back
            </button>
          )}
        </div>

        <ProgressDots current={step} total={STEP_COUNT} />

        <div style={{ width: 80, display: "flex", justifyContent: "flex-end" }}>
          {step > 0 && step < STEP_COUNT - 1 && (
            <button
              onClick={handleNext}
              disabled={!canAdvance}
              style={{
                background: canAdvance ? GOLD : "#E5E7EB",
                color: canAdvance ? "#fff" : "#9CA3AF",
                border: "none", borderRadius: 10,
                padding: "8px 22px", fontSize: 13, fontWeight: 600, fontFamily: FONT,
                cursor: canAdvance ? "pointer" : "not-allowed",
                transition: "all 0.2s",
                boxShadow: canAdvance ? "0 1px 8px rgba(212, 160, 24, 0.2)" : "none",
              }}
            >
              Next
            </button>
          )}
          {step === STEP_COUNT - 1 && (
            <button
              onClick={handleDeepDive}
              style={{
                background: "none", border: "1.5px solid #E5E7EB", borderRadius: 10,
                padding: "8px 18px", fontSize: 13, fontWeight: 600, fontFamily: FONT,
                color: MUTED, cursor: "pointer", transition: "all 0.2s",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = GOLD_BORDER; e.currentTarget.style.color = DARK; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = "#E5E7EB"; e.currentTarget.style.color = MUTED; }}
            >
              Done
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
