import React, { useEffect, useMemo, useState } from "react";
import { getAlertLibrary } from "../../../api/alerts";

const C = {
  gold: "#F5B731",
  goldSoft: "#C9A64B",
  goldSurface: "rgba(245,183,49,0.10)",
  goldBorder: "rgba(245,183,49,0.32)",
  ink: "#0F1318",
  secondary: "#4B5563",
  tertiary: "#9C9590",
  border: "#E8EAED",
  ivory: "#FBF8F2",
};

function Overlay({ children, onClose }) {
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0,
        background: "rgba(15,19,24,0.45)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 1000,
        fontFamily: "'DM Sans', sans-serif",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(560px, 92vw)",
          maxHeight: "82vh",
          background: "#FFFFFF",
          borderRadius: 12,
          border: `1px solid ${C.border}`,
          boxShadow: "0 12px 48px rgba(15,19,24,0.18)",
          display: "flex", flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {children}
      </div>
    </div>
  );
}

function Row({ alert, checked, onToggle }) {
  return (
    <label
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        padding: "8px 12px",
        borderTop: `1px solid ${C.border}`,
        cursor: "pointer",
      }}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={() => onToggle(alert.id)}
        style={{ marginTop: 3, accentColor: C.gold }}
      />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: C.ink, lineHeight: 1.3 }}>
          {alert.name}
        </div>
        <div style={{
          fontSize: 11, color: C.tertiary, marginTop: 2,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {alert.source} · {alert.cluster} · {alert.cadence}
        </div>
      </div>
    </label>
  );
}

/**
 * SubscribeModal — two modes:
 *   target = { alert } → customise single alert (cadence toggles + subscribe)
 *   target = { pack }  → review/edit a starter pack before subscribing
 */
export default function SubscribeModal({ target, onClose, onSubscribeAlert, onSubscribeAll }) {
  const { alert, pack } = target || {};

  // Live alert library — flattened from the cluster groupings the
  // backend returns at /api/alerts/library.
  const [allAlerts, setAllAlerts] = useState([]);
  useEffect(() => {
    let cancelled = false;
    getAlertLibrary()
      .then((d) => {
        if (cancelled) return;
        const flat = (d.clusters || []).flatMap((c) => c.items || []);
        setAllAlerts(flat.length ? flat : d.alerts || []);
      })
      .catch(() => { if (!cancelled) setAllAlerts([]); });
    return () => { cancelled = true; };
  }, []);

  const initialIds = useMemo(() => {
    if (pack) return new Set(pack.alert_ids);
    if (alert) return new Set([alert.id]);
    return new Set();
  }, [alert, pack]);

  const [selected, setSelected] = useState(initialIds);

  const toggleId = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const list = useMemo(() => {
    if (pack) {
      return allAlerts.filter((a) => pack.alert_ids.includes(a.id));
    }
    if (alert) {
      return [alert];
    }
    return [];
  }, [alert, pack, allAlerts]);

  const title = pack
    ? `Starter pack · ${pack.persona}`
    : `Customise alert`;
  const subtitle = pack
    ? `${pack.alert_count} alerts curated for ${pack.persona.toLowerCase()}. Deselect any you don't need.`
    : alert?.description || "";

  const confirmLabel = pack
    ? `Subscribe to ${selected.size} alert${selected.size === 1 ? "" : "s"}`
    : `Subscribe`;

  const onConfirm = () => {
    if (pack) {
      onSubscribeAll?.([...selected]);
    } else if (alert) {
      onSubscribeAlert?.(alert.id);
    }
  };

  return (
    <Overlay onClose={onClose}>
      {/* Header */}
      <div style={{
        padding: "16px 20px 12px",
        borderBottom: `1px solid ${C.border}`,
      }}>
        <div style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 10, fontWeight: 700, color: C.goldSoft,
          letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 4,
        }}>
          Intelligence · Alerts
        </div>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
          <div style={{ flex: 1 }}>
            <h3 style={{
              margin: "0 0 4px", fontSize: 16, fontWeight: 700,
              letterSpacing: "-0.01em", color: C.ink,
            }}>
              {title}
            </h3>
            <p style={{ margin: 0, fontSize: 12, color: C.secondary, lineHeight: 1.5 }}>
              {subtitle}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              width: 28, height: 28, borderRadius: 6,
              border: `1px solid ${C.border}`,
              background: "#FFFFFF", color: C.tertiary,
              cursor: "pointer", fontSize: 14, lineHeight: 1,
            }}
          >
            ×
          </button>
        </div>
      </div>

      {/* Body */}
      <div style={{ flex: 1, overflowY: "auto", background: C.ivory }}>
        {list.map((a) => (
          <Row
            key={a.id}
            alert={a}
            checked={selected.has(a.id)}
            onToggle={toggleId}
          />
        ))}
      </div>

      {/* Footer */}
      <div style={{
        padding: "12px 20px",
        borderTop: `1px solid ${C.border}`,
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: 12, background: "#FFFFFF",
      }}>
        <div style={{ fontSize: 11, color: C.tertiary }}>
          Cadence, delivery channel and keywords can be edited anytime.
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={onClose}
            style={{
              padding: "6px 14px",
              fontSize: 12, fontWeight: 600,
              border: `1px solid ${C.border}`,
              background: "#FFFFFF", color: C.secondary,
              borderRadius: 6, cursor: "pointer",
            }}
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={selected.size === 0}
            style={{
              padding: "6px 14px",
              fontSize: 12, fontWeight: 700,
              border: "none",
              background: selected.size === 0 ? "#E8EAED" : C.gold,
              color: selected.size === 0 ? C.tertiary : C.ink,
              borderRadius: 6,
              cursor: selected.size === 0 ? "not-allowed" : "pointer",
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </Overlay>
  );
}
