import React, { useState, useEffect, useCallback } from "react";
import api from "../../services/api";

const ACCENT = "#ff5722";

function severityIcon(severity) {
  const map = { info: "i", warning: "!", critical: "!!" };
  return map[severity] || "i";
}

function severityColor(severity) {
  const map = { info: "#2196f3", warning: "#ff9800", critical: "#f44336" };
  return map[severity] || "#607d8b";
}

function timeAgo(iso) {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function AlertsCard() {
  const [data, setData] = useState(null);
  const [rules, setRules] = useState(null);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState("notifications");

  const loadNotifications = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.notifications.list(false, 30);
      setData(res);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  const loadRules = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.notifications.rules();
      setRules(res);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  const markRead = useCallback(async (id) => {
    try {
      await api.notifications.markRead(id);
      loadNotifications();
    } catch (e) { console.error(e); }
  }, [loadNotifications]);

  const markAllRead = useCallback(async () => {
    try {
      await api.notifications.markAllRead();
      loadNotifications();
    } catch (e) { console.error(e); }
  }, [loadNotifications]);

  const checkNow = useCallback(async () => {
    setLoading(true);
    try {
      await api.notifications.checkNow();
      await loadNotifications();
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [loadNotifications]);

  useEffect(() => {
    if (view === "notifications" && !data) loadNotifications();
    if (view === "rules" && !rules) loadRules();
  }, [view, data, rules, loadNotifications, loadRules]);

  const unread = data?.unread || 0;

  return (
    <div className="card" style={{ borderLeft: `3px solid ${ACCENT}` }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <h3 style={{ margin: 0, color: ACCENT, flex: 1 }}>
          Alerts
          {unread > 0 && (
            <span style={{
              background: ACCENT, color: "#fff", borderRadius: 10,
              padding: "1px 6px", fontSize: 11, marginLeft: 6,
            }}>{unread}</span>
          )}
        </h3>
        <button
          className={`tab-btn-sm ${view === "notifications" ? "active" : ""}`}
          style={view === "notifications" ? { background: ACCENT, color: "#fff" } : { color: ACCENT }}
          onClick={() => setView("notifications")}
        >Alerts</button>
        <button
          className={`tab-btn-sm ${view === "rules" ? "active" : ""}`}
          style={view === "rules" ? { background: ACCENT, color: "#fff" } : { color: ACCENT }}
          onClick={() => setView("rules")}
        >Rules</button>
      </div>

      {loading && <div className="spinner-sm" />}

      {view === "notifications" && (
        <div>
          <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
            <button className="tab-btn-sm" style={{ color: ACCENT, fontSize: 11 }} onClick={markAllRead}>
              Mark all read
            </button>
            <button className="tab-btn-sm" style={{ color: ACCENT, fontSize: 11 }} onClick={checkNow}>
              Check now
            </button>
          </div>

          {data?.notifications?.length > 0 ? (
            <div style={{ maxHeight: 300, overflowY: "auto" }}>
              {data.notifications.map((n) => (
                <div
                  key={n.notification_id}
                  style={{
                    borderBottom: "1px solid #333", padding: "6px 0", fontSize: 13,
                    opacity: n.read ? 0.6 : 1,
                  }}
                >
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    <span style={{
                      width: 20, height: 20, borderRadius: 10,
                      background: severityColor(n.severity), color: "#fff",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 10, fontWeight: 700, flexShrink: 0,
                    }}>{severityIcon(n.severity)}</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 600 }}>{n.title}</div>
                      <div style={{ color: "#999", fontSize: 12 }}>{n.body}</div>
                    </div>
                    <div style={{ fontSize: 11, color: "#666", whiteSpace: "nowrap" }}>
                      {timeAgo(n.created_at)}
                    </div>
                  </div>
                  {!n.read && (
                    <button
                      style={{ fontSize: 11, color: ACCENT, background: "none", border: "none", cursor: "pointer", padding: 0, marginTop: 2 }}
                      onClick={() => markRead(n.notification_id)}
                    >Mark read</button>
                  )}
                </div>
              ))}
            </div>
          ) : !loading && (
            <div style={{ color: "#666", fontSize: 13 }}>No notifications yet</div>
          )}
        </div>
      )}

      {view === "rules" && (
        <div>
          {rules?.rules?.length > 0 ? (
            <div style={{ maxHeight: 200, overflowY: "auto" }}>
              {rules.rules.map((r) => (
                <div key={r.rule_id} style={{ borderBottom: "1px solid #333", padding: "4px 0", fontSize: 12 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ textTransform: "capitalize" }}>{r.rule_type?.replace(/_/g, " ")}</span>
                    <span style={{ color: r.enabled ? "#4caf50" : "#666" }}>
                      {r.enabled ? "Active" : "Disabled"}
                    </span>
                  </div>
                  {r.radius_km && <div style={{ color: "#888" }}>Radius: {r.radius_km} km</div>}
                </div>
              ))}
            </div>
          ) : !loading && (
            <div style={{ color: "#666", fontSize: 13 }}>No alert rules configured</div>
          )}
        </div>
      )}
    </div>
  );
}
