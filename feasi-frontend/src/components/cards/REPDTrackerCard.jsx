import React, { useState, useEffect, useCallback } from "react";
import { useSite } from "../../SiteContext";
import api from "../../services/api";

const ACCENT = "#ffc107";
const TECH_PILLS = ["all", "solar", "bess", "wind", "biomass"];

function statusColor(status) {
  const map = {
    Operational: "#4caf50",
    "Under Construction": "#ff9800",
    "Awaiting Construction": "#2196f3",
    Approved: "#8bc34a",
    Submitted: "#9c27b0",
    Refused: "#f44336",
    Appeal: "#e91e63",
  };
  return map[status] || "#607d8b";
}

export default function REPDTrackerCard() {
  const { pickedLocation } = useSite();
  const [summary, setSummary] = useState(null);
  const [projects, setProjects] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tech, setTech] = useState("all");
  const [view, setView] = useState("summary");

  const lat = pickedLocation?.lat;
  const lon = pickedLocation?.lon;

  const loadSummary = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.tracker.repdSummary();
      setSummary(data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  const loadProjects = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (tech !== "all") params.tech_category = tech;
      if (lat != null) { params.lat = lat; params.lon = lon; params.radius_km = 25; }
      const data = await api.tracker.repd(params);
      setProjects(data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [tech, lat, lon]);

  useEffect(() => {
    if (view === "summary" && !summary) loadSummary();
    if (view === "projects") loadProjects();
  }, [view, summary, tech, loadSummary, loadProjects]);

  return (
    <div className="card" style={{ borderLeft: `3px solid ${ACCENT}` }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0, color: ACCENT, flex: 1 }}>REPD Tracker</h3>
        <button
          className={`tab-btn-sm ${view === "summary" ? "active" : ""}`}
          style={view === "summary" ? { background: ACCENT, color: "#000" } : { color: ACCENT }}
          onClick={() => setView("summary")}
        >Summary</button>
        <button
          className={`tab-btn-sm ${view === "projects" ? "active" : ""}`}
          style={view === "projects" ? { background: ACCENT, color: "#000" } : { color: ACCENT }}
          onClick={() => setView("projects")}
        >Projects</button>
      </div>

      {loading && <div className="spinner-sm" />}

      {view === "summary" && summary && (
        <div>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 8 }}>
            <div><strong>{summary.total_projects?.toLocaleString()}</strong> projects</div>
            <div><strong>{summary.total_mw?.toLocaleString()} MW</strong> total</div>
          </div>
          {summary.by_technology?.map((t) => (
            <div key={t.tech_category} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "2px 0" }}>
              <span style={{ textTransform: "capitalize" }}>{t.tech_category || "other"}</span>
              <span>{t.cnt} ({Number(t.total_mw).toLocaleString()} MW)</span>
            </div>
          ))}
        </div>
      )}

      {view === "projects" && (
        <>
          <div style={{ display: "flex", gap: 4, marginBottom: 8, flexWrap: "wrap" }}>
            {TECH_PILLS.map((t) => (
              <button
                key={t}
                className="tab-btn-sm"
                style={tech === t ? { background: ACCENT, color: "#000" } : { color: ACCENT }}
                onClick={() => setTech(t)}
              >{t}</button>
            ))}
          </div>
          {projects?.projects?.length > 0 ? (
            <div style={{ maxHeight: 300, overflowY: "auto" }}>
              {projects.projects.map((p) => (
                <div key={p.repd_id} style={{ borderBottom: "1px solid #333", padding: "6px 0", fontSize: 13 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <strong>{p.site_name || "Unnamed"}</strong>
                    <span style={{ color: statusColor(p.status), fontWeight: 600 }}>{p.status}</span>
                  </div>
                  <div style={{ color: "#999" }}>
                    {p.capacity_mw ? `${p.capacity_mw} MW` : ""} {p.technology || ""} — {p.developer || ""}
                  </div>
                </div>
              ))}
            </div>
          ) : !loading && (
            <div style={{ color: "#666", fontSize: 13 }}>No projects found</div>
          )}
        </>
      )}
    </div>
  );
}
