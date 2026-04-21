/**
 * Princeps 3D Twin — AttributionFooter
 * ----------------------------------------------------------------------
 * Renders a small gold-accented credit line at the bottom-right of the
 * twin viewport satisfying the CC-BY-4.0 attribution requirement for every
 * model shipped under `/public/assets/twin3d/`. Clicking the line opens a
 * modal with the full licence table sourced from `LICENSES.md`.
 *
 * The footer is mandatory — do not hide or remove it. It is part of the
 * licence compliance surface of the 3D twin.
 *
 * Drop into TwinRoot:
 *
 *   import AttributionFooter from "./AttributionFooter";
 *   ...
 *   <AttributionFooter />
 *
 * No props are required. Uses Vite raw-import for the licence markdown
 * (built-in, no extra plugin) so the table ships with the client bundle
 * and the modal opens without a network round-trip.
 */

import React, { useEffect, useMemo, useState } from 'react';
import { listManifestEntries } from './assets/gltfLoader';

// LICENCE_TEXT is fetched at runtime from the static public asset. We do NOT
// Vite-`?raw` import it because `public/` files are not part of the module
// graph. The first render shows a loading message; the modal lazily pulls
// the markdown when the user opens it.
const LICENCE_URL = '/assets/twin3d/LICENSES.md';

const GOLD = '#F5B731';
const INK = '#0F1318';
const IVORY = '#FBF8F2';

// --- Attribution summary builder ----------------------------------------
function buildSummary(entries) {
  if (!entries?.length) return '3D models: (pending attribution)';
  const ccby = entries.filter((e) => (e.licence || '').toUpperCase().startsWith('CC-BY'));
  const cc0  = entries.filter((e) => (e.licence || '').toUpperCase() === 'CC0');

  const bits = [];
  if (ccby.length) {
    // Show the highest-value CC-BY explicitly (Tesla if present)
    const tesla = ccby.find((e) => e.asset_id?.includes('megapack'));
    if (tesla) bits.push('Tesla by author (CC-BY-4.0)');
    if (ccby.length > (tesla ? 1 : 0)) {
      const remaining = ccby.length - (tesla ? 1 : 0);
      bits.push(`${remaining} more CC-BY source${remaining === 1 ? '' : 's'}`);
    }
  }
  if (cc0.length) {
    bits.push('Kenney Industrial Kit (CC0)');
  }
  const total = entries.length;
  return `3D models: ${bits.join(' · ')} · ${total} source${total === 1 ? '' : 's'}`;
}

// --- Component -----------------------------------------------------------
export default function AttributionFooter() {
  const [open, setOpen] = useState(false);
  // manifest entries arrive asynchronously — re-render when hydrated
  const [, forceTick] = useState(0);
  useEffect(() => {
    const id = setTimeout(() => forceTick((t) => t + 1), 400);
    const id2 = setTimeout(() => forceTick((t) => t + 1), 1500);
    return () => { clearTimeout(id); clearTimeout(id2); };
  }, []);

  const entries = useMemo(() => listManifestEntries(), []);
  const summary = useMemo(() => buildSummary(entries), [entries]);

  return (
    <>
      <div
        className="princeps-twin-attr"
        onClick={() => setOpen(true)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setOpen(true); }}
        aria-label="Open 3D model attribution and licence info"
      >
        <span className="princeps-twin-attr-dot" />
        <span className="princeps-twin-attr-text">{summary}</span>
        <span className="princeps-twin-attr-more">LICENSES</span>
      </div>

      {open && (
        <AttributionModal onClose={() => setOpen(false)} licenceUrl={LICENCE_URL} />
      )}

      <style>{`
        .princeps-twin-attr {
          position: absolute;
          right: 12px;
          bottom: 10px;
          z-index: 7;
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 5px 10px;
          background: rgba(15, 19, 24, 0.72);
          backdrop-filter: blur(8px);
          border: 1px solid rgba(245, 183, 49, 0.32);
          border-radius: 6px;
          color: ${IVORY};
          font-family: "DM Sans", -apple-system, sans-serif;
          font-size: 11px;
          letter-spacing: 0.01em;
          cursor: pointer;
          transition: border-color 140ms ease, background 140ms ease;
          max-width: 520px;
        }
        .princeps-twin-attr:hover,
        .princeps-twin-attr:focus-visible {
          border-color: ${GOLD};
          background: rgba(15, 19, 24, 0.88);
          outline: none;
        }
        .princeps-twin-attr-dot {
          width: 6px; height: 6px;
          border-radius: 50%;
          background: ${GOLD};
          box-shadow: 0 0 6px rgba(245, 183, 49, 0.8);
          flex-shrink: 0;
        }
        .princeps-twin-attr-text {
          opacity: 0.85;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .princeps-twin-attr-more {
          color: ${GOLD};
          font-weight: 700;
          letter-spacing: 0.06em;
          font-size: 10px;
          border-left: 1px solid rgba(245, 183, 49, 0.32);
          padding-left: 8px;
        }
      `}</style>
    </>
  );
}

