import React, { useState, useRef, useEffect, useCallback } from "react";

const TOOL_LABELS = {
  run_solar_yield: "Solar simulation",
  get_site_context: "Site analysis",
  create_site_parcel: "Create parcel",
  get_grid_connection: "Grid connection",
  run_financial_analysis: "Financial analysis",
  get_energy_prices: "Energy prices",
  get_demand_forecast: "Demand forecast",
  query_planning_apps: "Planning search",
  search_substations: "Substation search",
  get_grid_live: "Grid live data",
  create_map_layer: "Map layer",
  zoom_to_location: "Map zoom",
  score_candidate_site_prospector: "Site scoring",
  scan_region_for_sites: "Regional scan",
};

function ToolCallCard({ call, onToggle, expanded }) {
  const label = TOOL_LABELS[call.name] || call.name.replace(/_/g, " ");
  const running = call.status === "running";
  return (
    <div className={"cr-tool" + (running ? " cr-tool-run" : "")}>
      <button className="cr-tool-head" onClick={onToggle}>
        <span className="cr-tool-status">
          {running ? <span className="cr-spin" /> : <span className="cr-check">✓</span>}
        </span>
        <span className="cr-tool-label">{label}</span>
        <span className="cr-tool-caret">{expanded ? "▾" : "▸"}</span>
      </button>
      {expanded && call.result && (
        <pre className="cr-tool-body">{typeof call.result === "string" ? call.result : JSON.stringify(call.result, null, 2).slice(0, 600)}</pre>
      )}
    </div>
  );
}

function Message({ msg, onToggleTool, expandedTools }) {
  if (msg.role === "user") {
    return <div className="cr-msg cr-msg-user"><div className="cr-bubble cr-bubble-user">{msg.content}</div></div>;
  }
  return (
    <div className="cr-msg cr-msg-assistant">
      <div className="cr-bubble cr-bubble-assistant">
        {msg.toolCalls && msg.toolCalls.length > 0 && (
          <div className="cr-tools">
            {msg.toolCalls.map((tc, i) => {
              const k = `${msg.timestamp}-${i}`;
              return (
                <ToolCallCard
                  key={k}
                  call={tc}
                  expanded={!!expandedTools[k]}
                  onToggle={() => onToggleTool(k)}
                />
              );
            })}
          </div>
        )}
        {msg.content && <div className="cr-content">{msg.content}</div>}
      </div>
    </div>
  );
}

