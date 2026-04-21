/**
 * Toast — global render layer for the `toast` primitive.
 *
 * Mount once near the App root. Listens to `src/lib/toast.js` and renders
 * a vertical stack at bottom-right with slide-from-right animation.
 */
import React, { useEffect, useState } from "react";
import { subscribe, toast } from "../lib/toast";

const COLOURS = {
  success: { bg: "#0F1318", border: "#3B8A5A", accent: "#3B8A5A", fg: "#FFFFFF" },
  error:   { bg: "#0F1318", border: "#C64545", accent: "#C64545", fg: "#FFFFFF" },
  info:    { bg: "#0F1318", border: "#F5B731", accent: "#F5B731", fg: "#FFFFFF" },
};

export default function Toast() {
  const [items, setItems] = useState([]);

  useEffect(() => subscribe(setItems), []);

  return (
    <>
      <style>{`
        @keyframes princepsToastSlideIn {
          from { transform: translateX(120%); opacity: 0; }
          to   { transform: translateX(0);     opacity: 1; }
        }
      `}</style>
      <div
        aria-live="polite"
        aria-atomic="true"
        style={{
          position: "fixed",
          right: 20,
          bottom: 20,
          zIndex: 100000,
          display: "flex",
          flexDirection: "column",
          gap: 8,
          pointerEvents: "none",
          fontFamily: "'DM Sans', sans-serif",
        }}
      >
        {items.map((t) => {
          const c = COLOURS[t.level] || COLOURS.info;
          return (
            <div
              key={t.id}
              role="status"
              onClick={() => toast.dismiss(t.id)}
              style={{
                pointerEvents: "auto",
                minWidth: 220,
                maxWidth: 360,
                background: c.bg,
                color: c.fg,
                border: `1px solid ${c.border}`,
                borderLeft: `4px solid ${c.accent}`,
                borderRadius: 8,
                padding: "10px 14px",
                fontSize: 12,
                fontWeight: 600,
                letterSpacing: "-0.005em",
                lineHeight: 1.45,
                boxShadow: "0 10px 24px rgba(0,0,0,0.18)",
                cursor: "pointer",
                animation: "princepsToastSlideIn 180ms ease-out",
              }}
            >
              {t.message}
            </div>
          );
        })}
      </div>
    </>
  );
}
