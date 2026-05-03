import {useState, memo} from 'react';

/**
 * Kognitwin-pattern AI Assistant with VISIBLE multi-tool calls.
 *
 * Renders a stream of events from the chat SSE channel. Tool calls are not
 * hidden behind a spinner — every one shows up as a card with the tool name,
 * a short summary, and an expander for full args + result. Generalised
 * version of "Query by PI Data Fetcher / Search by EBS Expert" that works
 * for any registered tool (BMRS Fetcher, REPD Search, GridConnection, etc.)
 *
 * Event shapes accepted:
 *   {type:'message',    role:'user'|'assistant', content:string}
 *   {type:'tool_call',  id:string, tool:string, args:object, status:'pending'|'ok'|'error'}
 *   {type:'tool_result',toolCallId:string, result:any, error?:any}
 *   {type:'thinking',   content:string}
 *
 * The component pairs tool_call + tool_result into a single card via
 * matching `id`. Streaming-safe: incremental events just append.
 */
export function ToolCallStream({events}) {
  const cards = pairToolEvents(events);
  return (
    <div className="px-toolcall-stream">
      {cards.map((c) => {
        if (c.type === 'message') return <MessageBubble key={c.key} {...c} />;
        if (c.type === 'thinking') return <ThinkingNote key={c.key} {...c} />;
        return <ToolCallCard key={c.key} {...c} />;
      })}
    </div>
  );
}

function pairToolEvents(events) {
  const out = [];
  const indexById = new Map();
  events.forEach((e, i) => {
    if (e.type === 'message') {
      out.push({type: 'message', key: `m${i}`, role: e.role, content: e.content});
      return;
    }
    if (e.type === 'thinking') {
      out.push({type: 'thinking', key: `t${i}`, content: e.content});
      return;
    }
    if (e.type === 'tool_call') {
      const card = {
        type: 'tool',
        key: `tc${i}`,
        id: e.id,
        tool: e.tool,
        args: e.args ?? {},
        status: e.status ?? 'pending',
        result: undefined,
      };
      out.push(card);
      indexById.set(e.id, card);
      return;
    }
    if (e.type === 'tool_result') {
      const card = indexById.get(e.toolCallId);
      if (card) {
        card.result = e.result;
        card.status = e.error ? 'error' : 'ok';
      }
    }
  });
  return out;
}

function MessageBubble({role, content}) {
  return (
    <div className={`px-msg px-msg-${role}`}>
      <div className="px-msg-role">{role === 'user' ? 'You' : 'Princeps'}</div>
      <div className="px-msg-content">{content}</div>
    </div>
  );
}

function ThinkingNote({content}) {
  return (
    <div className="px-thinking" aria-label="reasoning">
      <span className="px-thinking-label">thinking</span>
      <span className="px-thinking-text">{content}</span>
    </div>
  );
}

const ToolCallCard = memo(function ToolCallCard({tool, args, result, status}) {
  const [open, setOpen] = useState(false);
  const summary = summariseArgs(args);
  return (
    <div className={`px-toolcall px-toolcall-${status}`}>
      <button
        type="button"
        className="px-toolcall-header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="px-toolcall-icon">{statusIcon(status)}</span>
        <span className="px-toolcall-tool">{tool}</span>
        {summary ? <span className="px-toolcall-summary">{summary}</span> : null}
      </button>
      {open ? (
        <div className="px-toolcall-body">
          <div className="px-toolcall-args">
            <div className="px-toolcall-section-label">args</div>
            <pre>{JSON.stringify(args, null, 2)}</pre>
          </div>
          {result !== undefined ? (
            <div className="px-toolcall-result">
              <div className="px-toolcall-section-label">result</div>
              <pre>{typeof result === 'string' ? result : JSON.stringify(result, null, 2)}</pre>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
});

function statusIcon(status) {
  if (status === 'ok') return '●';
  if (status === 'error') return '✕';
  return '◌';
}

function summariseArgs(args) {
  if (!args || typeof args !== 'object') return '';
  const entries = Object.entries(args).slice(0, 3);
  return entries.map(([k, v]) => `${k}=${formatValue(v)}`).join(' · ');
}

function formatValue(v) {
  if (v == null) return '∅';
  if (typeof v === 'string') return v.length > 24 ? `"${v.slice(0, 24)}…"` : `"${v}"`;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  if (Array.isArray(v)) return `[${v.length}]`;
  return '{…}';
}
