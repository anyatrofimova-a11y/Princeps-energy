import React, { useEffect, useRef, useState, useCallback } from "react";
import mapboxgl from "mapbox-gl";
import api from "../services/api";

/**
 * PortfolioMapOverlay — renders all pipeline projects as color-coded pins on the map.
 * This is the "portfolio-first home screen" pattern from PVcase/Pivvot.
 *
 * Pin colors by stage:
 *   prospect=#8A857D  screened=#D4A018  grid_applied=#0891b2
 *   grid_offer=#3b82f6  planning=#a855f7  fid=#16a34a
 *   construction=#f59e0b  energised=#22c55e
 */

const STAGE_COLORS = {
  prospect: "#8A857D",
  screened: "#D4A018",
  grid_applied: "#0891b2",
  grid_offer: "#3b82f6",
  planning: "#a855f7",
  fid: "#16a34a",
  construction: "#f59e0b",
  energised: "#22c55e",
};

const TECH_ICONS = {
  solar: "PV",
  wind: "WD",
  bess: "BS",
  dc: "DC",
  hybrid: "\u26A1",
};

export default function PortfolioMapOverlay({ map, onSelectProject, visible = true }) {
  const markersRef = useRef({});
  const [projects, setProjects] = useState([]);
  const loadedRef = useRef(false);

  // Load projects once
  useEffect(() => {
    if (loadedRef.current || !visible) return;
    loadedRef.current = true;
    api.projects.list({ limit: 500 }).then(res => {
      if (res?.projects) setProjects(res.projects);
    });
  }, [visible]);

  // Create/update markers
  useEffect(() => {
    if (!map || !visible || !map.isStyleLoaded?.()) return;

    const currentIds = new Set(projects.map(p => p.project_id));

    // Remove old markers
    for (const [id, marker] of Object.entries(markersRef.current)) {
      if (!currentIds.has(id)) {
        marker.remove();
        delete markersRef.current[id];
      }
    }

    // Add/update markers
    for (const project of projects) {
      if (!project.lat || !project.lon) continue;
      if (markersRef.current[project.project_id]) continue;

      const color = STAGE_COLORS[project.stage] || "#8A857D";
      const icon = TECH_ICONS[project.technology] || "\u2B22";

      const el = document.createElement("div");
      el.className = "portfolio-pin";
      el.style.cssText = `
        width: 32px; height: 32px; border-radius: 50%;
        background: ${color}; border: 2px solid white;
        display: flex; align-items: center; justify-content: center;
        font-size: 14px; cursor: pointer;
        box-shadow: 0 2px 8px rgba(0,0,0,0.25);
        transition: transform 0.15s, box-shadow 0.15s;
      `;
      el.innerHTML = `<span style="pointer-events:none">${icon}</span>`;

      // MW badge
      if (project.capacity_mw) {
        const badge = document.createElement("div");
        badge.style.cssText = `
          position: absolute; bottom: -6px; left: 50%; transform: translateX(-50%);
          background: #0F0E0A; color: white; font-size: 7px; font-weight: 700;
          padding: 1px 4px; border-radius: 4px; white-space: nowrap;
          font-family: Roboto, sans-serif;
        `;
        badge.textContent = `${Math.round(project.capacity_mw)}MW`;
        el.appendChild(badge);
      }

      // Hover
      el.addEventListener("mouseenter", () => {
        el.style.transform = "scale(1.2)";
        el.style.boxShadow = `0 4px 16px ${color}66`;
        el.style.zIndex = "10";
      });
      el.addEventListener("mouseleave", () => {
        el.style.transform = "scale(1)";
        el.style.boxShadow = "0 2px 8px rgba(0,0,0,0.25)";
        el.style.zIndex = "";
      });

      const marker = new mapboxgl.Marker({ element: el, anchor: "center" })
        .setLngLat([project.lon, project.lat])
        .addTo(map);

      el.addEventListener("click", () => onSelectProject?.(project));

      markersRef.current[project.project_id] = marker;
    }

    return () => {};
  }, [map, projects, visible, onSelectProject]);

  // ── Hide pipeline-stage markers below zoom 11 ──────────────────────
  // 500+ HTML markers blanket the country at low zoom. Below z11 we
  // hide them entirely; above z11 individual sites are visible. A
  // proper Mapbox cluster source would be the next step.
  useEffect(() => {
    if (!map) return;
    const updateVisibility = () => {
      const z = map.getZoom();
      const display = z < 11 ? "none" : "";
      Object.values(markersRef.current).forEach((m) => {
        const el = m.getElement?.();
        if (el && el.style.display !== display) el.style.display = display;
      });
    };
    updateVisibility();
    map.on("zoomend", updateVisibility);
    return () => { map.off("zoomend", updateVisibility); };
  }, [map, projects]);

  // Cleanup
  useEffect(() => {
    return () => {
      Object.values(markersRef.current).forEach(m => m.remove());
      markersRef.current = {};
    };
  }, []);

  if (!visible || projects.length === 0) return null;

  // Legend strip
  return (
    <div className="portfolio-legend">
      <span className="portfolio-legend-title">PIPELINE</span>
      {Object.entries(STAGE_COLORS).map(([stage, color]) => {
        const count = projects.filter(p => p.stage === stage).length;
        if (count === 0) return null;
        return (
          <div key={stage} className="portfolio-legend-item">
            <span className="portfolio-legend-dot" style={{ background: color }} />
            <span className="portfolio-legend-label">{stage.replace("_", " ")}</span>
            <span className="portfolio-legend-count">{count}</span>
          </div>
        );
      })}
      <span className="portfolio-legend-total">{projects.length} sites</span>
    </div>
  );
}
