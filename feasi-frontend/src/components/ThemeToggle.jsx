/**
 * ThemeToggle — Dark/Light/System theme switcher.
 *
 * Applies CSS class to document root and persists preference.
 * Supports: dark (default), light, system (auto from OS).
 */
import React, { useState, useEffect, useCallback } from "react";
import { useSite } from "../SiteContext";

const THEMES = [
  { id: "dark", label: "Dark", icon: "🌙" },
  { id: "light", label: "Light", icon: "☀️" },
  { id: "system", label: "System", icon: "💻" },
];

function getSystemTheme() {
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function applyTheme(theme) {
  const resolved = theme === "system" ? getSystemTheme() : theme;
  document.documentElement.setAttribute("data-theme", resolved);
  document.documentElement.classList.toggle("light-theme", resolved === "light");
}

export default function ThemeToggle({ compact = false }) {
  const { settings, saveSettings } = useSite();
  const [theme, setTheme] = useState(settings?.theme || "dark");

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // Listen for system theme changes
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const handler = () => applyTheme("system");
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [theme]);

  const cycle = useCallback(() => {
    const idx = THEMES.findIndex(t => t.id === theme);
    const next = THEMES[(idx + 1) % THEMES.length];
    setTheme(next.id);
    saveSettings?.({ ...settings, theme: next.id });
  }, [theme, settings, saveSettings]);

  if (compact) {
    return (
      <button className="theme-toggle-compact" onClick={cycle} title={`Theme: ${theme}`}>
        {THEMES.find(t => t.id === theme)?.icon || "🌙"}
      </button>
    );
  }

  return (
    <div className="theme-toggle">
      {THEMES.map(t => (
        <button
          key={t.id}
          className={`theme-toggle-btn ${theme === t.id ? "active" : ""}`}
          onClick={() => {
            setTheme(t.id);
            saveSettings?.({ ...settings, theme: t.id });
          }}
          title={t.label}
        >
          <span>{t.icon}</span>
          <span className="theme-toggle-label">{t.label}</span>
        </button>
      ))}
    </div>
  );
}
