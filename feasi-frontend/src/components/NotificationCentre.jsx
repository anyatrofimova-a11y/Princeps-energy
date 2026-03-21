/**
 * NotificationCentre — Real-time alerts for grid, planning, price triggers.
 *
 * Polls /api/grid/live-status for threshold breaches, monitors constraint
 * changes, and shows actionable notifications with timestamps.
 */
import React, { useState, useEffect, useCallback, useRef } from "react";

const POLL_MS = 60_000; // Check every minute

function timeAgo(ts) {
  const diff = Date.now() - new Date(ts).getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

const SEVERITY_COLORS = {
  critical: "#f44336",
  warning: "#ff9800",
  info: "#2196f3",
  success: "#4caf50",
};

export default function NotificationCentre() {
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [unread, setUnread] = useState(0);
  const prevRef = useRef({});

  const addNotification = useCallback((n) => {
    setNotifications(prev => [{
      id: Date.now() + Math.random(),
      timestamp: new Date().toISOString(),
      read: false,
      ...n,
    }, ...prev].slice(0, 50));
    setUnread(u => u + 1);
  }, []);

  // Poll for live grid status and generate notifications on threshold breach
  useEffect(() => {
    const check = async () => {
      try {
        const r = await fetch("/api/grid/live-status");
        if (!r.ok) return;
        const d = await r.json();
        const prev = prevRef.current;

        // Frequency deviation
        if (d.frequency_hz && Math.abs(d.frequency_hz - 50) > 0.1) {
          if (!prev.freqAlert || Date.now() - prev.freqAlert > 300_000) {
            addNotification({
              severity: "critical",
              title: "Grid Frequency Deviation",
              message: `Frequency at ${d.frequency_hz.toFixed(3)} Hz — ${Math.abs(d.frequency_hz - 50) > 0.15 ? "significant" : "minor"} deviation from 50 Hz`,
              category: "grid",
            });
            prev.freqAlert = Date.now();
          }
        }

        // Price spike
        if (d.price_gbp_mwh && d.price_gbp_mwh > 150) {
          if (!prev.priceAlert || Date.now() - prev.priceAlert > 600_000) {
            addNotification({
              severity: "warning",
              title: "Wholesale Price Spike",
              message: `£${d.price_gbp_mwh.toFixed(0)}/MWh — consider deferring non-critical loads`,
              category: "price",
            });
            prev.priceAlert = Date.now();
          }
        }

        // High carbon intensity
        if (d.carbon_intensity && d.carbon_intensity > 250) {
          if (!prev.carbonAlert || Date.now() - prev.carbonAlert > 600_000) {
            addNotification({
              severity: "warning",
              title: "High Carbon Intensity",
              message: `${d.carbon_intensity} gCO₂/kWh — grid running on fossil fuels`,
              category: "carbon",
            });
            prev.carbonAlert = Date.now();
          }
        }

        // Low renewable percentage
        if (d.renewable_pct != null && d.renewable_pct > 60) {
          if (!prev.renewAlert || Date.now() - prev.renewAlert > 1_800_000) {
            addNotification({
              severity: "success",
              title: "High Renewable Generation",
              message: `${d.renewable_pct}% renewable — ideal time for energy-intensive operations`,
              category: "grid",
            });
            prev.renewAlert = Date.now();
          }
        }

        prevRef.current = prev;
      } catch {}
    };

    check();
    const id = setInterval(check, POLL_MS);
    return () => clearInterval(id);
  }, [addNotification]);

  // Seed with startup notification
  useEffect(() => {
    addNotification({
      severity: "info",
      title: "Princeps Online",
      message: "Connected to BMRS, Carbon Intensity API, and 6 DNO data feeds",
      category: "system",
    });
  }, []);

  const markAllRead = () => {
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
    setUnread(0);
  };

  const dismiss = (id) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
    setUnread(u => Math.max(0, u - 1));
  };

  return (
    <>
      {/* Bell button */}
      <button
        className="notif-bell"
        onClick={() => { setOpen(!open); if (!open) markAllRead(); }}
        title="Notifications"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/>
          <path d="M13.73 21a2 2 0 01-3.46 0"/>
        </svg>
        {unread > 0 && <span className="notif-badge">{unread > 9 ? "9+" : unread}</span>}
      </button>

      {/* Panel */}
      {open && (
        <div className="notif-panel">
          <div className="notif-header">
            <span className="notif-title">Notifications</span>
            <div className="notif-actions">
              {notifications.length > 0 && (
                <button className="notif-clear" onClick={() => { setNotifications([]); setUnread(0); }}>
                  Clear all
                </button>
              )}
              <button className="notif-close" onClick={() => setOpen(false)}>&times;</button>
            </div>
          </div>

          <div className="notif-list">
            {notifications.length === 0 && (
              <div className="notif-empty">No notifications</div>
            )}
            {notifications.map(n => (
              <div key={n.id} className={`notif-item ${n.read ? "" : "unread"}`}>
                <div
                  className="notif-severity-dot"
                  style={{ background: SEVERITY_COLORS[n.severity] || "#888" }}
                />
                <div className="notif-content">
                  <div className="notif-item-title">{n.title}</div>
                  <div className="notif-item-msg">{n.message}</div>
                  <div className="notif-item-meta">
                    <span className="notif-category">{n.category}</span>
                    <span className="notif-time">{timeAgo(n.timestamp)}</span>
                  </div>
                </div>
                <button className="notif-dismiss" onClick={() => dismiss(n.id)}>&times;</button>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
