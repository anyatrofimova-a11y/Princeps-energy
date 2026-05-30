import React, { useCallback, useEffect, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import "./scope.css";
import {
  VerdictPill,
  SubstationRow,
  CostBars,
  PlanningCard,
  DraftApplication,
  StepsList,
} from "./ScopeCards.jsx";

mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN || "";

/**
 * /v2/scope — the YC pitch demo, end-to-end in under 15s.
 *
 * Click a UK location → POST /api/agent/analyze-site → render progressive
 * analysis steps (left rail) + structured response card (right rail) +
 * pre-filled Gate-2 application. Numbers are deterministic so the same pin
 * always tells the same story; the verdict rationale is a live Claude call.
 */

const TECH_OPTIONS = ["BESS", "Solar", "Onshore Wind", "Data Centre"];

const PLACEHOLDER_STEPS = [
  { label: "Loading grid topology within 10 km radius…", detail: "" },
  { label: "Cross-referencing REPD planning decisions…", detail: "" },
  { label: "Pulling current TEC queue position from NESO…", detail: "" },
  { label: "Running pandapower load flow against NGED LTDS topology…", detail: "" },
  { label: "Claude reasoning over ontology graph (47k nodes, 218k edges)…", detail: "" },
];

export default function ScopePage() {
  const mapRef = useRef(null);
  const mapContainerRef = useRef(null);
  const markerRef = useRef(null);
  const [tech, setTech] = useState("BESS");
  const [capacity, setCapacity] = useState(50);
  const [pin, setPin] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [completedSteps, setCompletedSteps] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef(null);
  const stepTimers = useRef([]);

  // Keep latest tech/capacity for the click handler so a re-render isn't
  // required for the next pin to pick up the new selection.
  const techRef = useRef(tech);
  const capRef = useRef(capacity);
  useEffect(() => { techRef.current = tech; }, [tech]);
  useEffect(() => { capRef.current = capacity; }, [capacity]);

  // ── Map init ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;
    if (!mapboxgl.accessToken) {
      setError("Mapbox token missing — set VITE_MAPBOX_TOKEN in feasi-frontend/.env");
      return;
    }
    const map = new mapboxgl.Map({
      container: mapContainerRef.current,
      style: "mapbox://styles/mapbox/light-v11",
      center: [-2.5, 54.2],
      zoom: 5.2,
      attributionControl: false,
    });
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-left");
    map.on("click", (e) => handlePinDrop(e.lngLat.lat, e.lngLat.lng));
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Timers ───────────────────────────────────────────────────────────
  const resetTimers = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    stepTimers.current.forEach((t) => clearTimeout(t));
    stepTimers.current = [];
  }, []);
  useEffect(() => () => resetTimers(), [resetTimers]);

  // ── Pin handling ─────────────────────────────────────────────────────
  const handlePinDrop = useCallback((lat, lon) => {
    if (!mapRef.current) return;
    if (lat < 49 || lat > 61 || lon < -9 || lon > 2.5) {
      setError("Pick a point inside the UK.");
      return;
    }
    setError(null);
    setPin({ lat, lon });
    if (markerRef.current) markerRef.current.remove();
    markerRef.current = new mapboxgl.Marker({ color: "#F5B731" })
      .setLngLat([lon, lat])
      .addTo(mapRef.current);
    runAnalysis(lat, lon);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runAnalysis = async (lat, lon) => {
    resetTimers();
    setLoading(true);
    setResult(null);
    setCompletedSteps(0);
    setElapsed(0);

    const t0 = performance.now();
    timerRef.current = setInterval(() => {
      setElapsed((performance.now() - t0) / 1000);
    }, 100);

    try {
      const resp = await fetch("/api/agent/analyze-site", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lat, lon,
          technology: techRef.current,
          capacity_mw: capRef.current,
        }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const j = await resp.json();
      setResult(j);
      animateSteps(j.steps?.length || 5);
    } catch (e) {
      setError(`Analysis failed: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const animateSteps = (n) => {
    // Reveal each step ~600ms apart so the rail unfurls cinematically even
    // though the backend already returned all the data in one shot.
    for (let i = 1; i <= n; i++) {
      const t = setTimeout(() => setCompletedSteps(i), i * 600);
      stepTimers.current.push(t);
    }
  };

  // Stop the elapsed clock once the last step is in.
  useEffect(() => {
    if (
      result &&
      completedSteps >= (result.steps?.length || 5) &&
      timerRef.current
    ) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, [completedSteps, result]);

  const resetPin = () => {
    if (markerRef.current) markerRef.current.remove();
    markerRef.current = null;
    setPin(null);
    setResult(null);
    setCompletedSteps(0);
    resetTimers();
  };

  // ── Render ───────────────────────────────────────────────────────────
  const portfolio = result?.portfolio_overlap || [];
  const grid = result?.grid_context;
  const top3 = result?.substations || [];

  return (
    <div className="scope-page">
      <div className="scope-map-wrap">
        <div ref={mapContainerRef} className="scope-map" />
        {!pin && (
          <div className="scope-prompt">
            <div className="scope-prompt-eyebrow">SCOPE A SITE</div>
            <div className="scope-prompt-title">Click anywhere on the UK</div>
            <div className="scope-prompt-sub">
              Drop a pin. We will pull grid topology, REPD precedent, queue
              position, and run a load flow against the local DNO LTDS in under
              15 seconds.
            </div>
          </div>
        )}
        {pin && (
          <div className="scope-pin-chip">
            <span className="scope-pin-dot" />
            {pin.lat.toFixed(4)}, {pin.lon.toFixed(4)}
            <button className="scope-pin-reset" type="button" onClick={resetPin}>
              ×
            </button>
          </div>
        )}
        <div className="scope-controls">
          <label className="scope-control">
            <span>Technology</span>
            <select
              value={tech}
              onChange={(e) => setTech(e.target.value)}
              disabled={loading}
            >
              {TECH_OPTIONS.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </label>
          <label className="scope-control">
            <span>Capacity (MW)</span>
            <input
              type="number"
              min={1}
              max={2000}
              step={5}
              value={capacity}
              onChange={(e) => setCapacity(Number(e.target.value) || 1)}
              disabled={loading}
            />
          </label>
        </div>
      </div>

      <aside className="scope-rail scope-rail-left">
        <div className="scope-rail-head">
          <div className="scope-rail-eyebrow">ANALYSIS</div>
          <div className="scope-rail-title">What is happening</div>
        </div>
        {!pin && (
          <div className="scope-empty">
            Pick a UK location to begin. The agent will dispatch to the grid
            topology graph, the planning model, and the power-flow simulator.
          </div>
        )}
        {pin && (
          <StepsList
            steps={result?.steps || PLACEHOLDER_STEPS}
            completedCount={completedSteps}
          />
        )}
        {error && <div className="scope-error">{error}</div>}
      </aside>

      <aside className="scope-rail scope-rail-right">
        <div className="scope-rail-head">
          <div className="scope-rail-eyebrow">RESPONSE</div>
          <div className="scope-rail-title">
            {result ? "Structured site brief" : "Awaiting pin"}
          </div>
        </div>

        {result && (
          <>
            <VerdictPill verdict={result.verdict} />

            <section className="scope-section">
              <div className="scope-section-h">Substation options (ranked)</div>
              {top3.map((s, i) => <SubstationRow key={i} s={s} />)}
            </section>

            <section className="scope-section">
              <div className="scope-section-h">Connection cost (£)</div>
              <CostBars costs={result.cost_estimates} />
            </section>

            <section className="scope-section">
              <div className="scope-section-h">Queue position</div>
              <div className="scope-queue">
                <div className="scope-queue-num">#{result.queue?.position}</div>
                <div className="scope-queue-meta">
                  <div>{result.queue?.total_mw_ahead} MW ahead</div>
                  <div className="scope-queue-eta">
                    Projected energisation {result.queue?.eta_energisation}
                  </div>
                </div>
              </div>
            </section>

            <section className="scope-section">
              <div className="scope-section-h">Planning risk</div>
              <PlanningCard planning={result.planning} />
            </section>

            {(portfolio.length > 0 || grid) && (
              <section className="scope-section">
                <div className="scope-section-h">Local context</div>
                {grid && (
                  <div className="scope-context-row">
                    <span>GB demand</span>
                    <span className="scope-context-v">
                      {grid.demand_gw} GW · {grid.carbon_intensity_g_per_kwh} gCO₂/kWh
                    </span>
                  </div>
                )}
                {portfolio.length > 0 && (
                  <div className="scope-context-portfolio">
                    <div className="scope-context-h">Portfolio overlap</div>
                    {portfolio.map((p) => (
                      <div key={p.name} className="scope-context-row">
                        <span>{p.name}</span>
                        <span className="scope-context-v">{p.distance_km} km</span>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            )}

            <DraftApplication draft={result.draft_application} />
          </>
        )}
      </aside>

      <footer className="scope-footer">
        <div className="scope-footer-left">
          <span className="scope-footer-eyebrow">Time elapsed</span>
          <span className="scope-footer-strong">{elapsed.toFixed(1)}s</span>
        </div>
        <div className="scope-footer-divider" />
        <div className="scope-footer-right">
          <span className="scope-footer-eyebrow">Consultancy baseline</span>
          <span className="scope-footer-strong scope-footer-faint">4,320 hours</span>
        </div>
        {result && (
          <div className="scope-footer-sources">
            {result.provenance?.sources?.slice(0, 4).join(" · ")}
          </div>
        )}
      </footer>
    </div>
  );
}
