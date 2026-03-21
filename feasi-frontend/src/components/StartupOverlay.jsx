import React, { useEffect, useState, useRef } from "react";

const SUBSYSTEMS = [
  { key: "database",          label: "Database",           icon: "\u25A0" },
  { key: "core_api",          label: "Core API",           icon: "\u25B6" },
  { key: "grid_data",         label: "Grid Data",          icon: "\u26A1" },
  { key: "demand_data",       label: "Demand Data",        icon: "\u25CF" },
  { key: "neo4j",             label: "Graph Topology",     icon: "\u2630" },
  { key: "geeflow",           label: "GeeFlow",            icon: "\u25B2" },
  { key: "dc_infrastructure", label: "DC Infrastructure",  icon: "\u25A0" },
];

const STATUS_COLORS = {
  ready:   "#4ade80",
  loading: "#60a5fa",
  pending: "#6b7280",
  failed:  "#f87171",
};

const STATUS_LABELS = {
  ready:   "Online",
  loading: "Loading",
  pending: "Pending",
  failed:  "Failed",
};

export default function StartupOverlay({ onReady }) {
  const [readiness, setReadiness] = useState(null);
  const [dismissed, setDismissed] = useState(false);
  const abortRef = useRef(null);

  useEffect(() => {
    const ac = new AbortController();
    abortRef.current = ac;

    const poll = async () => {
      if (ac.signal.aborted) return;
      try {
        const res = await fetch("/api/readiness", { signal: ac.signal });
        if (res.ok) {
          const data = await res.json();
          setReadiness(data);
          if (data.core_ready) {
            // Core is ready — user can start interacting
            setTimeout(() => {
              setDismissed(true);
              onReady?.(data);
            }, 600);
            return; // stop polling
          }
        } else {
          setReadiness(null);
        }
      } catch (err) {
        if (err.name === "AbortError") return;
        setReadiness(null);
      }
      setTimeout(poll, 1500);
    };

    poll();
    return () => ac.abort();
  }, [onReady]);

  if (dismissed) return null;

  const isConnecting = readiness === null;
  const overall = readiness?.overall ?? "starting";
  const subsystems = readiness?.subsystems ?? {};
  const allReady = overall === "ready";

  return (
    <div style={styles.overlay}>
      <div style={styles.card}>
        {/* Logo */}
        <div style={styles.logo}>PRINCEPS</div>
        <div style={styles.subtitle}>Energy Infrastructure Intelligence</div>

        {/* Spinner */}
        <div style={styles.spinnerWrap}>
          {allReady ? (
            <div style={styles.checkmark}>&#10003;</div>
          ) : (
            <div style={styles.spinner} />
          )}
        </div>

        {/* Status line */}
        <div style={styles.statusLine}>
          {isConnecting
            ? "Connecting to backend..."
            : allReady
              ? "All systems operational"
              : readiness?.core_ready
                ? "Core online \u2014 loading background data..."
                : "Starting subsystems..."}
        </div>

        {/* Uptime */}
        {readiness?.uptime_s != null && (
          <div style={styles.uptime}>{readiness.uptime_s}s elapsed</div>
        )}

        {/* Subsystem checklist */}
        {!isConnecting && (
          <div style={styles.checklist}>
            {SUBSYSTEMS.map(({ key, label }) => {
              const info = subsystems[key] || { status: "pending" };
              const color = STATUS_COLORS[info.status] || STATUS_COLORS.pending;
              const statusText = info.progress
                ? info.progress
                : info.error
                  ? `Failed: ${info.error.slice(0, 40)}`
                  : STATUS_LABELS[info.status] || info.status;

              return (
                <div key={key} style={styles.checkItem}>
                  <span style={{ ...styles.checkIcon, color }}>
                    {info.status === "ready"
                      ? "\u2713"
                      : info.status === "failed"
                        ? "\u2717"
                        : info.status === "loading"
                          ? "\u25CB"
                          : "\u2022"}
                  </span>
                  <span style={styles.checkLabel}>{label}</span>
                  <span style={{ ...styles.checkStatus, color }}>
                    {statusText}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <style>{`
        @keyframes princeps-spin {
          to { transform: rotate(360deg); }
        }
        @keyframes princeps-fadeIn {
          from { opacity: 0; transform: translateY(12px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes princeps-pulse {
          0%, 100% { opacity: 0.6; }
          50%      { opacity: 1; }
        }
      `}</style>
    </div>
  );
}

const styles = {
  overlay: {
    position: "fixed",
    inset: 0,
    zIndex: 99999,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "radial-gradient(ellipse at center, #1a1a2e 0%, #0d0d1a 100%)",
  },
  card: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 12,
    animation: "princeps-fadeIn 0.5s ease-out",
  },
  logo: {
    fontSize: 32,
    fontWeight: 700,
    letterSpacing: 6,
    color: "#e0e0ff",
    fontFamily: "'Inter', system-ui, sans-serif",
  },
  subtitle: {
    fontSize: 12,
    color: "#8888aa",
    letterSpacing: 2,
    textTransform: "uppercase",
    marginBottom: 16,
  },
  spinnerWrap: {
    width: 48,
    height: 48,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 8,
  },
  spinner: {
    width: 36,
    height: 36,
    border: "3px solid #333355",
    borderTopColor: "#6366f1",
    borderRadius: "50%",
    animation: "princeps-spin 0.8s linear infinite",
  },
  checkmark: {
    fontSize: 32,
    color: "#4ade80",
    fontWeight: 700,
  },
  statusLine: {
    fontSize: 13,
    color: "#aaaabb",
    animation: "princeps-pulse 2s ease-in-out infinite",
  },
  uptime: {
    fontSize: 11,
    color: "#666680",
    marginTop: -4,
  },
  checklist: {
    marginTop: 12,
    display: "flex",
    flexDirection: "column",
    gap: 8,
    minWidth: 280,
  },
  checkItem: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    fontSize: 13,
    fontFamily: "'Inter', system-ui, sans-serif",
  },
  checkIcon: {
    fontSize: 14,
    width: 16,
    textAlign: "center",
  },
  checkLabel: {
    color: "#ccccdd",
    flex: 1,
  },
  checkStatus: {
    fontSize: 11,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    maxWidth: 160,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
};
