import {useState} from 'react';
import {renderManifest} from './ModuleRuntime.jsx';

/**
 * ModuleCanvas — drag-drop visual editor for Slate module manifests.
 *
 * Slate widgets flow in a 12-col grid, so the natural canvas is a
 * vertical reorderable list of widgets with a width slider per row.
 * Pure HTML5 drag-and-drop, no extra deps.
 *
 * Props:
 *   manifest:        {slug, title, target_type, widgets: [{id, kind, w, props}]}
 *   onChange(next):  fired on every mutation
 *   onSave():        triggers a save to /api/workshop/modules
 *   saving:          boolean — disables save button
 */

const WIDGET_KINDS = [
  {kind: 'KPI',           label: 'KPI',            colour: '#F5B731', defaults: {label: 'Connectors live', endpoint: '/api/datasets', value_path: 'count'}},
  {kind: 'ObjectList',    label: 'Object List',    colour: '#3B82F6', defaults: {type: 'Project', limit: 10, columns: ['label', 'stage', 'verdict']}},
  {kind: 'QuiverChart',   label: 'Quiver Chart',   colour: '#8B5CF6', defaults: {type: 'REPDProject', x_field: 'capacity_mw', y_field: 'capacity_mw', limit: 200}},
  {kind: 'NotesFeed',     label: 'Notes Feed',     colour: '#22C55E', defaults: {limit: 6, title: 'Recent notes'}},
  {kind: 'DatasetHealth', label: 'Dataset Health', colour: '#EF4444', defaults: {title: 'Connector health'}},
  {kind: 'Markdown',      label: 'Markdown',       colour: '#94A3B8', defaults: {text: 'Some **markdown** content.'}},
  {kind: 'Map',           label: 'Map',            colour: '#0EA5E9', defaults: {center: 'London'}},
  {kind: 'ObjectCard',    label: 'Object Card',    colour: '#7C3AED', defaults: {title: 'Card', fields: ['label', 'capacity_mw']}},
  {kind: 'ObjectTable',   label: 'Object Table',   colour: '#0F766E', defaults: {columns: ['label']}},
  {kind: 'Chart',         label: 'Inline Chart',   colour: '#D97706', defaults: {series: []}},
  {kind: 'ActionButton',  label: 'Action Button',  colour: '#BE185D', defaults: {label: 'Run', action_id: 'run_feasibility'}},
];

const KIND_BY_NAME = Object.fromEntries(WIDGET_KINDS.map(k => [k.kind, k]));

