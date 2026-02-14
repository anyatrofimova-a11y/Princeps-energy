import React, { useState, useEffect, useRef } from "react";
import { useSite } from "../../SiteContext";
import MetricCard from "../ui/MetricCard";
import api from "../../services/api";

const LAND_USE_COLORS = {
  water: "#2196f3",
  trees: "#2e7d32",
  grass: "#8bc34a",
  flooded_vegetation: "#00897b",
  crops: "#ffc107",
  shrub_and_scrub: "#795548",
  built: "#9e9e9e",
  bare: "#d7ccc8",
  snow_and_ice: "#e3f2fd",
};

function LandUsePie({ data }) {
  if (!data?.class_percentages) return null;
  const entries = Object.entries(data.class_percentages).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, v]) => s + v, 0) || 1;

  return (
    <div style={{ marginBottom: 10 }}>
      <div className="card-label">Land Use Classification</div>
      <div style={{ display: "flex", height: 18, borderRadius: 4, overflow: "hidden", marginBottom: 6 }}>
        {entries.map(([cls, pct]) => (
          <div
            key={cls}
            style={{
              width: `${(pct / total) * 100}%`,
              background: LAND_USE_COLORS[cls] || "#666",
              minWidth: pct > 1 ? 2 : 0,
            }}
            title={`${cls}: ${pct}%`}
          />
        ))}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 10px", fontSize: 11 }}>
        {entries.filter(([, v]) => v >= 1).map(([cls, pct]) => (
          <span key={cls}>
            <span style={{
              display: "inline-block", width: 8, height: 8, borderRadius: 2,
              background: LAND_USE_COLORS[cls] || "#666", marginRight: 3,
            }} />
            {cls.replace(/_/g, " ")}: {pct}%
          </span>
        ))}
      </div>
    </div>
  );
}

function TerrainStats({ data }) {
  if (!data?.elevation) return null;
  return (
    <div style={{ marginBottom: 10 }}>
      <div className="card-label">Terrain</div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 12 }}>
        <span>Elevation: <b>{data.elevation.mean_m}m</b> (range {data.elevation.min_m}–{data.elevation.max_m}m)</span>
        <span>Slope: <b>{data.slope.mean_deg}°</b> avg, {data.slope.p90_deg}° p90</span>
        <span>South-facing: <b>{data.aspect.south_facing_pct}%</b></span>
      </div>
    </div>
  );
}

function SolarResourceBars({ data }) {
  if (!data?.monthly) return null;
  const maxGhi = Math.max(...data.monthly.map(m => m.ghi_kwh_m2_day || 0), 1);
  return (
    <div style={{ marginBottom: 10 }}>
      <div className="card-label">Solar Resource (ERA5)</div>
      <div style={{ display: "flex", gap: 2, alignItems: "flex-end", height: 50 }}>
        {data.monthly.map((m, i) => (
          <div
            key={i}
            style={{
              flex: 1,
              height: `${((m.ghi_kwh_m2_day || 0) / maxGhi) * 100}%`,
              background: "#ff9800",
              borderRadius: "2px 2px 0 0",
              minHeight: 2,
            }}
            title={`Month ${m.month}: ${m.ghi_kwh_m2_day} kWh/m²/day, ${m.temperature_c}°C`}
          />
        ))}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "#888", marginTop: 2 }}>
        <span>Jan</span><span>Jul</span><span>Dec</span>
      </div>
      <div style={{ fontSize: 12, marginTop: 4 }}>
        Annual GHI: <b>{data.annual_ghi_kwh_m2} kWh/m²</b>
      </div>
    </div>
  );
}

