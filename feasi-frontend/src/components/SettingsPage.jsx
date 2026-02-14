import React, { useState, useMemo, useCallback } from "react";
import { useSite } from "../SiteContext";

const LAYER_OPTIONS = [
  { id: "hillshade", label: "Hillshade" },
  { id: "slope", label: "Slope" },
  { id: "contours", label: "Contours" },
  { id: "carbon", label: "Carbon" },
  { id: "la", label: "Local Auth" },
  { id: "transport", label: "Transport" },
  { id: "environment", label: "Energy Assets" },
  { id: "gridFlow", label: "Grid Flow" },
  { id: "aerial", label: "Aerial" },
  { id: "ndvi", label: "NDVI" },
  { id: "satellite", label: "Sentinel-2" },
];

const SECTIONS = [
  { id: "map", label: "Map & Display" },
  { id: "api", label: "API & Connections" },
  { id: "profile", label: "Profile & Notifications" },
];

function validate(form) {
  const errors = {};
  if (!form.mapboxToken || !form.mapboxToken.trim()) {
    errors.mapboxToken = "Mapbox token is required";
  }
  if (form.backendUrl && form.backendUrl.trim()) {
    try { new URL(form.backendUrl); } catch {
      errors.backendUrl = "Must be a valid URL";
    }
  }
  if (!form.displayName || form.displayName.trim().length < 2) {
    errors.displayName = "Min 2 characters";
  }
  if (!form.email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
    errors.email = "Valid email required";
  }
  return errors;
}