export default function ChatRail({
  projectId = null,
  parcelId = null,
  onMapLayer = null,
  onZoomTo = null,
  defaultCollapsed = false,
}) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [expandedTools, setExpandedTools] = useState({});
  const endRef = useRef(null);
  const inputRef = useRef(null);
  const abortRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCollapsed(false);
        setTimeout(() => inputRef.current?.focus(), 60);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const toggleTool = useCallback((k) => {
    setExpandedTools((p) => ({ ...p, [k]: !p[k] }));
  }, []);

  const ensureSession = useCallback(async () => {
    if (sessionId) return sessionId;
    try {
      const res = await fetch("/chat/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parcel_id: parcelId || null, project_id: projectId || null }),
      });
      const data = await res.json();
      if (data.session_id) {
        setSessionId(data.session_id);
        return data.session_id;
      }
    } catch (e) {
      console.error("chat session create failed", e);
    }
    return null;
  }, [sessionId, parcelId, projectId]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    setStreaming(true);

    const userMsg = { role: "user", content: text, timestamp: Date.now() };
    const assistantMsg = { role: "assistant", content: "", toolCalls: [], mapLayers: [], timestamp: Date.now() + 1 };
    setMessages((p) => [...p, userMsg, assistantMsg]);

    const sid = await ensureSession();
    if (!sid) {
      setMessages((p) => {
        const copy = [...p];
        copy[copy.length - 1] = { ...copy[copy.length - 1], content: "Failed to create chat session." };
        return copy;
      });
      setStreaming(false);
      return;
    }

    try {
      abortRef.current = new AbortController();
      let res = await fetch(`/chat/${sid}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
        signal: abortRef.current.signal,
      });

      if (res.status === 404) {
        setSessionId(null);
        try {
          const ssr = await fetch("/chat/session", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ parcel_id: parcelId || null, project_id: projectId || null }),
          });
          const ssd = await ssr.json();
          if (ssd.session_id) {
            setSessionId(ssd.session_id);
            res = await fetch(`/chat/${ssd.session_id}/message`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ message: text }),
              signal: abortRef.current.signal,
            });
          }
        } catch { /* falls through */ }
      }

      if (!res.ok) {
        const t = await res.text().catch(() => "");
        setMessages((p) => {
          const c = [...p];
          c[c.length - 1] = { ...c[c.length - 1], content: `[Error ${res.status}: ${t.slice(0, 120)}]` };
          return c;
        });
        setStreaming(false);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          let ev;
          try { ev = JSON.parse(line.slice(6)); } catch { continue; }

          if (ev.type === "text_delta") {
            setMessages((p) => {
              const c = [...p];
              const l = { ...c[c.length - 1] };
              l.content += ev.content;
              c[c.length - 1] = l;
              return c;
            });
          } else if (ev.type === "tool_call") {
            setMessages((p) => {
              const c = [...p];
              const l = { ...c[c.length - 1] };
              l.toolCalls = [...(l.toolCalls || []), { name: ev.name, args: ev.args, status: "running" }];
              c[c.length - 1] = l;
              return c;
            });
          } else if (ev.type === "tool_result") {
            setMessages((p) => {
              const c = [...p];
              const l = { ...c[c.length - 1] };
              const tc = [...(l.toolCalls || [])];
              const idx = tc.findLastIndex((t) => t.name === ev.name && t.status === "running");
              if (idx >= 0) tc[idx] = { ...tc[idx], result: ev.result, status: "done" };
              l.toolCalls = tc;
              c[c.length - 1] = l;
              return c;
            });
          } else if (ev.type === "map_layer") {
            if (onMapLayer) onMapLayer(ev.layer);
          } else if (ev.type === "zoom_to") {
            if (onZoomTo) onZoomTo({ lat: ev.lat, lon: ev.lon, zoom: ev.zoom, label: ev.label });
          } else if (ev.type === "error") {
            setMessages((p) => {
              const c = [...p];
              const l = { ...c[c.length - 1] };
              l.content += `\n\n[Error: ${ev.message}]`;
              c[c.length - 1] = l;
              return c;
            });
          }
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") {
        setMessages((p) => {
          const c = [...p];
          c[c.length - 1] = { ...c[c.length - 1], content: `[Network error: ${e.message}]` };
          return c;
        });
      }
    } finally {
      setStreaming(false);
    }
  }, [input, streaming, ensureSession, parcelId, projectId, onMapLayer, onZoomTo]);

  const onKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  if (collapsed) {
    return (
      <aside className="cr-root cr-collapsed" role="complementary">
        <button className="cr-expand" onClick={() => setCollapsed(false)} title="Open chat (⌘K)">
          ◂
        </button>
        <button className="cr-icon" onClick={() => setCollapsed(false)} title="Chat">💬</button>
        <div className="cr-icon cr-icon-dim" title="History">⊙</div>
        <div className="cr-icon cr-icon-dim" title="Settings">⚙</div>
        <style>{baseCSS}</style>
      </aside>
    );
  }

  return (
    <aside className="cr-root cr-expanded" role="complementary">
      <div className="cr-header">
        <div className="cr-title">
          <span className="cr-dot" />
          Princeps AI
        </div>
        <button className="cr-collapse" onClick={() => setCollapsed(true)} title="Collapse">▸</button>
      </div>

      <div className="cr-list">
        {messages.length === 0 && (
          <div className="cr-empty">
            <div className="cr-empty-title">How can I help?</div>
            <div className="cr-empty-sub">Ask about grid connection, site scoring, demand, planning.</div>
            <div className="cr-hint">⌘K to focus input</div>
          </div>
        )}
        {messages.map((m, i) => (
          <Message key={i} msg={m} onToggleTool={toggleTool} expandedTools={expandedTools} />
        ))}
        <div ref={endRef} />
      </div>

      <div className="cr-input-row">
        <textarea
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKey}
          placeholder={streaming ? "Streaming…" : "Ask anything about this project"}
          disabled={streaming}
          className="cr-input"
          rows={1}
        />
        <button
          className={"cr-send" + (input.trim() && !streaming ? " cr-send-ready" : "")}
          onClick={send}
          disabled={!input.trim() || streaming}
          aria-label="Send"
        >
          {streaming ? "…" : "↑"}
        </button>
      </div>

      <style>{baseCSS}</style>
    </aside>
  );
}

const baseCSS = `
  .cr-root {
    display: flex; flex-direction: column;
    height: 100%;
    background: var(--cds-layer-01);
    border-left: 1px solid var(--cds-border-subtle);
    box-shadow: -4px 0 16px rgba(0,0,0,0.04);
    font-family: "DM Sans", -apple-system, sans-serif;
    transition: width 240ms ease;
    flex-shrink: 0;
  }
  .cr-expanded { width: 360px; }
  .cr-collapsed {
    width: 48px;
    align-items: center;
    padding-top: 12px;
    gap: 14px;
  }
  .cr-expand {
    background: var(--cds-layer-02);
    border: 1px solid var(--cds-border-subtle);
    width: 32px; height: 32px; border-radius: 8px;
    font-family: var(--mono); font-size: 13px;
    color: var(--cds-text-secondary);
    cursor: pointer;
  }
  .cr-expand:hover { border-color: var(--gold); color: var(--gold-dark); }
  .cr-icon {
    font-size: 18px;
    width: 32px; height: 32px;
    display: flex; align-items: center; justify-content: center;
    color: var(--cds-text-secondary);
    cursor: pointer;
    border-radius: 8px;
  }
  .cr-icon:hover { background: rgba(var(--accent-rgb), 0.08); }
  .cr-icon-dim { color: var(--cds-text-helper); cursor: default; }

  .cr-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 12px 16px;
    border-bottom: 1px solid var(--cds-border-subtle);
    flex-shrink: 0;
  }
  .cr-title {
    display: flex; align-items: center; gap: 8px;
    font-size: 13px; font-weight: 700;
    color: var(--ink);
  }
  .cr-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--gold);
    box-shadow: 0 0 0 3px rgba(var(--accent-rgb), 0.25);
  }
  .cr-collapse {
    background: none; border: none;
    color: var(--cds-text-helper);
    cursor: pointer; font-size: 14px;
    padding: 4px 8px; border-radius: 6px;
  }
  .cr-collapse:hover { background: var(--cds-layer-02); color: var(--ink); }

  .cr-list {
    flex: 1; overflow-y: auto;
    padding: 16px;
    display: flex; flex-direction: column; gap: 10px;
  }
  .cr-empty {
    text-align: center;
    padding: 40px 16px;
    color: var(--cds-text-helper);
  }
  .cr-empty-title {
    font-size: 15px; font-weight: 600;
    color: var(--cds-text-secondary);
    margin-bottom: 6px;
  }
  .cr-empty-sub { font-size: 12px; line-height: 1.5; }
  .cr-hint {
    font-family: var(--mono); font-size: 10px;
    margin-top: 16px;
    color: var(--cds-text-helper);
  }

  .cr-msg { display: flex; }
  .cr-msg-user { justify-content: flex-end; }
  .cr-msg-assistant { justify-content: flex-start; }
  .cr-bubble {
    max-width: 92%;
    padding: 10px 12px;
    border-radius: 12px;
    font-size: 13px; line-height: 1.5;
    white-space: pre-wrap; word-wrap: break-word;
  }
  .cr-bubble-user {
    background: rgba(var(--accent-rgb), 0.12);
    color: var(--ink);
    border-bottom-right-radius: 4px;
  }
  .cr-bubble-assistant {
    background: var(--cds-layer-02);
    color: var(--cds-text-primary);
    border: 1px solid var(--cds-border-subtle);
    border-bottom-left-radius: 4px;
  }

  .cr-tools {
    display: flex; flex-direction: column; gap: 4px;
    margin-bottom: 8px;
  }
  .cr-tool {
    background: var(--cds-layer-01);
    border: 1px solid var(--cds-border-subtle);
    border-radius: 8px;
    overflow: hidden;
  }
  .cr-tool-run { border-color: var(--gold); }
  .cr-tool-head {
    display: flex; align-items: center; gap: 8px;
    width: 100%; padding: 6px 10px;
    background: none; border: none; cursor: pointer;
    font-family: inherit; font-size: 12px; font-weight: 600;
    color: var(--cds-text-primary);
    text-align: left;
  }
  .cr-tool-head:hover { background: var(--cds-layer-02); }
  .cr-tool-status { width: 14px; display: flex; justify-content: center; }
  .cr-spin {
    width: 10px; height: 10px;
    border: 2px solid var(--gold);
    border-top-color: transparent;
    border-radius: 50%;
    animation: cr-spin 0.8s linear infinite;
  }
  @keyframes cr-spin { to { transform: rotate(360deg); } }
  .cr-check { color: var(--cds-support-success); font-size: 11px; }
  .cr-tool-label { flex: 1; }
  .cr-tool-caret { color: var(--cds-text-helper); font-size: 10px; }
  .cr-tool-body {
    margin: 0;
    padding: 8px 12px;
    background: var(--cds-layer-02);
    border-top: 1px solid var(--cds-border-subtle);
    font-family: var(--mono); font-size: 10px;
    color: var(--cds-text-secondary);
    white-space: pre-wrap; word-wrap: break-word;
    max-height: 160px; overflow-y: auto;
  }

  .cr-input-row {
    display: flex; gap: 8px;
    padding: 12px;
    border-top: 1px solid var(--cds-border-subtle);
    flex-shrink: 0;
  }
  .cr-input {
    flex: 1;
    resize: none;
    padding: 10px 12px;
    border: 1px solid var(--cds-border-subtle);
    border-radius: 10px;
    font-family: inherit; font-size: 13px;
    color: var(--cds-text-primary);
    background: var(--cds-layer-02);
    outline: none;
    line-height: 1.5;
    min-height: 38px; max-height: 120px;
    transition: border-color 120ms;
  }
  .cr-input:focus {
    border-color: var(--gold);
    box-shadow: 0 0 0 3px rgba(var(--accent-rgb), 0.12);
  }
  .cr-send {
    width: 38px; height: 38px; border-radius: 10px;
    border: none;
    background: var(--cds-layer-03);
    color: var(--cds-text-helper);
    font-family: var(--mono); font-size: 15px; font-weight: 700;
    cursor: not-allowed;
    flex-shrink: 0;
    transition: all 120ms;
  }
  .cr-send-ready {
    background: var(--gold);
    color: #fff;
    cursor: pointer;
  }
  .cr-send-ready:hover { background: var(--gold-dark); }
  .cr-content { white-space: pre-wrap; }
`;
