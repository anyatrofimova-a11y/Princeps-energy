/**
 * Princeps 3D Twin — ReferenceSourcesPanel
 * ----------------------------------------------------------------------
 * Small dev-facing drawer listing the industry benchmark tools that
 * inspired the Princeps twin. It sits in the layer-rail family of panels
 * and is intended for internal demos and onboarding — NOT a permanent
 * public-facing UI.
 *
 * Content is static: each row links out to the reference tool with a
 * one-line description of what we learned from it and which area of the
 * twin borrows from it. Gold-on-ink styling matches the rest of the
 * twin chrome.
 *
 * Usage:
 *   const [open, setOpen] = useState(false);
 *   <ReferenceSourcesPanel open={open} onClose={() => setOpen(false)} />
 *
 * A toggle lives on the ToolbarLeft under the "help" button's overflow
 * menu — keeps it discoverable for the team without cluttering the
 * shipping UI.
 */

import React, { useEffect } from 'react';

const GOLD = '#F5B731';
const INK = '#0F1318';
const IVORY = '#FBF8F2';

const REFERENCES = [
  {
    name: 'Glint Solar',
    url: 'https://www.glintsolar.ai/',
    area: 'Solar / BESS siting',
    blurb:
      'Polygon-first siting canvas with a zoom-continuous 3D twin. We mirrored the "draw → instant feasibility" loop and the light-mode twin aesthetic.',
    takeaway: 'Canvas-centric UX beats form-centric.',
  },
  {
    name: 'RatedPower',
    url: 'https://ratedpower.com/',
    area: 'Auto-design + GA drawings',
    blurb:
      'Enphase-backed parametric plant designer — outputs GA drawings, BoQ, SLDs straight from a site polygon. Benchmark for export fidelity.',
    takeaway: 'Parametric rules must round-trip to IFC/DXF.',
  },
  {
    name: 'PVcase',
    url: 'https://pvcase.com/',
    area: 'PV layout / shading',
    blurb:
      'Terrain-aware row optimisation plus CAD interop (DWG). Sets the bar for row-break handling on undulating terrain.',
    takeaway: 'Row-break algorithms matter more than fancy shaders.',
  },
  {
    name: 'NVIDIA Omniverse',
    url: 'https://www.nvidia.com/en-us/omniverse/',
    area: 'Industrial digital twins',
    blurb:
      'USD-based real-time collaborative 3D. Inspires our LOD + instancing strategy; out of scope for MVP, relevant for v3.',
    takeaway: 'USD interop is the long-term interchange format.',
  },
  {
    name: 'Cesium ion',
    url: 'https://cesium.com/platform/cesium-ion/',
    area: 'Global terrain + imagery',
    blurb:
      'Terrain tiles, photogrammetric city models, globe camera. We use Cesium for the "zoom out" shell — deck.gl handles the asset-scale.',
    takeaway: 'Geospatial accuracy > cosmetic PBR for our users.',
  },
  {
    name: 'Sketchfab (CC-BY feed)',
    url: 'https://sketchfab.com/search?q=substation&licenses=322a749bcfa841b29dff1e8a1bb74b0b&type=models',
    area: 'Asset library sourcing',
    blurb:
      'Primary source of free-use glTF models for substations, PV modules, wind turbines. Tesla Megapack silhouette comes from this CC-BY feed.',
    takeaway: 'CC-BY is the realistic licence floor for shipped meshes.',
  },
  {
    name: 'Kenney.nl Industrial Kit',
    url: 'https://kenney.nl/assets/industrial-kit',
    area: 'CC0 generics',
    blurb:
      'CC0 containers, gensets, warehouse shells. Fills the "I just need a box that reads as industrial" gap without legal overhead.',
    takeaway: 'Style consistency matters — stick to one CC0 pack.',
  },
  {
    name: 'NREL SAM',
    url: 'https://sam.nrel.gov/',
    area: 'Energy yield modelling',
    blurb:
      'PvWattsv8 + PySAM under the Princeps Solar bot. Not a visual tool but the authoritative yield number behind every twin projection.',
    takeaway: 'Visual twin without audited yield data = vapour.',
  },
];