export default function ModuleCanvas({manifest, onChange, onSave, saving}) {
  const [selectedId, setSelectedId] = useState(null);
  const [showPreview, setShowPreview] = useState(false);
  const [dragSrcIdx, setDragSrcIdx] = useState(null);

  const widgets = manifest?.widgets || [];

  const update = (mutator) => {
    const next = JSON.parse(JSON.stringify(manifest || {}));
    next.widgets = next.widgets || [];
    mutator(next);
    onChange(next);
  };

  const addWidget = (kind) => {
    const k = KIND_BY_NAME[kind];
    if (!k) return;
    const idBase = kind.toLowerCase().slice(0, 4);
    let n = 1;
    while (widgets.some(w => w.id === `${idBase}${n}`)) n++;
    const newId = `${idBase}${n}`;
    update(m => {
      m.widgets.push({id: newId, kind, w: 6, props: {...k.defaults}});
    });
    setSelectedId(newId);
  };

  const removeWidget = (id) => {
    update(m => { m.widgets = m.widgets.filter(w => w.id !== id); });
    if (selectedId === id) setSelectedId(null);
  };

  const setWidth = (id, w) => {
    update(m => {
      const w2 = m.widgets.find(x => x.id === id);
      if (w2) w2.w = Math.max(1, Math.min(12, w));
    });
  };

  const updateProps = (id, propsPatch) => {
    update(m => {
      const w2 = m.widgets.find(x => x.id === id);
      if (w2) w2.props = {...(w2.props || {}), ...propsPatch};
    });
  };

  const reorder = (fromIdx, toIdx) => {
    if (fromIdx === toIdx) return;
    update(m => {
      const moved = m.widgets.splice(fromIdx, 1)[0];
      m.widgets.splice(toIdx, 0, moved);
    });
  };

  const renameWidget = (oldId, newId) => {
    if (!newId.match(/^[a-zA-Z0-9_]+$/)) return;
    if (widgets.some(w => w.id === newId)) return;
    update(m => {
      const w = m.widgets.find(x => x.id === oldId);
      if (w) w.id = newId;
    });
    setSelectedId(newId);
  };

  const selected = widgets.find(w => w.id === selectedId);

  return (
    <div className="mc-canvas-wrap">
      {/* Top bar: title + actions */}
      <header className="mc-canvas-head">
        <input
          type="text"
          className="mc-canvas-title-input"
          value={manifest?.title || ''}
          onChange={(e) => update(m => { m.title = e.target.value; })}
          placeholder="Module title"
        />
        <input
          type="text"
          className="mc-canvas-slug-input"
          value={manifest?.slug || ''}
          onChange={(e) => update(m => { m.slug = e.target.value; })}
          placeholder="slug-with-hyphens"
        />
        <button
          className="mc-canvas-toggle"
          onClick={() => setShowPreview(s => !s)}>
          {showPreview ? '✎ edit' : '👁 preview'}
        </button>
        {onSave && (
          <button className="mc-canvas-save" disabled={saving} onClick={onSave}>
            {saving ? 'saving…' : '✓ save module'}
          </button>
        )}
      </header>

      {showPreview ? (
        <section className="mc-preview-pane">
          {renderManifest(manifest)}
        </section>
      ) : (
        <div className="mc-canvas-body">
          {/* Left: widget palette */}
          <aside className="mc-palette">
            <div className="mc-palette-head">+ ADD WIDGET</div>
            <div className="mc-palette-grid">
              {WIDGET_KINDS.map(k => (
                <button
                  key={k.kind}
                  className="mc-palette-tile"
                  style={{borderLeftColor: k.colour}}
                  onClick={() => addWidget(k.kind)}>
                  <span className="mc-palette-kind">{k.label}</span>
                </button>
              ))}
            </div>
            <div className="mc-palette-help">
              click to add to the canvas →
              drag handles ⋮⋮ to reorder.
            </div>
          </aside>

          {/* Centre: widget list */}
          <section className="mc-canvas-list">
            {widgets.length === 0 && (
              <div className="mc-canvas-empty">No widgets yet — pick one from the palette →</div>
            )}
            {widgets.map((w, i) => {
              const meta = KIND_BY_NAME[w.kind] || {colour: '#94A3B8', label: w.kind};
              const isSel = selectedId === w.id;
              return (
                <div
                  key={w.id}
                  className={`mc-row ${isSel ? 'is-selected' : ''}`}
                  draggable
                  onDragStart={(e) => { setDragSrcIdx(i); e.dataTransfer.effectAllowed = 'move'; }}
                  onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; }}
                  onDrop={(e) => { e.preventDefault(); if (dragSrcIdx != null) reorder(dragSrcIdx, i); setDragSrcIdx(null); }}
                  onClick={() => setSelectedId(w.id)}
                  style={{borderLeftColor: meta.colour}}>
                  <span className="mc-row-handle" title="drag to reorder">⋮⋮</span>
                  <span className="mc-row-kind">{meta.label}</span>
                  <span className="mc-row-id">{w.id}</span>
                  <div className="mc-row-w-block">
                    <input
                      type="range" min={1} max={12} value={w.w || 6}
                      onChange={(e) => setWidth(w.id, parseInt(e.target.value, 10))}
                      onClick={(e) => e.stopPropagation()}
                      className="mc-row-w-slider"
                    />
                    <span className="mc-row-w-value">w={w.w || 6}</span>
                  </div>
                  <button
                    className="mc-row-del"
                    onClick={(e) => { e.stopPropagation(); if (confirm(`Remove ${w.id}?`)) removeWidget(w.id); }}>×</button>
                </div>
              );
            })}
          </section>

          {/* Right: inspector */}
          <aside className="mc-inspector">
            {!selected && (
              <div>
                <div className="mc-inspector-eyebrow">SELECT A WIDGET</div>
                <div style={{fontSize: 12, color: '#5A5F66', marginTop: 8}}>
                  Click any row in the list to edit its props.
                  <br/><br/>
                  <strong>{widgets.length} widgets</strong> in the manifest.
                </div>
              </div>
            )}
            {selected && (
              <ModuleNodeInspector
                key={selected.id}
                widget={selected}
                onRename={(nid) => renameWidget(selected.id, nid)}
                onPropsChange={(patch) => updateProps(selected.id, patch)}
                onDelete={() => removeWidget(selected.id)}
              />
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

function ModuleNodeInspector({widget, onRename, onPropsChange, onDelete}) {
  const meta = KIND_BY_NAME[widget.kind] || {colour: '#94A3B8'};
  const [idDraft, setIdDraft] = useState(widget.id);
  const propEntries = Object.entries(widget.props || {});

  return (
    <div>
      <div className="mc-inspector-eyebrow" style={{borderLeftColor: meta.colour}}>
        {widget.kind}
      </div>
      <div className="mc-insp-row">
        <label>id</label>
        <div style={{display: 'flex', gap: 4}}>
          <input
            type="text" value={idDraft}
            onChange={(e) => setIdDraft(e.target.value)}
            className="mc-insp-input"
          />
          {idDraft !== widget.id && (
            <button className="mc-insp-mini-btn" onClick={() => onRename(idDraft)}>rename</button>
          )}
        </div>
      </div>
      {propEntries.map(([k, v]) => (
        <div key={k} className="mc-insp-row">
          <label>{k}</label>
          {Array.isArray(v) ? (
            <input
              type="text"
              value={v.join(', ')}
              onChange={(e) => onPropsChange({[k]: e.target.value.split(',').map(s => s.trim()).filter(Boolean)})}
              className="mc-insp-input"
            />
          ) : (typeof v === 'string' && v.length > 60) ? (
            <textarea
              value={v}
              onChange={(e) => onPropsChange({[k]: e.target.value})}
              className="mc-insp-input"
              rows={4}
            />
          ) : (
            <input
              type="text"
              value={v == null ? '' : String(v)}
              onChange={(e) => onPropsChange({[k]: e.target.value})}
              className="mc-insp-input"
            />
          )}
        </div>
      ))}
      <button className="mc-insp-del-btn" onClick={onDelete}>delete widget</button>
    </div>
  );
}
