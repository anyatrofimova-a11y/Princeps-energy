/**
 * OIMFeaturePopup — clean React popover rendered into a Mapbox GL popup for
 * any feature in an OpenInfraMap-styled overlay layer.
 *
 * Usage: produces an HTML string the caller passes to mapboxgl.Popup.setHTML().
 * We deliberately avoid a React portal here because Mapbox manages the popup
 * lifecycle (position, removal on map move) and a simple HTML string keeps the
 * code free of DOM-mounting gymnastics — exactly as the upstream OIM popup
 * does (web/src/popup/).
 *
 * Exports both:
 *   - `renderOimPopupHtml(feature)` — string for setHTML()
 *   - `OIMFeaturePopup` — React component for callers that prefer JSX
 */
import React from 'react';
import {
  friendlyName,
  friendlyIcon,
  formatProperties,
  wikidataQid,
  osmUrl,
} from '../lib/oimTagFormatters';

function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

/**
 * Render a feature into an HTML string suitable for mapboxgl.Popup.setHTML().
 * Keeps inline styles so it survives without a stylesheet next to it.
 */
export function renderOimPopupHtml(feature) {
  if (!feature) return '';
  const title = friendlyName(feature);
  const icon = friendlyIcon(feature);
  const rows = formatProperties(feature);
  const wd = wikidataQid(feature);
  const osm = osmUrl(feature);

  const rowsHtml = rows
    .map(
      (r) => `
      <div style="display:flex;justify-content:space-between;gap:12px;padding:3px 0;font-size:11px;line-height:1.35">
        <span style="color:#6b6f76;font-weight:500;letter-spacing:0.02em">${escapeHtml(r.label)}</span>
        <span style="color:#0f1318;font-weight:500;text-align:right">${escapeHtml(r.value)}</span>
      </div>`
    )
    .join('');

  const footerLinks = [];
  if (osm) {
    footerLinks.push(
      `<a href="${escapeHtml(osm)}" target="_blank" rel="noopener noreferrer"
         style="color:#8a6c1a;text-decoration:none;font-size:10px;font-weight:600;letter-spacing:0.04em">
         OSM ↗
       </a>`
    );
  }
  if (wd) {
    footerLinks.push(
      `<a href="https://www.wikidata.org/wiki/${escapeHtml(wd)}" target="_blank" rel="noopener noreferrer"
         style="color:#8a6c1a;text-decoration:none;font-size:10px;font-weight:600;letter-spacing:0.04em">
         Wikidata ${escapeHtml(wd)} ↗
       </a>`
    );
  }

  return `
    <div style="font-family:'DM Sans',-apple-system,sans-serif;min-width:200px;max-width:280px">
      <div style="display:flex;align-items:center;gap:8px;border-bottom:1px solid #ede9df;padding-bottom:6px;margin-bottom:8px">
        ${icon ? `<img src="${escapeHtml(icon)}" alt="" style="width:18px;height:18px;flex:none" />` : ''}
        <div style="font-size:13px;font-weight:600;color:#0f1318">${escapeHtml(title)}</div>
      </div>
      <div>${rowsHtml || '<div style="font-size:11px;color:#8a9099">No tags</div>'}</div>
      ${footerLinks.length ? `<div style="display:flex;gap:10px;border-top:1px solid #ede9df;padding-top:6px;margin-top:8px">${footerLinks.join('')}</div>` : ''}
    </div>
  `;
}

/**
 * React form of the same popup. Useful if a caller mounts it into a portal
 * inside their own popup container (rather than letting Mapbox manage HTML).
 */
export default function OIMFeaturePopup({ feature }) {
  if (!feature) return null;
  const title = friendlyName(feature);
  const icon = friendlyIcon(feature);
  const rows = formatProperties(feature);
  const wd = wikidataQid(feature);
  const osm = osmUrl(feature);

  return (
    <div style={{ fontFamily: "'DM Sans', sans-serif", minWidth: 200, maxWidth: 280 }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        borderBottom: '1px solid #ede9df', paddingBottom: 6, marginBottom: 8,
      }}>
        {icon && <img src={icon} alt="" style={{ width: 18, height: 18, flex: 'none' }} />}
        <div style={{ fontSize: 13, fontWeight: 600, color: '#0f1318' }}>{title}</div>
      </div>
      <div>
        {rows.length === 0 && (
          <div style={{ fontSize: 11, color: '#8a9099' }}>No tags</div>
        )}
        {rows.map((r, i) => (
          <div key={i} style={{
            display: 'flex', justifyContent: 'space-between', gap: 12,
            padding: '3px 0', fontSize: 11, lineHeight: 1.35,
          }}>
            <span style={{ color: '#6b6f76', fontWeight: 500, letterSpacing: '0.02em' }}>
              {r.label}
            </span>
            <span style={{ color: '#0f1318', fontWeight: 500, textAlign: 'right' }}>
              {r.value}
            </span>
          </div>
        ))}
      </div>
      {(osm || wd) && (
        <div style={{
          display: 'flex', gap: 10, borderTop: '1px solid #ede9df',
          paddingTop: 6, marginTop: 8,
        }}>
          {osm && (
            <a href={osm} target="_blank" rel="noopener noreferrer"
               style={{ color: '#8a6c1a', textDecoration: 'none', fontSize: 10, fontWeight: 600, letterSpacing: '0.04em' }}>
              OSM ↗
            </a>
          )}
          {wd && (
            <a href={`https://www.wikidata.org/wiki/${wd}`} target="_blank" rel="noopener noreferrer"
               style={{ color: '#8a6c1a', textDecoration: 'none', fontSize: 10, fontWeight: 600, letterSpacing: '0.04em' }}>
              Wikidata {wd} ↗
            </a>
          )}
        </div>
      )}
    </div>
  );
}
