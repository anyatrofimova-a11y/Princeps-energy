import React, { useState, useEffect, useRef } from "react";
import { useSite } from "../../SiteContext";
import MetricCard from "../ui/MetricCard";
import ImageUploader from "../ImageUploader";
import api from "../../services/api";

const METRIC_LABELS = {
  terrain_flatness: { label: "Terrain Flatness", good: "high" },
  shading_risk: { label: "Shading Risk", good: "low" },
  access_routes: { label: "Access Routes", good: "high" },
  flood_indicators: { label: "Flood Indicators", good: "low" },
  vegetation_density: { label: "Vegetation Density", good: "low" },
  existing_infrastructure: { label: "Infrastructure", good: "low" },
};

function ScoreGauge({ score, verdict, confidence }) {
  if (score == null) return null;
  const color = verdict === "GO" ? "#4caf50" : verdict === "CAUTION" ? "#ff9800" : "#f44336";
  return (
    <div style={{ marginBottom: 12 }}>
      <div className="card-label">Suitability Score</div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 4 }}>
        <div style={{ flex: 1, height: 10, borderRadius: 5, background: "#F7F8FA", overflow: "hidden" }}>
          <div style={{ width: `${score}%`, height: "100%", background: color, borderRadius: 5, transition: "width 0.5s ease" }} />
        </div>
        <span style={{ color, fontWeight: "bold", fontSize: 16, minWidth: 36, textAlign: "right" }}>{score}</span>
        <span style={{ padding: "2px 8px", borderRadius: 8, background: color, color: "#fff", fontSize: 11, fontWeight: "bold" }}>
          {verdict}
        </span>
      </div>
      {confidence != null && (
        <div style={{ fontSize: 11, color: "#888", marginTop: 2 }}>
          Confidence: {(confidence * 100).toFixed(0)}%
        </div>
      )}
    </div>
  );
}