// --- Modal ---------------------------------------------------------------
function AttributionModal({ onClose, licenceUrl }) {
  const [licenceText, setLicenceText] = useState('Loading LICENSES.md…');

  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose(); }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    let alive = true;
    fetch(licenceUrl, { cache: 'no-store' })
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((t) => { if (alive) setLicenceText(t); })
      .catch((err) => {
        if (alive) {
          setLicenceText(
            `Could not load LICENSES.md — see ${licenceUrl}\n\nError: ${err.message}`,
          );
        }
      });
    return () => { alive = false; };
  }, [licenceUrl]);

  return (
    <div
      className="princeps-twin-attr-backdrop"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="3D model attribution and licence register"
    >
      <div
        className="princeps-twin-attr-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="princeps-twin-attr-header">
          <div>
            <div className="princeps-twin-attr-title">3D Model Attribution</div>
            <div className="princeps-twin-attr-sub">
              Open-licence assets bundled in the Princeps 3D Twin
            </div>
          </div>
          <button
            className="princeps-twin-attr-close"
            onClick={onClose}
            aria-label="Close"
          >×</button>
        </div>

        <pre className="princeps-twin-attr-body">{licenceText}</pre>

        <div className="princeps-twin-attr-footer">
          <span>
            CC-BY-4.0 asset? Author credit is required. Raise a PR to
            <code> LICENSES.md</code> before a new asset lands.
          </span>
        </div>
      </div>

      <style>{`
        .princeps-twin-attr-backdrop {
          position: fixed;
          inset: 0;
          background: rgba(15, 19, 24, 0.75);
          backdrop-filter: blur(6px);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          padding: 24px;
          font-family: "DM Sans", -apple-system, sans-serif;
        }
        .princeps-twin-attr-panel {
          background: ${IVORY};
          color: ${INK};
          width: min(920px, 100%);
          max-height: 80vh;
          display: flex;
          flex-direction: column;
          border: 1px solid rgba(15, 19, 24, 0.12);
          border-top: 3px solid ${GOLD};
          border-radius: 8px;
          box-shadow: 0 20px 60px rgba(0,0,0,0.35);
          overflow: hidden;
        }
        .princeps-twin-attr-header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          padding: 18px 22px 14px;
          border-bottom: 1px solid rgba(15,19,24,0.06);
        }
        .princeps-twin-attr-title {
          font-size: 16px;
          font-weight: 700;
          letter-spacing: 0.01em;
        }
        .princeps-twin-attr-sub {
          font-size: 12px;
          color: rgba(15,19,24,0.55);
          margin-top: 3px;
        }
        .princeps-twin-attr-close {
          background: transparent;
          border: none;
          font-size: 24px;
          line-height: 1;
          color: rgba(15,19,24,0.55);
          cursor: pointer;
          padding: 0 4px;
        }
        .princeps-twin-attr-close:hover { color: ${INK}; }
        .princeps-twin-attr-body {
          flex: 1;
          overflow: auto;
          padding: 18px 22px;
          font-family: "Geist Mono", "SF Mono", ui-monospace, monospace;
          font-size: 12px;
          line-height: 1.55;
          background: #f7f4ed;
          color: #1A1D23;
          white-space: pre-wrap;
          word-break: break-word;
          margin: 0;
        }
        .princeps-twin-attr-footer {
          padding: 11px 22px;
          font-size: 11px;
          color: rgba(15,19,24,0.6);
          border-top: 1px solid rgba(15,19,24,0.06);
          background: #fbf8f2;
        }
        .princeps-twin-attr-footer code {
          background: rgba(245, 183, 49, 0.12);
          padding: 1px 4px;
          border-radius: 3px;
        }
      `}</style>
    </div>
  );
}
