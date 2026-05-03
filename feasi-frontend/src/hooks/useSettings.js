import {useCallback, useEffect, useState} from 'react';

/**
 * localStorage-backed app settings, with cross-component sync via a custom
 * event (single-tab) and the native `storage` event (cross-tab).
 *
 * Replaces the `settings` / `settingsForm` pair from SiteContext.
 *
 *   const [settings, updateSettings] = useSettings();
 *   updateSettings({theme: 'gold-light'});
 *   updateSettings(prev => ({...prev, units: 'imperial'}));
 */

const STORAGE_KEY = 'princeps_settings';
const SYNC_EVENT = 'px:settings-changed';

// Defaults mirror the existing SiteContext SETTINGS_DEFAULTS so consumers
// see no behaviour change when SiteContext flips to use this hook.
const DEFAULTS = Object.freeze({
  // Map & display
  mapStyle: 'dark',
  defaultSlopeOpacity: 0.6,
  defaultLayers: ['hillshade', 'contours', 'environment', 'aerial'],
  theme: 'dark',
  // API & connections
  mapboxToken: '',
  geeProjectId: '',
  backendUrl: '',
  // Profile & notifications
  displayName: '',
  email: '',
  exportFormat: 'csv',
  notifications: true,
});

function read() {
  if (typeof localStorage === 'undefined') return {...DEFAULTS};
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? {...DEFAULTS, ...JSON.parse(raw)} : {...DEFAULTS};
  } catch {
    return {...DEFAULTS};
  }
}

function write(value) {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    window.dispatchEvent(new Event(SYNC_EVENT));
  } catch {
    /* quota / privacy mode — soft-fail */
  }
}

export function useSettings() {
  const [settings, setSettings] = useState(read);

  useEffect(() => {
    const sync = () => setSettings(read());
    window.addEventListener(SYNC_EVENT, sync);
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener(SYNC_EVENT, sync);
      window.removeEventListener('storage', sync);
    };
  }, []);

  const update = useCallback((patch) => {
    const cur = read();
    const next = typeof patch === 'function' ? patch(cur) : {...cur, ...patch};
    write(next);
    setSettings(next);
  }, []);

  return [settings, update];
}

export const SETTINGS_DEFAULTS = DEFAULTS;