function FindingsGrid({ findings }) {
  if (!findings) return null;
  const metrics = Object.entries(METRIC_LABELS);
  return (
    <div style={{ marginBottom: 12 }}>
      <div className="card-label">Findings</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 12px" }}>
        {metrics.map(([key, { label, good }]) => {
          const val = findings[key];
          if (val == null) return null;
          const isGood = good === "high" ? val >= 60 : val < 40;
          const color = isGood ? "#4caf50" : val > 70 || val < 30 ? "#f44336" : "#ff9800";
          return (
            <div key={key} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
              <div style={{ flex: 1 }}>
                <div style={{ color: "#aaa", marginBottom: 2 }}>{label}</div>
                <div style={{ height: 5, borderRadius: 3, background: "#F7F8FA", overflow: "hidden" }}>
                  <div style={{ width: `${val}%`, height: "100%", background: color, borderRadius: 3 }} />
                </div>
              </div>
              <span style={{ fontWeight: "bold", color, minWidth: 24, textAlign: "right" }}>{val}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function UsableArea({ pct }) {
  if (pct == null) return null;
  return (
    <div style={{ marginBottom: 12 }}>
      <div className="card-label">Usable Area</div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <svg width="48" height="48" viewBox="0 0 48 48">
          <circle cx="24" cy="24" r="20" fill="none" stroke="#333" strokeWidth="4" />
          <circle cx="24" cy="24" r="20" fill="none" stroke="#4caf50" strokeWidth="4"
            strokeDasharray={`${pct * 1.257} ${125.7 - pct * 1.257}`}
            strokeDashoffset="31.4" strokeLinecap="round" />
          <text x="24" y="28" textAnchor="middle" fill="#f4f4f4" fontSize="12" fontWeight="bold">{pct}%</text>
        </svg>
        <span style={{ fontSize: 12 }}>of site area deemed usable for development</span>
      </div>
    </div>
  );
}

function DomainBadges({ contributions }) {
  if (!contributions) return null;
  const entries = Object.entries(contributions);
  if (!entries.length) return null;
  return (
    <div style={{ marginBottom: 12 }}>
      <div className="card-label">Domain Contributions</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {entries.map(([domain, data]) => {
          const adj = data?.adjustment || 0;
          const color = adj > 0 ? "#4caf50" : adj < 0 ? "#f44336" : "#888";
          return (
            <span key={domain} style={{
              padding: "3px 8px", borderRadius: 4, fontSize: 11,
              background: "rgba(255,255,255,0.05)", border: `1px solid ${color}40`,
            }}>
              <span style={{ color, fontWeight: "bold" }}>{adj > 0 ? "+" : ""}{adj}</span>
              {" "}{domain}
            </span>
          );
        })}
      </div>
    </div>
  );
}

const DEEP_DEFAULT_MODES = ["building_footprints", "land_cover", "canopy_height", "infrastructure_detect"];

export default function VisionCard() {
  const {
    pickedLocation, parcelId, setChatLayers,
    visionData, setVisionData,
    visionLoading, setVisionLoading,
  } = useSite();

  const [activeTab, setActiveTab] = useState("instant");
  const [deepJobId, setDeepJobId] = useState(null);
  const [deepResults, setDeepResults] = useState(null);
  const [deepLoading, setDeepLoading] = useState(false);
  const pollRef = useRef(null);

  // Poll for deep analysis job
  useEffect(() => {
    if (!deepJobId) return;
    const poll = setInterval(async () => {
      const status = await api.vision.jobStatus(deepJobId);
      if (!status) return;
      if (status.status === "done") {
        setDeepResults(status.result);
        setDeepLoading(false);
        setDeepJobId(null);
        clearInterval(poll);
        // Auto-inject detection layers
        if (parcelId) {
          const layerData = await api.vision.getLayers(parcelId);
          if (layerData?.layers?.length) {
            setChatLayers(prev => {
              const ids = new Set(prev.map(l => l.id));
              const newLayers = layerData.layers.filter(l => !ids.has(l.id));
              return [...prev, ...newLayers];
            });
          }
        }
      } else if (status.status === "failed") {
        setDeepLoading(false);
        setDeepJobId(null);
        clearInterval(poll);
      }
    }, 4000);
    pollRef.current = poll;
    return () => clearInterval(poll);
  }, [deepJobId, parcelId, setChatLayers]);

  const handleDeepAnalysis = async () => {
    if (!pickedLocation) return;
    setDeepLoading(true);
    setDeepResults(null);
    const res = await api.vision.deepAnalyse(
      null, pickedLocation.lat, pickedLocation.lon, parcelId, DEEP_DEFAULT_MODES
    );
    if (res?.job_id) {
      setDeepJobId(res.job_id);
    } else {
      setDeepLoading(false);
    }
  };

  const handleUploadComplete = (result) => {
    if (result) {
      setVisionData(result);
      setActiveTab("instant");
    }
  };

  const findings = visionData?.findings;
  const headerVal = visionData?.suitability_score != null ? `${visionData.suitability_score}/100` : null;

  return (
    <MetricCard
      title="Vision AI"
      accentColor="#7c4dff"
      headerValue={headerVal}
      aiInsight={visionData?.summary?.slice(0, 100)}
    >
      {/* Tab bar */}
      <div style={{ display: "flex", gap: 2, marginBottom: 10 }}>
        {["instant", "deep", "upload"].map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              flex: 1, padding: "5px 8px", fontSize: 11, fontWeight: 700,
              textTransform: "uppercase", letterSpacing: 0.5,
              border: "1px solid " + (activeTab === tab ? "#7c4dff" : "#393939"),
              borderRadius: 2,
              background: activeTab === tab ? "rgba(124,77,255,0.15)" : "transparent",
              color: activeTab === tab ? "#7c4dff" : "#888",
              cursor: "pointer", fontFamily: "inherit",
            }}
          >
            {tab === "upload" ? "Upload" : tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* Instant tab */}
      {activeTab === "instant" && (
        <>
          {visionLoading && (
            <div style={{ textAlign: "center", padding: "16px 0", color: "#7c4dff" }}>
              <div className="spinner" /> Analysing satellite imagery...
            </div>
          )}
          {!visionData && !visionLoading && (
            <div className="muted" style={{ textAlign: "center", padding: 12, fontSize: 12 }}>
              Vision analysis will auto-run when a site is selected, or upload an image manually.
            </div>
          )}
          {visionData && (
            <>
              <ScoreGauge
                score={visionData.suitability_score}
                verdict={visionData.verdict}
                confidence={visionData.confidence}
              />
              <FindingsGrid findings={findings} />
              <UsableArea pct={findings?.usable_area_pct} />
              <DomainBadges contributions={visionData.domain_contributions} />
              {findings?.exclusion_zones?.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <div className="card-label">Exclusion Zones</div>
                  {findings.exclusion_zones.map((ez, i) => (
                    <div key={i} style={{ fontSize: 11, color: "#f44336", marginBottom: 2 }}>
                      {ez.type}: {ez.reason}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </>
      )}

      {/* Deep tab */}
      {activeTab === "deep" && (
        <>
          {!deepResults && !deepLoading && (
            <div style={{ textAlign: "center", padding: "12px 0" }}>
              <button className="btn-primary" onClick={handleDeepAnalysis} disabled={!pickedLocation}
                style={{ fontSize: 12 }}>
                Run Deep Analysis
              </button>
              <div className="muted" style={{ marginTop: 6, fontSize: 11 }}>
                GeoAI: building footprints, land cover, canopy height, infrastructure detection (3-10 min)
              </div>
            </div>
          )}
          {deepLoading && (
            <div style={{ textAlign: "center", padding: "16px 0", color: "#7c4dff" }}>
              <div className="spinner" /> Deep analysis in progress...
            </div>
          )}
          {deepResults && (
            <>
              <div style={{ fontSize: 12, marginBottom: 8 }}>
                <strong>Score:</strong> {deepResults.aggregated?.suitability_score}/100
                {" — "}
                <span style={{
                  color: deepResults.aggregated?.verdict === "GO" ? "#4caf50"
                    : deepResults.aggregated?.verdict === "CAUTION" ? "#ff9800" : "#f44336",
                  fontWeight: "bold",
                }}>
                  {deepResults.aggregated?.verdict}
                </span>
              </div>
              {deepResults.aggregated?.notes?.map((note, i) => (
                <div key={i} style={{ fontSize: 11, color: "#c6c6c6", marginBottom: 2 }}>
                  - {note}
                </div>
              ))}
              <div style={{ marginTop: 8, fontSize: 11, color: "#888" }}>
                Modes: {deepResults.aggregated?.modes_completed?.join(", ")}
              </div>
              <button className="btn-primary" onClick={handleDeepAnalysis} disabled={deepLoading}
                style={{ marginTop: 10, fontSize: 11, opacity: 0.7 }}>
                Re-run Deep Analysis
              </button>
            </>
          )}
        </>
      )}

      {/* Upload tab */}
      {activeTab === "upload" && (
        <ImageUploader
          onAnalysisComplete={handleUploadComplete}
          lat={pickedLocation?.lat}
          lon={pickedLocation?.lon}
          parcelId={parcelId}
        />
      )}
    </MetricCard>
  );
}