export default function ReferenceSourcesPanel({ open, onClose }) {
  useEffect(() => {
    if (!open) return undefined;
    function onKey(e) { if (e.key === 'Escape') onClose?.(); }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="princeps-ref-panel" role="complementary" aria-label="Reference sources">
      <div className="princeps-ref-header">
        <div>
          <div className="princeps-ref-eyebrow">INSPIRATION · DEV DRAWER</div>
          <div className="princeps-ref-title">Reference sources</div>
          <div className="princeps-ref-sub">
            Tools benchmarked while building the Princeps 3D Twin.
            Not shipped UI — internal reference only.
          </div>
        </div>
        <button className="princeps-ref-close" onClick={onClose} aria-label="Close">×</button>
      </div>

      <div className="princeps-ref-body">
        {REFERENCES.map((r) => (
          <a
            key={r.name}
            href={r.url}
            target="_blank"
            rel="noopener noreferrer"
            className="princeps-ref-card"
          >
            <div className="princeps-ref-card-head">
              <span className="princeps-ref-name">{r.name}</span>
              <span className="princeps-ref-area">{r.area}</span>
            </div>
            <div className="princeps-ref-blurb">{r.blurb}</div>
            <div className="princeps-ref-take">
              <span className="princeps-ref-take-label">Takeaway</span>
              <span>{r.takeaway}</span>
            </div>
          </a>
        ))}
      </div>

      <style>{`
        .princeps-ref-panel {
          position: absolute;
          left: 56px;
          top: 12px;
          width: 360px;
          max-height: calc(100vh - 120px);
          background: ${IVORY};
          color: ${INK};
          border: 1px solid rgba(15,19,24,0.08);
          border-left: 3px solid ${GOLD};
          border-radius: 8px;
          box-shadow: 0 12px 40px rgba(0,0,0,0.22);
          font-family: "DM Sans", -apple-system, sans-serif;
          z-index: 8;
          display: flex;
          flex-direction: column;
        }
        .princeps-ref-header {
          padding: 16px 18px 12px;
          border-bottom: 1px solid rgba(15,19,24,0.06);
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 12px;
        }
        .princeps-ref-eyebrow {
          color: ${GOLD};
          font-size: 10px;
          font-weight: 700;
          letter-spacing: 0.12em;
        }
        .princeps-ref-title {
          font-size: 16px;
          font-weight: 700;
          margin-top: 4px;
        }
        .princeps-ref-sub {
          font-size: 11.5px;
          color: rgba(15,19,24,0.6);
          margin-top: 6px;
          line-height: 1.5;
        }
        .princeps-ref-close {
          background: transparent;
          border: none;
          font-size: 22px;
          line-height: 1;
          color: rgba(15,19,24,0.5);
          cursor: pointer;
        }
        .princeps-ref-close:hover { color: ${INK}; }
        .princeps-ref-body {
          flex: 1;
          overflow-y: auto;
          padding: 10px 14px 16px;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .princeps-ref-card {
          display: block;
          padding: 10px 12px;
          border: 1px solid rgba(15,19,24,0.08);
          border-radius: 6px;
          text-decoration: none;
          color: ${INK};
          background: #fefcf7;
          transition: all 150ms ease;
        }
        .princeps-ref-card:hover {
          border-color: ${GOLD};
          transform: translateX(2px);
          box-shadow: 0 2px 10px rgba(245,183,49,0.15);
        }
        .princeps-ref-card-head {
          display: flex;
          align-items: baseline;
          justify-content: space-between;
          gap: 10px;
          margin-bottom: 4px;
        }
        .princeps-ref-name {
          font-size: 13px;
          font-weight: 700;
        }
        .princeps-ref-area {
          font-size: 10px;
          color: ${GOLD};
          font-weight: 700;
          letter-spacing: 0.06em;
          text-transform: uppercase;
        }
        .princeps-ref-blurb {
          font-size: 12px;
          color: rgba(15,19,24,0.75);
          line-height: 1.5;
        }
        .princeps-ref-take {
          display: flex;
          align-items: center;
          gap: 6px;
          margin-top: 7px;
          padding-top: 7px;
          border-top: 1px dashed rgba(15,19,24,0.08);
          font-size: 11px;
          color: rgba(15,19,24,0.7);
        }
        .princeps-ref-take-label {
          font-size: 9.5px;
          font-weight: 700;
          letter-spacing: 0.08em;
          color: rgba(15,19,24,0.45);
          text-transform: uppercase;
        }
      `}</style>
    </div>
  );
}
