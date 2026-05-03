import {useEffect, useState, useRef} from 'react';

/**
 * HealthBadge — pill showing the 0-100 asset health score for a RID.
 *
 *  • Renders <A 92>, <D 45>, etc. — colour scaled by grade.
 *  • Hover  → popover with the 5 driver bars + values + last_computed.
 *  • Click  → modal with the full provenance breakdown.
 *
 * Self-contained: no external CSS file (styles inlined / scoped via the
 * `ph-` prefix to avoid colliding with .opx-* classes). Backed by
 * GET /api/asset-health/{rid}.
 */

const GRADE_COLOURS = {
  A: '#22C55E',
  B: '#84CC16',
  C: '#F5B731',
  D: '#F97316',
  F: '#EF4444',
};

const DRIVER_LABELS = {
  data_freshness: 'Data freshness',
  connector_health: 'Connector health',
  verdict: 'Verdict',
  action_error_rate: 'Action error rate',
  audit_volume: 'Audit volume',
};

export default function HealthBadge({rid}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [hover, setHover] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const wrapRef = useRef(null);

  useEffect(() => {
    if (!rid) return;
    let cancelled = false;
    fetch(`/api/asset-health/${encodeURIComponent(rid)}`)
      .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`))
      .then(d => { if (!cancelled) setData(d); })
      .catch(e => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [rid]);

  // Modal close on Esc
  useEffect(() => {
    if (!modalOpen) return;
    const onKey = (e) => { if (e.key === 'Escape') setModalOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [modalOpen]);

  if (error) {
    return (
      <span
        className="ph-badge ph-badge-err"
        title={`Health score unavailable: ${error}`}
        style={badgeStyle('#9CA3AF')}>
        ? —
      </span>
    );
  }

  if (!data) {
    return (
      <span className="ph-badge ph-badge-loading" style={badgeStyle('#D1D5DB')}>
        … —
      </span>
    );
  }

  const colour = GRADE_COLOURS[data.grade] || '#9CA3AF';

  return (
    <span
      ref={wrapRef}
      className="ph-badge-wrap"
      style={{position: 'relative', display: 'inline-block'}}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}>
      <button
        type="button"
        className="ph-badge"
        style={badgeStyle(colour)}
        onClick={() => setModalOpen(true)}
        title={`Asset health ${data.grade} ${data.score} — click for details`}>
        <span style={{fontWeight: 700}}>{data.grade}</span>
        <span style={{opacity: 0.92}}>{data.score}</span>
      </button>

      {hover && !modalOpen && <HoverPopover data={data} />}
      {modalOpen && (
        <ProvenanceModal data={data} onClose={() => setModalOpen(false)} />
      )}
    </span>
  );
}

function badgeStyle(colour) {
  return {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    minWidth: 40,
    padding: '3px 9px',
    borderRadius: 999,
    background: colour,
    color: '#FFFFFF',
    border: 'none',
    cursor: 'pointer',
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: '0.02em',
    fontFamily: '"JetBrains Mono", monospace',
    boxShadow: '0 1px 2px rgba(15,19,24,0.12)',
    lineHeight: 1.2,
    verticalAlign: 'middle',
  };
}

function HoverPopover({data}) {
  return (
    <div
      role="tooltip"
      style={{
        position: 'absolute',
        top: 'calc(100% + 6px)',
        left: 0,
        zIndex: 50,
        minWidth: 260,
        padding: '10px 12px',
        background: '#FFFFFF',
        border: '1px solid #E5E0D2',
        borderRadius: 8,
        boxShadow: '0 6px 16px rgba(15,19,24,0.12)',
        fontFamily: 'inherit',
        color: '#0F1318',
      }}>
      <div style={{fontSize: 11, color: '#5A5F66', marginBottom: 6,
                   textTransform: 'uppercase', letterSpacing: '0.06em'}}>
        Asset Health · {data.grade} {data.score}
      </div>
      <div style={{display: 'flex', flexDirection: 'column', gap: 4}}>
        {(data.drivers || []).map(d => (
          <DriverBar key={d.name} driver={d} />
        ))}
      </div>
      <div style={{fontSize: 10, color: '#8A8F96', marginTop: 6,
                   fontFamily: '"JetBrains Mono", monospace'}}>
        computed {(data.computed_at || '').slice(0, 19)}
      </div>
    </div>
  );
}

function DriverBar({driver}) {
  const pct = Math.max(0, Math.min(100, Number(driver.score) || 0));
  const barColour = pct >= 70 ? '#22C55E' : pct >= 40 ? '#F5B731' : '#EF4444';
  return (
    <div style={{display: 'grid', gridTemplateColumns: '120px 1fr 38px',
                 gap: 6, alignItems: 'center', fontSize: 11}}>
      <span style={{color: '#4A3208'}}>
        {DRIVER_LABELS[driver.name] || driver.name}
        <span style={{color: '#8A8F96', marginLeft: 4}}>
          ({Math.round((driver.weight || 0) * 100)}%)
        </span>
      </span>
      <span style={{display: 'inline-block', height: 6, background: '#F2EDDF',
                    borderRadius: 4, overflow: 'hidden', position: 'relative'}}>
        <span style={{display: 'block', width: `${pct}%`, height: '100%',
                      background: barColour}} />
      </span>
      <span style={{textAlign: 'right',
                    fontFamily: '"JetBrains Mono", monospace',
                    color: '#0F1318'}}>
        {pct}
      </span>
    </div>
  );
}

function ProvenanceModal({data, onClose}) {
  return (
    <>
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, background: 'rgba(15,19,24,0.45)',
          zIndex: 1000,
        }}
      />
      <div
        role="dialog"
        aria-label="Asset health provenance"
        style={{
          position: 'fixed', top: '50%', left: '50%',
          transform: 'translate(-50%, -50%)',
          zIndex: 1001,
          width: 'min(560px, 92vw)',
          maxHeight: '85vh', overflowY: 'auto',
          background: '#FFFFFF',
          borderRadius: 10,
          border: '1px solid #E5E0D2',
          boxShadow: '0 18px 48px rgba(15,19,24,0.32)',
          padding: '18px 20px',
          fontFamily: 'inherit', color: '#0F1318',
        }}>
        <header style={{display: 'flex', alignItems: 'center', gap: 10,
                        marginBottom: 14}}>
          <span style={badgeStyle(GRADE_COLOURS[data.grade] || '#9CA3AF')}>
            <span style={{fontWeight: 700}}>{data.grade}</span>
            <span>{data.score}</span>
          </span>
          <h2 style={{margin: 0, fontSize: 16, fontWeight: 600}}>
            Asset Health Provenance
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="close"
            style={{
              marginLeft: 'auto',
              background: 'transparent', border: 'none',
              fontSize: 22, lineHeight: 1, cursor: 'pointer',
              color: '#5A5F66', padding: '0 4px',
            }}>
            ×
          </button>
        </header>

        <div style={{fontSize: 11, color: '#5A5F66', marginBottom: 14,
                     fontFamily: '"JetBrains Mono", monospace',
                     wordBreak: 'break-all'}}>
          {data.rid}
        </div>

        <table style={{width: '100%', borderCollapse: 'collapse', fontSize: 12}}>
          <thead>
            <tr style={{textAlign: 'left', color: '#5A5F66'}}>
              <th style={{padding: '6px 8px', borderBottom: '1px solid #E5E0D2'}}>Driver</th>
              <th style={{padding: '6px 8px', borderBottom: '1px solid #E5E0D2'}}>Weight</th>
              <th style={{padding: '6px 8px', borderBottom: '1px solid #E5E0D2'}}>Score</th>
              <th style={{padding: '6px 8px', borderBottom: '1px solid #E5E0D2'}}>Value</th>
              <th style={{padding: '6px 8px', borderBottom: '1px solid #E5E0D2'}}>Source</th>
            </tr>
          </thead>
          <tbody>
            {(data.drivers || []).map(d => (
              <tr key={d.name}>
                <td style={{padding: '6px 8px', borderBottom: '1px solid #F4EFE2'}}>
                  {DRIVER_LABELS[d.name] || d.name}
                </td>
                <td style={{padding: '6px 8px', borderBottom: '1px solid #F4EFE2',
                            fontFamily: '"JetBrains Mono", monospace'}}>
                  {Math.round((d.weight || 0) * 100)}%
                </td>
                <td style={{padding: '6px 8px', borderBottom: '1px solid #F4EFE2',
                            fontFamily: '"JetBrains Mono", monospace',
                            fontWeight: 600}}>
                  {d.score}
                </td>
                <td style={{padding: '6px 8px', borderBottom: '1px solid #F4EFE2'}}>
                  {String(d.value)}
                </td>
                <td style={{padding: '6px 8px', borderBottom: '1px solid #F4EFE2',
                            fontFamily: '"JetBrains Mono", monospace',
                            color: '#5A5F66'}}>
                  {String(d.source)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <footer style={{marginTop: 14, fontSize: 11, color: '#8A8F96',
                        fontFamily: '"JetBrains Mono", monospace'}}>
          computed {(data.computed_at || '').slice(0, 19)}
        </footer>
      </div>
    </>
  );
}
