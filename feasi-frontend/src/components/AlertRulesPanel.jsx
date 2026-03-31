import React, { useState, useCallback } from "react";
import api from "../services/api";

const TRIGGERS = [
  { id: "price_threshold", label: "Price Threshold", unit: "GBP/MWh" },
  { id: "capacity_change", label: "Capacity Change", unit: "MW" },
  { id: "planning_decision", label: "Planning Decision", unit: "" },
  { id: "grid_outage", label: "Grid Outage", unit: "" },
  { id: "frequency_deviation", label: "Frequency Deviation", unit: "Hz" },
  { id: "curtailment_event", label: "Curtailment Event", unit: "%" },
];

const CONDITIONS = [
  { id: "above", label: "Above" },
  { id: "below", label: "Below" },
  { id: "equals", label: "Equals" },
  { id: "changes", label: "Any Change" },
];

const FREQUENCIES = [
  { id: "once", label: "Once" },
  { id: "hourly", label: "Hourly" },
  { id: "daily", label: "Daily" },
];

function fmtTime(d) {
  try { return new Date(d).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); }
  catch { return d; }
}

export default function AlertRulesPanel({ onClose, embedded }) {
  const [rules, setRules] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [form, setForm] = useState({ trigger: "price_threshold", condition: "above", value: "", frequency: "once", action: "in_app" });
  const [testing, setTesting] = useState(null);

  const updateForm = useCallback((field, val) => {
    setForm(prev => ({ ...prev, [field]: val }));
  }, []);

  const createRule = useCallback(async () => {
    if (!form.trigger) return;
    const rule = {
      id: `rule-${Date.now()}`,
      ...form,
      value: form.value ? parseFloat(form.value) : null,
      enabled: true,
      created: new Date().toISOString(),
    };
    try {
      await api.alerts.createRule(rule);
    } catch (e) {
      console.warn("[Alerts] Create failed:", e);
    }
    setRules(prev => [rule, ...prev]);
    setForm({ trigger: "price_threshold", condition: "above", value: "", frequency: "once", action: "in_app" });
  }, [form]);

  const toggleRule = useCallback((ruleId) => {
    setRules(prev => prev.map(r =>
      r.id === ruleId ? { ...r, enabled: !r.enabled } : r
    ));
  }, []);

  const deleteRule = useCallback((ruleId) => {
    setRules(prev => prev.filter(r => r.id !== ruleId));
  }, []);

  const testRule = useCallback(async (rule) => {
    setTesting(rule.id);
    try {
      await api.alerts.testRule(rule);
      setAlerts(prev => [{
        id: `alert-${Date.now()}`,
        rule_id: rule.id,
        trigger: rule.trigger,
        message: `Test alert: ${TRIGGERS.find(t => t.id === rule.trigger)?.label} ${rule.condition} ${rule.value || "triggered"}`,
        date: new Date().toISOString(),
        test: true,
      }, ...prev]);
    } catch (e) {
      console.warn("[Alerts] Test failed:", e);
    } finally {
      setTesting(null);
    }
  }, []);

  const triggerInfo = TRIGGERS.find(t => t.id === form.trigger);

  return (
    <div className="ar-panel">
      {!embedded && (
        <div className="ar-header">
          <span className="ar-title">Alert Rules</span>
          <button className="ar-close" onClick={onClose}>&times;</button>
        </div>
      )}

      <div className="ar-body">
        {/* Create rule form */}
        <div className="ar-section">
          <div className="ar-section-title">New Rule</div>
          <div className="ar-form">
            <div className="ar-field">
              <label className="ar-label">Trigger</label>
              <select className="ar-select" value={form.trigger} onChange={e => updateForm("trigger", e.target.value)}>
                {TRIGGERS.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
              </select>
            </div>

            <div className="ar-row">
              <div className="ar-field">
                <label className="ar-label">Condition</label>
                <select className="ar-select" value={form.condition} onChange={e => updateForm("condition", e.target.value)}>
                  {CONDITIONS.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
                </select>
              </div>
              {form.condition !== "changes" && (
                <div className="ar-field">
                  <label className="ar-label">Value {triggerInfo?.unit ? `(${triggerInfo.unit})` : ""}</label>
                  <input className="ar-input" type="number" value={form.value}
                    onChange={e => updateForm("value", e.target.value)}
                    placeholder={triggerInfo?.unit || "Value"} />
                </div>
              )}
            </div>

            <div className="ar-row">
              <div className="ar-field">
                <label className="ar-label">Frequency</label>
                <select className="ar-select" value={form.frequency} onChange={e => updateForm("frequency", e.target.value)}>
                  {FREQUENCIES.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}
                </select>
              </div>
              <div className="ar-field">
                <label className="ar-label">Action</label>
                <select className="ar-select" value={form.action} onChange={e => updateForm("action", e.target.value)}>
                  <option value="in_app">In-app Notification</option>
                  <option value="email">Email (placeholder)</option>
                </select>
              </div>
            </div>

            <button className="ar-btn-primary" onClick={createRule}>Create Rule</button>
          </div>
        </div>

        {/* Active rules */}
        {rules.length > 0 && (
          <div className="ar-section">
            <div className="ar-section-title">Active Rules ({rules.length})</div>
            {rules.map(r => {
              const trig = TRIGGERS.find(t => t.id === r.trigger);
              return (
                <div key={r.id} className={`ar-rule-card${r.enabled ? "" : " ar-disabled"}`}>
                  <div className="ar-rule-top">
                    <span className="ar-rule-name">{trig?.label || r.trigger}</span>
                    <label className="ar-toggle">
                      <input type="checkbox" checked={r.enabled} onChange={() => toggleRule(r.id)} />
                      <span className="ar-toggle-slider" />
                    </label>
                  </div>
                  <div className="ar-rule-desc">
                    {r.condition} {r.value != null ? r.value : ""} {trig?.unit || ""} / {r.frequency}
                  </div>
                  <div className="ar-rule-actions">
                    <button className="ar-btn-sm" onClick={() => testRule(r)} disabled={testing === r.id}>
                      {testing === r.id ? "Testing..." : "Test"}
                    </button>
                    <button className="ar-btn-sm ar-btn-danger" onClick={() => deleteRule(r.id)}>Delete</button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Recent alerts */}
        {alerts.length > 0 && (
          <div className="ar-section">
            <div className="ar-section-title">Recent Alerts</div>
            {alerts.slice(0, 10).map(a => (
              <div key={a.id} className={`ar-alert-item${a.test ? " ar-test" : ""}`}>
                <span className="ar-alert-msg">{a.message}</span>
                <span className="ar-alert-time">{fmtTime(a.date)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