function ScoreGauge({ score }) {
  if (!score) return null;
  const pct = (score.total_score / score.max_score) * 100;
  const color = score.recommendation === "GO" ? "#4caf50" : score.recommendation === "CAUTION" ? "#ff9800" : "#f44336";
  return (
    <div style={{ marginBottom: 10 }}>
      <div className="card-label">Suitability Score</div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 4 }}>
        <div style={{
          width: "100%", height: 10, borderRadius: 5,
          background: "#1a1a2e", overflow: "hidden",
        }}>
          <div style={{
            width: `${pct}%`, height: "100%",
            background: color, borderRadius: 5,
            transition: "width 0.5s ease",
          }} />
        </div>
        <span style={{ color, fontWeight: "bold", fontSize: 16, minWidth: 40, textAlign: "right" }}>
          {score.total_score}
        </span>
        <span style={{
          padding: "2px 8px", borderRadius: 8,
          background: color, color: "#fff", fontSize: 11, fontWeight: "bold",
        }}>
          {score.recommendation}
        </span>
      </div>
      <div style={{ fontSize: 11, color: "#aaa", marginTop: 4 }}>{score.summary}</div>
    </div>
  );
}

export default function SatelliteCard() {
  const {
    pickedLocation, geeflowData, setGeeflowData,
    geeflowLoading, setGeeflowLoading,
    geeflowJobId, setGeeflowJobId,
  } = useSite();

  const pollRef = useRef(null);

  // Poll for job completion
  useEffect(() => {
    if (!geeflowJobId) return;
    const poll = setInterval(async () => {
      const status = await api.geeflow.jobStatus(geeflowJobId);
      if (!status) return;
      if (status.status === "done") {
        setGeeflowData(status.result);
        setGeeflowLoading(false);
        setGeeflowJobId(null);
        clearInterval(poll);
      } else if (status.status === "failed") {
        setGeeflowLoading(false);
        setGeeflowJobId(null);
        clearInterval(poll);
      }
    }, 3000);
    pollRef.current = poll;
    return () => clearInterval(poll);
  }, [geeflowJobId, setGeeflowData, setGeeflowLoading, setGeeflowJobId]);

  const handleRun = async () => {
    if (!pickedLocation) return;
    setGeeflowLoading(true);
    setGeeflowData(null);
    const res = await api.geeflow.submitAnalysis(
      pickedLocation.lat, pickedLocation.lon, 5,
      ["land_use", "terrain", "solar_resource", "vegetation"]
    );
    if (res?.job_id) {
      setGeeflowJobId(res.job_id);
    } else {
      setGeeflowLoading(false);
    }
  };

  const extractions = geeflowData?.extractions || {};
  const score = geeflowData?.site_score;
  const headerVal = score ? `${score.total_score}/100` : null;

  return (
    <MetricCard
      title="Satellite"
      accentColor="#1565c0"
      headerValue={headerVal}
      aiInsight={score?.summary?.slice(0, 100)}
    >
      {!geeflowData && !geeflowLoading && (
        <div style={{ textAlign: "center", padding: "12px 0" }}>
          <button
            className="btn-primary"
            onClick={handleRun}
            disabled={!pickedLocation}
            style={{ fontSize: 12 }}
          >
            Run Satellite Analysis
          </button>
          {!pickedLocation && (
            <div className="muted" style={{ marginTop: 6, fontSize: 11 }}>
              Pick a site location first
            </div>
          )}
        </div>
      )}

      {geeflowLoading && (
        <div style={{ textAlign: "center", padding: "16px 0", color: "#00e5ff" }}>
          <div className="spinner" /> Analysing satellite data...
        </div>
      )}

      {geeflowData && (
        <>
          <ScoreGauge score={score} />
          <LandUsePie data={extractions.land_use} />
          <TerrainStats data={extractions.terrain} />
          <SolarResourceBars data={extractions.solar_resource} />

          {extractions.vegetation && (
            <div style={{ fontSize: 12 }}>
              <div className="card-label">Vegetation</div>
              Green cover: <b>{extractions.vegetation.green_cover_pct}%</b>,
              NDVI: <b>{extractions.vegetation.annual_ndvi_mean}</b>
            </div>
          )}

          <button
            className="btn-primary"
            onClick={handleRun}
            disabled={geeflowLoading}
            style={{ marginTop: 10, fontSize: 11, opacity: 0.7 }}
          >
            Re-run Analysis
          </button>
        </>
      )}
    </MetricCard>
  );
}
