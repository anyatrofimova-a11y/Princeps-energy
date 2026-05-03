/**
 * Pattern (f) — Shift handover panel.
 *
 * Operations cadence in one screen: who's on shift, role, time window,
 * scheduled rounds, handover meetings, role mitigations, operating
 * instructions, and a comments thread. Read-only per row; the comments
 * box accepts new entries.
 *
 * Props:
 *   shift: {operator, role, startsAt, endsAt}
 *   rounds:        [{id, time, location, status}]
 *   handovers:     [{id, time, role, with}]
 *   mitigations:   [{id, label, status}]
 *   instructions:  [{id, label, urgency}]
 *   comments:      [{id, author, postedAt, severity, content, pinned?}]
 *   onAddComment:  (text) => void
 */
export function ShiftHandover({
  shift,
  rounds = [],
  handovers = [],
  mitigations = [],
  instructions = [],
  comments = [],
  onAddComment,
}) {
  return (
    <aside className="px-shift-handover">
      <Section title="My Shift and Role">
        {shift ? (
          <div className="px-shift-card">
            <div className="px-shift-operator">{shift.operator}</div>
            <div className="px-shift-role">{shift.role}</div>
            <div className="px-shift-window">
              {fmtTime(shift.startsAt)} → {fmtTime(shift.endsAt)}
            </div>
          </div>
        ) : <Empty>No active shift.</Empty>}
      </Section>

      <Section title="My Handover Meetings">
        {handovers.length === 0 ? <Empty>No meetings scheduled.</Empty> : (
          <ul className="px-list">
            {handovers.map((h) => (
              <li key={h.id} className="px-handover-row">
                <span className="px-handover-time">{fmtTime(h.time)}</span>
                <span className="px-handover-role">{h.role}</span>
                {h.with ? <span className="px-handover-with">with {h.with}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="My Rounds During My Shift">
        {rounds.length === 0 ? <Empty>No rounds today.</Empty> : (
          <ul className="px-list">
            {rounds.map((r) => (
              <li key={r.id} className={`px-round-row px-status-${r.status}`}>
                <span className="px-round-time">{fmtTime(r.time)}</span>
                <span className="px-round-location">{r.location}</span>
                <span className="px-round-status">{r.status}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Mitigations For My Role">
        {mitigations.length === 0 ? <Empty>None.</Empty> : (
          <ul className="px-list">
            {mitigations.map((m) => (
              <li key={m.id} className={`px-mitigation-row px-status-${m.status}`}>
                <span>{m.label}</span>
                <span className="px-mitigation-status">{m.status}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="My Operating Instructions">
        {instructions.length === 0 ? <Empty>None.</Empty> : (
          <ul className="px-list">
            {instructions.map((i) => (
              <li key={i.id} className={`px-instruction-row px-urgency-${i.urgency}`}>{i.label}</li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Shift Comments">
        <ul className="px-comments">
          {comments.map((c) => (
            <li key={c.id} className={`px-comment px-severity-${c.severity ?? 'info'}`}>
              <header>
                <span className="px-comment-author">{c.author}</span>
                <span className="px-comment-time">{fmtTime(c.postedAt)}</span>
                {c.pinned ? <span className="px-comment-pinned" aria-label="pinned">📌</span> : null}
              </header>
              <p>{c.content}</p>
            </li>
          ))}
        </ul>
        {onAddComment ? <CommentBox onSubmit={onAddComment} /> : null}
      </Section>
    </aside>
  );
}

function Section({title, children}) {
  return (
    <section className="px-shift-section">
      <header>{title}</header>
      <div>{children}</div>
    </section>
  );
}

function Empty({children}) {
  return <div className="px-empty">{children}</div>;
}

function CommentBox({onSubmit}) {
  return (
    <form
      className="px-comment-box"
      onSubmit={(e) => {
        e.preventDefault();
        const t = e.target.elements.text.value.trim();
        if (t) {
          onSubmit(t);
          e.target.reset();
        }
      }}
    >
      <input name="text" placeholder="Add a comment for the next shift…" />
      <button type="submit">Post</button>
    </form>
  );
}

function fmtTime(ts) {
  if (!ts) return '';
  try {
    const d = typeof ts === 'string' ? new Date(ts) : ts;
    return d.toLocaleString(undefined, {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return String(ts);
  }
}
