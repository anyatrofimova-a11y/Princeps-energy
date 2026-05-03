import {useState, useEffect, useCallback} from 'react';

/**
 * Foundry-style collapsible drawer.
 *
 * Collapsed (default): 36px-wide rail with a single toggle button.
 * Expanded:            320px-wide overlay panel — does NOT displace the
 *                      main content (so existing routes / LegacyApp absolute-
 *                      positioned panels keep working).
 * State:               persisted to localStorage per drawer.
 *
 * Props:
 *   side          'left' | 'right'
 *   defaultExpanded  boolean (default false)
 *   storageKey?   string — defaults to 'px-drawer-{side}'
 *   icon?         string — optional rail icon (when collapsed)
 *   title?        string — header inside the expanded panel
 *   children      panel content
 */
export function CollapsibleDrawer({
  side = 'left',
  defaultExpanded = false,
  storageKey,
  icon,
  title,
  children,
}) {
  const key = storageKey ?? `px-drawer-${side}`;
  const [expanded, setExpanded] = useState(() => {
    try {
      const stored = typeof localStorage !== 'undefined' ? localStorage.getItem(key) : null;
      if (stored === 'true') return true;
      if (stored === 'false') return false;
      return defaultExpanded;
    } catch {
      return defaultExpanded;
    }
  });

  useEffect(() => {
    try { localStorage.setItem(key, String(expanded)); } catch { /* ignore */ }
  }, [key, expanded]);

  const toggle = useCallback(() => setExpanded((v) => !v), []);

  // Keyboard: Cmd/Ctrl + [ for left drawer, Cmd/Ctrl + ] for right.
  useEffect(() => {
    const handler = (e) => {
      const isMod = e.metaKey || e.ctrlKey;
      if (!isMod) return;
      if (side === 'left' && e.key === '[') { e.preventDefault(); toggle(); }
      if (side === 'right' && e.key === ']') { e.preventDefault(); toggle(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [side, toggle]);

  return (
    <aside
      className={`px-drawer px-drawer-${side} ${expanded ? 'is-expanded' : 'is-collapsed'}`}
      aria-expanded={expanded}
    >
      <button
        type="button"
        className="px-drawer-toggle"
        onClick={toggle}
        title={`${expanded ? 'Collapse' : 'Expand'} (${side === 'left' ? '⌘[' : '⌘]'})`}
        aria-label={`${expanded ? 'Collapse' : 'Expand'} ${side} drawer`}
      >
        <span className="px-drawer-toggle-glyph">
          {icon ?? (side === 'left'
            ? (expanded ? '⟨' : '⟩')
            : (expanded ? '⟩' : '⟨'))}
        </span>
      </button>
      {expanded ? (
        <div className="px-drawer-panel">
          {title ? <header className="px-drawer-title">{title}</header> : null}
          <div className="px-drawer-content">{children}</div>
        </div>
      ) : null}
    </aside>
  );
}
