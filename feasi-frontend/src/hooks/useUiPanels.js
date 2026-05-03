import {useCallback, useEffect, useState} from 'react';

/**
 * URL-hash-backed UI panel registry — replaces the 30+ `*Open` booleans that
 * used to live in SiteContext.
 *
 * Wire format: `#panels=grid-connection,demand-forecast,bess-panel`
 *
 * Why URL hash and not query string: panel state is purely UI; we don't
 * want it in the search params (those are owned by useSiteTarget /
 * useSearchParams for parcel id, lat/lng, etc.).
 *
 * Cross-component sync: `replaceState` doesn't fire `hashchange`, so we
 * dispatch a custom `px:panels-changed` event on every write.
 *
 * Public surface:
 *   const {isOpen, setPanelOpen, togglePanel, closeAll, openSet} = useUiPanels();
 *   const [open, setOpen] = usePanel('grid-connection');   // drop-in for useState(false)
 */

const SYNC_EVENT = 'px:panels-changed';
const PANELS_KEY = 'panels';

function readFromHash() {
  if (typeof window === 'undefined') return new Set();
  const hash = window.location.hash || '';
  const stripped = hash.startsWith('#') ? hash.slice(1) : hash;
  const parts = stripped.split('&').filter(Boolean);
  for (const p of parts) {
    if (p.startsWith(`${PANELS_KEY}=`)) {
      return new Set(p.slice(PANELS_KEY.length + 1).split(',').filter(Boolean));
    }
  }
  return new Set();
}

function writeToHash(panelSet) {
  if (typeof window === 'undefined') return;
  const hash = window.location.hash || '';
  const stripped = hash.startsWith('#') ? hash.slice(1) : hash;
  const others = stripped.split('&').filter((p) => p && !p.startsWith(`${PANELS_KEY}=`));
  const panelsPart = panelSet.size > 0
    ? `${PANELS_KEY}=${[...panelSet].sort().join(',')}`
    : '';
  const next = [panelsPart, ...others].filter(Boolean).join('&');
  const newHash = next ? `#${next}` : '';
  if (newHash !== window.location.hash) {
    const url = `${window.location.pathname}${window.location.search}${newHash}`;
    window.history.replaceState(null, '', url);
    window.dispatchEvent(new Event(SYNC_EVENT));
  }
}

export function useUiPanels() {
  const [openSet, setOpenSet] = useState(readFromHash);

  useEffect(() => {
    const sync = () => setOpenSet(readFromHash());
    window.addEventListener(SYNC_EVENT, sync);
    window.addEventListener('hashchange', sync);
    return () => {
      window.removeEventListener(SYNC_EVENT, sync);
      window.removeEventListener('hashchange', sync);
    };
  }, []);

  const isOpen = useCallback((name) => openSet.has(name), [openSet]);

  const setPanelOpen = useCallback((name, value) => {
    const cur = readFromHash();
    const next = new Set(cur);
    if (value) next.add(name); else next.delete(name);
    writeToHash(next);
    setOpenSet(next);
  }, []);

  const togglePanel = useCallback((name) => {
    const cur = readFromHash();
    const next = new Set(cur);
    if (next.has(name)) next.delete(name); else next.add(name);
    writeToHash(next);
    setOpenSet(next);
  }, []);

  const closeAll = useCallback(() => {
    writeToHash(new Set());
    setOpenSet(new Set());
  }, []);

  return {isOpen, setPanelOpen, togglePanel, closeAll, openSet};
}

/**
 * Drop-in replacement for `const [xOpen, setXOpen] = useState(false)`.
 * Supports functional updates: `setOpen(prev => !prev)`.
 *
 *   const [gridConnectionOpen, setGridConnectionOpen] = usePanel('grid-connection');
 */
export function usePanel(name) {
  const {isOpen, setPanelOpen} = useUiPanels();
  const cur = isOpen(name);
  const setter = useCallback((value) => {
    const resolved = typeof value === 'function' ? value(cur) : value;
    setPanelOpen(name, Boolean(resolved));
  }, [name, cur, setPanelOpen]);
  return [cur, setter];
}