export default function SettingsPage({ onExit }) {
  const { settingsForm, updateSettingsForm, saveSettings, resetSettingsForm } = useSite();
  const [activeSection, setActiveSection] = useState("map");
  const [toast, setToast] = useState(null);

  const errors = useMemo(() => validate(settingsForm), [settingsForm]);
  const hasErrors = Object.keys(errors).length > 0;

  const sectionErrors = useMemo(() => ({
    map: false,
    api: !!(errors.mapboxToken || errors.backendUrl),
    profile: !!(errors.displayName || errors.email),
  }), [errors]);

  const handleSave = useCallback(() => {
    if (hasErrors) return;
    saveSettings(settingsForm);
    setToast("Settings saved");
    setTimeout(() => setToast(null), 2000);
  }, [hasErrors, settingsForm, saveSettings]);

  const handleReset = useCallback(() => {
    resetSettingsForm();
  }, [resetSettingsForm]);

  const handleLayerToggle = useCallback((layerId) => {
    const current = settingsForm.defaultLayers || [];
    const next = current.includes(layerId)
      ? current.filter(id => id !== layerId)
      : [...current, layerId];
    updateSettingsForm({ defaultLayers: next });
  }, [settingsForm.defaultLayers, updateSettingsForm]);

  return (
    <div className="settings-page">
      {/* Header */}
      <div className="settings-header">
        <button className="settings-back-btn" onClick={onExit}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
          Back
        </button>
        <span className="settings-title">Settings</span>
        <div className="settings-actions">
          <button className="settings-reset-btn" onClick={handleReset}>Reset</button>
          <button className="settings-save-btn" onClick={handleSave} disabled={hasErrors}>Save</button>
        </div>
      </div>

      {/* Section Tabs */}
      <div className="settings-tabs">
        {SECTIONS.map(s => (
          <button
            key={s.id}
            className={`settings-section-tab${activeSection === s.id ? " active" : ""}${sectionErrors[s.id] ? " has-error" : ""}`}
            onClick={() => setActiveSection(s.id)}
          >
            {s.label}
            {sectionErrors[s.id] && <span className="settings-error-dot" />}
          </button>
        ))}
      </div>

      {/* Form Body */}
      <div className="settings-body">
        <div className="settings-form">

          {activeSection === "map" && (
            <>
              <label className="settings-field">
                <span className="settings-label">Default Map Style</span>
                <select
                  className="settings-select"
                  value={settingsForm.mapStyle}
                  onChange={e => updateSettingsForm({ mapStyle: e.target.value })}
                >
                  <option value="dark">Dark</option>
                  <option value="satellite">Satellite</option>
                  <option value="streets">Streets</option>
                </select>
              </label>

              <label className="settings-field">
                <span className="settings-label">Default Slope Opacity</span>
                <div className="settings-range-row">
                  <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.05"
                    value={settingsForm.defaultSlopeOpacity}
                    onChange={e => updateSettingsForm({ defaultSlopeOpacity: parseFloat(e.target.value) })}
                    className="settings-range"
                  />
                  <span className="settings-range-val">{(settingsForm.defaultSlopeOpacity * 100).toFixed(0)}%</span>
                </div>
              </label>

              <div className="settings-field">
                <span className="settings-label">Default Active Layers</span>
                <div className="settings-checkbox-grid">
                  {LAYER_OPTIONS.map(l => (
                    <label key={l.id} className="settings-checkbox-item">
                      <input
                        type="checkbox"
                        checked={(settingsForm.defaultLayers || []).includes(l.id)}
                        onChange={() => handleLayerToggle(l.id)}
                      />
                      {l.label}
                    </label>
                  ))}
                </div>
              </div>

              <label className="settings-field">
                <span className="settings-label">Theme</span>
                <select className="settings-select" value={settingsForm.theme} onChange={e => updateSettingsForm({ theme: e.target.value })}>
                  <option value="dark">Dark</option>
                  <option value="light" disabled>Light (Coming Soon)</option>
                </select>
              </label>
            </>
          )}

          {activeSection === "api" && (
            <>
              <label className="settings-field">
                <span className="settings-label">Mapbox Token <span className="settings-required">*</span></span>
                <input
                  type="text"
                  className={`settings-input${errors.mapboxToken ? " error" : ""}`}
                  value={settingsForm.mapboxToken}
                  onChange={e => updateSettingsForm({ mapboxToken: e.target.value })}
                  placeholder="pk.eyJ1..."
                />
                {errors.mapboxToken && <span className="settings-error-msg">{errors.mapboxToken}</span>}
              </label>

              <label className="settings-field">
                <span className="settings-label">GEE Project ID</span>
                <input
                  type="text"
                  className="settings-input"
                  value={settingsForm.geeProjectId}
                  onChange={e => updateSettingsForm({ geeProjectId: e.target.value })}
                  placeholder="my-gee-project"
                />
              </label>

              <label className="settings-field">
                <span className="settings-label">Backend URL</span>
                <input
                  type="text"
                  className={`settings-input${errors.backendUrl ? " error" : ""}`}
                  value={settingsForm.backendUrl}
                  onChange={e => updateSettingsForm({ backendUrl: e.target.value })}
                  placeholder="http://localhost:8000"
                />
                {errors.backendUrl && <span className="settings-error-msg">{errors.backendUrl}</span>}
              </label>
            </>
          )}

          {activeSection === "profile" && (
            <>
              <label className="settings-field">
                <span className="settings-label">Display Name <span className="settings-required">*</span></span>
                <input
                  type="text"
                  className={`settings-input${errors.displayName ? " error" : ""}`}
                  value={settingsForm.displayName}
                  onChange={e => updateSettingsForm({ displayName: e.target.value })}
                  placeholder="Your name"
                />
                {errors.displayName && <span className="settings-error-msg">{errors.displayName}</span>}
              </label>

              <label className="settings-field">
                <span className="settings-label">Email <span className="settings-required">*</span></span>
                <input
                  type="text"
                  className={`settings-input${errors.email ? " error" : ""}`}
                  value={settingsForm.email}
                  onChange={e => updateSettingsForm({ email: e.target.value })}
                  placeholder="user@example.com"
                />
                {errors.email && <span className="settings-error-msg">{errors.email}</span>}
              </label>

              <label className="settings-field">
                <span className="settings-label">Export Format</span>
                <select
                  className="settings-select"
                  value={settingsForm.exportFormat}
                  onChange={e => updateSettingsForm({ exportFormat: e.target.value })}
                >
                  <option value="csv">CSV</option>
                  <option value="json">JSON</option>
                  <option value="geojson">GeoJSON</option>
                </select>
              </label>

              <div className="settings-field">
                <span className="settings-label">Notifications</span>
                <div className="settings-toggle-group">
                  <button
                    className={`settings-toggle-btn${settingsForm.notifications ? " active" : ""}`}
                    onClick={() => updateSettingsForm({ notifications: true })}
                  >
                    On
                  </button>
                  <button
                    className={`settings-toggle-btn${!settingsForm.notifications ? " active" : ""}`}
                    onClick={() => updateSettingsForm({ notifications: false })}
                  >
                    Off
                  </button>
                </div>
              </div>
            </>
          )}

        </div>
      </div>

      {/* Toast */}
      {toast && <div className="settings-toast">{toast}</div>}
    </div>
  );
}
