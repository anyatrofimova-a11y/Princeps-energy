import React, { useState, useCallback } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

function fmtDate(d) {
  try { return new Date(d).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }); }
  catch { return d; }
}

function DeltaArrow({ oldVal, newVal }) {
  if (oldVal == null || newVal == null) return <span className="as-delta as-delta-none">--</span>;
  const diff = newVal - oldVal;
  if (Math.abs(diff) < 0.01) return <span className="as-delta as-delta-none">--</span>;
  const cls = diff > 0 ? "as-delta-up" : "as-delta-down";
  const arrow = diff > 0 ? "\u2191" : "\u2193";
  return <span className={`as-delta ${cls}`}>{arrow} {Math.abs(diff).toFixed(1)}</span>;
}

export default function AssessmentSnapshotPanel({ onClose, embedded }) {
  const { parcelId, agentResult, explain, solarYield, gridContext } = useSite();
  const [snapshots, setSnapshots] = useState([]);
  const [compareIds, setCompareIds] = useState([]);
  const [noteText, setNoteText] = useState("");
  const [noteTarget, setNoteTarget] = useState(null);

  const takeSnapshot = useCallback(() => {
    const snap = {
      id: `snap-${Date.now()}`,
      date: new Date().toISOString(),
      site: explain?.location_name || parcelId || "Unknown",
      score: agentResult?.confidence ?? null,
      verdict: agentResult?.verdict || null,
      metrics: {
        solar_yield: solarYield?.annual_kwh ? Math.round(solarYield.annual_kwh) : null,
        capacity_factor: solarYield?.capacity_factor ?? null,
        grid_capacity_mw: gridContext?.headroom_mw ?? null,
        irradiance: solarYield?.ghi_kwh_m2 ?? null,
      },
      notes: [],
    };
    setSnapshots(prev => [snap, ...prev]);
  }, [parcelId, agentResult, explain, solarYield, gridContext]);

  const toggleCompare = useCallback((id) => {
    setCompareIds(prev => {
      if (prev.includes(id)) return prev.filter(x => x !== id);
      if (prev.length >= 2) return [prev[1], id];
      return [...prev, id];
    });
  }, []);

  const addNote = useCallback((snapId) => {
    if (!noteText.trim()) return;
    setSnapshots(prev => prev.map(s =>
      s.id === snapId ? { ...s, notes: [...s.notes, { text: noteText, date: new Date().toISOString() }] } : s
    ));
    setNoteText("");
    setNoteTarget(null);
  }, [noteText]);

  const snapA = snapshots.find(s => s.id === compareIds[0]);
  const snapB = snapshots.find(s => s.id === compareIds[1]);
  const comparing = snapA && snapB;

  return (
    <div className="as-panel">
      {!embedded && (
        <div className="as-header">
          <span className="as-title">Assessment Snapshots</span>
          <button className="as-close" onClick={onClose}>&times;</button>
        </div>
      )}

      <div className="as-body">
        <button className="as-btn-primary" onClick={takeSnapshot}>Take Snapshot</button>

        {/* Comparison */}
        {comparing && (
          <div className="as-compare-box">
            <div className="as-compare-title">Comparison</div>
            <div className="as-compare-grid">
              <div className="as-compare-header">
                <span>Metric</span>
                <span>{fmtDate(snapA.date)}</span>
                <span>{fmtDate(snapB.date)}</span>
                <span>Delta</span>
              </div>
              {Object.keys(snapA.metrics).map(k => (
                <div key={k} className="as-compare-row">
                  <span className="as-metric-name">{k.replace(/_/g, " ")}</span>
                  <span className="as-metric-val">{snapA.metrics[k] ?? "--"}</span>
                  <span className="as-metric-val">{snapB.metrics[k] ?? "--"}</span>
                  <DeltaArrow oldVal={snapA.metrics[k]} newVal={snapB.metrics[k]} />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Timeline */}
        {snapshots.length > 1 && (
          <div className="as-timeline">
            <div className="as-timeline-line" />
            {snapshots.map((s, i) => (
              <div key={s.id} className={`as-timeline-dot${compareIds.includes(s.id) ? " selected" : ""}`}
                title={fmtDate(s.date)} onClick={() => toggleCompare(s.id)} />
            ))}
          </div>
        )}

        {/* Snapshot list */}
        <div className="as-section-title">
          {snapshots.length} Snapshot{snapshots.length !== 1 ? "s" : ""}
        </div>
        {snapshots.map(s => (
          <div key={s.id} className={`as-snap-card${compareIds.includes(s.id) ? " as-selected" : ""}`}>
            <div className="as-snap-top">
              <span className="as-snap-date">{fmtDate(s.date)}</span>
              <span className="as-snap-site">{s.site}</span>
              {s.verdict && <span className={`as-verdict as-verdict-${(s.verdict||"").toLowerCase()}`}>{s.verdict}</span>}
            </div>
            <div className="as-snap-metrics">
              {Object.entries(s.metrics).filter(([,v]) => v != null).map(([k, v]) => (
                <span key={k} className="as-snap-metric">{k.replace(/_/g, " ")}: {typeof v === "number" ? v.toFixed(1) : v}</span>
              ))}
            </div>
            <div className="as-snap-actions">
              <button className="as-btn-sm" onClick={() => toggleCompare(s.id)}>
                {compareIds.includes(s.id) ? "Deselect" : "Compare"}
              </button>
              <button className="as-btn-sm" onClick={() => setNoteTarget(noteTarget === s.id ? null : s.id)}>
                Add Note
              </button>
            </div>
            {noteTarget === s.id && (
              <div className="as-note-form">
                <input className="as-note-input" value={noteText} onChange={e => setNoteText(e.target.value)}
                  placeholder="Add a note..." onKeyDown={e => e.key === "Enter" && addNote(s.id)} />
                <button className="as-btn-sm" onClick={() => addNote(s.id)}>Save</button>
              </div>
            )}
            {s.notes.length > 0 && (
              <div className="as-notes-list">
                {s.notes.map((n, i) => (
                  <div key={i} className="as-note-item">{n.text}</div>
                ))}
              </div>
            )}
          </div>
        ))}

        {snapshots.length === 0 && (
          <div className="as-empty">No snapshots yet. Run an assessment and take a snapshot to track changes.</div>
        )}
      </div>
    </div>
  );
}
