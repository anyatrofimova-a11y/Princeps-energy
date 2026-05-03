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
  { id: "team", label: "Team" },
];

const ROLES = [
  { id: "owner", label: "Owner", desc: "Full admin, billing, delete workspace" },
  { id: "admin", label: "Admin", desc: "Manage members, settings, projects" },
  { id: "editor", label: "Editor", desc: "Edit projects, run analyses" },
  { id: "viewer", label: "Viewer", desc: "Read-only access" },
];

// Soft validation — only flag fields that are present BUT invalid.
// Blank fields are not errors, so a first-run user never sees a locked
// Save button. The (optional) asterisk next to required fields is a hint,
// not a hard block — saved form can be partially filled and is merged
// with whatever is already in localStorage.
function validate(form) {
  const errors = {};
  if (form.mapboxToken && form.mapboxToken.trim() && !/^(pk|sk)\./.test(form.mapboxToken.trim())) {
    errors.mapboxToken = "Mapbox tokens start with 'pk.' or 'sk.'";
  }
  if (form.backendUrl && form.backendUrl.trim()) {
    try { new URL(form.backendUrl); } catch {
      errors.backendUrl = "Must be a valid URL";
    }
  }
  if (form.displayName && form.displayName.trim() && form.displayName.trim().length < 2) {
    errors.displayName = "Min 2 characters";
  }
  if (form.email && form.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
    errors.email = "Must be a valid email";
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
    team: false,
  }), [errors]);

  const teamMembers = settingsForm.teamMembers || [];
  const teamMode = settingsForm.teamMode !== false;
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("editor");
  const addMember = useCallback(() => {
    const e = (inviteEmail || "").trim();
    if (!e || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e)) {
      setToast("Enter a valid email to invite");
      setTimeout(() => setToast(null), 2500);
      return;
    }
    if (teamMembers.some(m => m.email === e)) {
      setToast("Member already on team");
      setTimeout(() => setToast(null), 2000);
      return;
    }
    const next = [...teamMembers, {
      email: e, role: inviteRole, status: "invited",
      invited_at: new Date().toISOString(),
    }];
    updateSettingsForm({ teamMembers: next });
    setInviteEmail("");
    setToast(`Invite queued for ${e}`);
    setTimeout(() => setToast(null), 2000);
  }, [inviteEmail, inviteRole, teamMembers, updateSettingsForm]);
  const removeMember = useCallback((email) => {
    updateSettingsForm({ teamMembers: teamMembers.filter(m => m.email !== email) });
  }, [teamMembers, updateSettingsForm]);
  const changeRole = useCallback((email, role) => {
    updateSettingsForm({
      teamMembers: teamMembers.map(m => m.email === email ? { ...m, role } : m),
    });
  }, [teamMembers, updateSettingsForm]);

  const handleSave = useCallback(() => {
    if (hasErrors) {
      setToast("Fix highlighted fields before saving");
      setTimeout(() => setToast(null), 2500);
      return;
    }
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
          <button
            className="settings-save-btn"
            onClick={handleSave}
            title={hasErrors ? "Fix validation errors above" : "Save settings"}
          >Save</button>
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
                  <option value="light">Light</option>
                  <option value="system">Match system</option>
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

          {activeSection === "team" && (
            <>
              <div className="settings-field">
                <span className="settings-label">Team mode</span>
                <div className="settings-toggle-group">
                  <button
                    className={`settings-toggle-btn${teamMode ? " active" : ""}`}
                    onClick={() => updateSettingsForm({ teamMode: true })}
                  >On</button>
                  <button
                    className={`settings-toggle-btn${!teamMode ? " active" : ""}`}
                    onClick={() => updateSettingsForm({ teamMode: false })}
                  >Off (solo)</button>
                </div>
                <span style={{ fontSize: 11, color: "var(--cds-text-helper)", marginTop: 6, display: "block" }}>
                  When on, projects and comments are shared with invited members; chat threads show authorship.
                </span>
              </div>

              {teamMode && (
                <>
                  <div className="settings-field">
                    <span className="settings-label">Invite a teammate</span>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                      <input
                        type="email"
                        className="settings-input"
                        placeholder="teammate@example.com"
                        value={inviteEmail}
                        onChange={e => setInviteEmail(e.target.value)}
                        onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addMember(); } }}
                        style={{ flex: "1 1 220px", minWidth: 200 }}
                      />
                      <select
                        className="settings-select"
                        value={inviteRole}
                        onChange={e => setInviteRole(e.target.value)}
                        style={{ flex: "0 0 140px" }}
                      >
                        {ROLES.filter(r => r.id !== "owner").map(r => (
                          <option key={r.id} value={r.id}>{r.label}</option>
                        ))}
                      </select>
                      <button className="settings-save-btn" onClick={addMember}>Invite</button>
                    </div>
                    <span style={{ fontSize: 11, color: "var(--cds-text-helper)", marginTop: 6, display: "block" }}>
                      {ROLES.find(r => r.id === inviteRole)?.desc}
                    </span>
                  </div>

                  <div className="settings-field">
                    <span className="settings-label">Members ({teamMembers.length + 1})</span>
                    <div style={{
                      border: "1px solid var(--cds-border-subtle, #e5e7eb)",
                      borderRadius: 8,
                      overflow: "hidden",
                    }}>
                      <div style={{
                        display: "grid",
                        gridTemplateColumns: "1fr 140px 110px 40px",
                        gap: 0,
                        padding: "10px 12px",
                        background: "var(--cds-layer-02, #f7f7f8)",
                        fontSize: 11,
                        fontWeight: 600,
                        color: "var(--cds-text-helper)",
                        textTransform: "uppercase",
                        letterSpacing: "0.04em",
                      }}>
                        <span>Member</span><span>Role</span><span>Status</span><span/>
                      </div>
                      <div style={{
                        display: "grid",
                        gridTemplateColumns: "1fr 140px 110px 40px",
                        padding: "12px",
                        alignItems: "center",
                        borderTop: "1px solid var(--cds-border-subtle, #e5e7eb)",
                        fontSize: 13,
                      }}>
                        <span>
                          <strong>{settingsForm.displayName || settingsForm.email || "You"}</strong>
                          <span style={{ color: "var(--cds-text-helper)", marginLeft: 6 }}>(you)</span>
                        </span>
                        <span style={{ fontWeight: 600 }}>Owner</span>
                        <span style={{ color: "#16a34a" }}>Active</span>
                        <span/>
                      </div>
                      {teamMembers.length === 0 ? (
                        <div style={{
                          padding: "14px 12px",
                          color: "var(--cds-text-helper)",
                          fontSize: 12,
                          borderTop: "1px solid var(--cds-border-subtle, #e5e7eb)",
                          textAlign: "center",
                        }}>
                          No teammates yet. Invite one above.
                        </div>
                      ) : teamMembers.map(m => (
                        <div key={m.email} style={{
                          display: "grid",
                          gridTemplateColumns: "1fr 140px 110px 40px",
                          padding: "12px",
                          alignItems: "center",
                          borderTop: "1px solid var(--cds-border-subtle, #e5e7eb)",
                          fontSize: 13,
                        }}>
                          <span>{m.email}</span>
                          <select
                            className="settings-select"
                            value={m.role}
                            onChange={e => changeRole(m.email, e.target.value)}
                            style={{ padding: "4px 8px", fontSize: 12 }}
                          >
                            {ROLES.filter(r => r.id !== "owner").map(r => (
                              <option key={r.id} value={r.id}>{r.label}</option>
                            ))}
                          </select>
                          <span style={{
                            color: m.status === "active" ? "#16a34a" : "#d97706",
                            fontSize: 12,
                          }}>{m.status === "active" ? "Active" : "Invited"}</span>
                          <button
                            onClick={() => removeMember(m.email)}
                            title="Remove"
                            style={{
                              background: "transparent",
                              border: "none",
                              color: "var(--cds-text-helper)",
                              cursor: "pointer",
                              fontSize: 16,
                              padding: 4,
                            }}
                          >×</button>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="settings-field">
                    <span className="settings-label">Workspace</span>
                    <input
                      type="text"
                      className="settings-input"
                      placeholder="Princeps workspace"
                      value={settingsForm.workspaceName || ""}
                      onChange={e => updateSettingsForm({ workspaceName: e.target.value })}
                    />
                  </div>
                </>
              )}
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
