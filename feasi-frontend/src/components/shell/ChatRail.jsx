import React, { useState, useRef, useEffect, useCallback, useMemo, lazy, Suspense } from "react";
import { useWorkspace } from "../../contexts/WorkspaceContext";
import { getSuggestions } from "../../lib/chatSuggestions";
import { buildPageContext } from "../../lib/pageContext";
import useMapTime from "../../hooks/useMapTime";

const GridCanvas = lazy(() => import("../GridCanvas"));

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
  // Inline mode: stay expanded inside the parent container, no floating
  // bubble. Used by DocRail on the Intelligence pages so we don't get a
  // tautological second "Ask Princeps" bubble alongside the inline chat.
  inline = false,
}) {
  const [collapsed, setCollapsed] = useState(inline ? false : defaultCollapsed);
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [expandedTools, setExpandedTools] = useState({});
  const endRef = useRef(null);
  const inputRef = useRef(null);
  const abortRef = useRef(null);

  // ── Suggested-prompt context (pills on empty state) ──
  // WorkspaceProvider is mounted at app root, but ChatRail can in theory be
  // rendered before it — guard so we don't crash if that changes later.
  let workspaceCtx = null;
  try { workspaceCtx = useWorkspace(); } catch { workspaceCtx = null; }
  const activeWorkspace = workspaceCtx?.activeWorkspace || "home";
  const activeViewMode  = workspaceCtx?.activeViewMode  || null;

  // lifecycleTab + projectContext + focus arrive via window CustomEvents.
  //   - "princeps-chat-context" { lifecycleTab, projectContext } — page-level
  //   - "princeps-chat-focus"   { type, id, label, data }        — entity click
  // Pathname tracked separately for pushState-driven routes.
  const [chatContext, setChatContext] = useState(() => ({
    lifecycleTab: null,
    projectContext: null,
    project: null,       // full project record (id, name, lat, lon, tech, capacity_mw, stage, dno, tec_mw)
    focus: null,
    pathname: typeof window !== "undefined" ? window.location.pathname : "/",
  }));
  // Ref mirror so the send() closure + path poll always read the latest.
  const chatContextRef = useRef(chatContext);
  useEffect(() => { chatContextRef.current = chatContext; }, [chatContext]);

  // Scrubber state — pathway + asOf flow into page_context so Claude knows
  // which FES scenario/year the user is viewing. useMapTime is safe outside
  // SiteProvider (vanilla external store) so no guard needed.
  const mapTime = useMapTime();

  useEffect(() => {
    const onCtx = (e) => {
      const d = e.detail || {};
      setChatContext((prev) => ({
        ...prev,
        lifecycleTab:   d.lifecycleTab   ?? prev.lifecycleTab,
        projectContext: d.projectContext ?? prev.projectContext,
        project:        d.project        ?? prev.project,
      }));
    };
    const onFocus = (e) => {
      const d = e.detail || {};
      setChatContext((prev) => ({
        ...prev,
        focus: d && (d.type || d.id || d.label) ? {
          type: d.type || "unknown",
          id: d.id ?? null,
          label: d.label ?? null,
          data: d.data ?? null,
          at: Date.now(),
        } : null,
      }));
    };
    const onNav = () => {
      setChatContext((prev) => ({ ...prev, pathname: window.location.pathname, focus: null }));
    };
    window.addEventListener("princeps-chat-context", onCtx);
    window.addEventListener("princeps-chat-focus", onFocus);
    window.addEventListener("popstate", onNav);
    window.addEventListener("hashchange", onNav);
    const pathTick = setInterval(() => {
      if (window.location.pathname !== chatContextRef.current.pathname) {
        setChatContext((p) => ({ ...p, pathname: window.location.pathname, focus: null }));
      }
    }, 1000);
    return () => {
      window.removeEventListener("princeps-chat-context", onCtx);
      window.removeEventListener("princeps-chat-focus", onFocus);
      window.removeEventListener("popstate", onNav);
      window.removeEventListener("hashchange", onNav);
      clearInterval(pathTick);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Build a UI-context dict matching the backend's build_system_prompt
  // shape. Called on every send() so the most recent focus/pathname wins.
  // Starts from the shared buildPageContext collector (URL params, selected
  // asset via window globals, FES pathway, as-of year) and overlays focus
  // + projectContext fields this component owns.
  const buildUiContext = useCallback(() => {
    const ctx = chatContextRef.current;
    const base = buildPageContext({
      workspace: activeWorkspace || null,
      viewMode: activeViewMode || null,
      project: ctx.project || null,
      lifecycleTab: ctx.lifecycleTab || null,
      pathway: mapTime?.fesPathway || null,
      asOf: mapTime?.asOf || null,
    });
    const ui = { ...base, pathname: ctx.pathname };
    if (projectId) ui.project_id = projectId;
    if (parcelId) ui.parcel_id = parcelId;
    if (ctx.projectContext) {
      const pc = ctx.projectContext;
      if (pc.name) ui.project_name = pc.name;
      if (pc.technology || pc.workload) ui.technology = pc.technology || pc.workload;
      if (pc.capacity_mw != null) ui.capacity_mw = pc.capacity_mw;
      if (pc.stage) ui.stage = pc.stage;
      if (pc.verdict) ui.verdict = pc.verdict;
      if (pc.region) ui.region = pc.region;
      if (pc.lat != null && pc.lon != null) ui.picked_location = { lat: pc.lat, lon: pc.lon };
      if (pc.candidate_count != null) ui.candidate_count = pc.candidate_count;
    }
    if (ctx.focus) {
      ui.focus = {
        type: ctx.focus.type,
        id: ctx.focus.id,
        label: ctx.focus.label,
      };
      const f = ctx.focus.data || {};
      if (ctx.focus.type === "alert" && f.title) ui.focused_alert = f.title;
      if (ctx.focus.type === "docket" && f.title) ui.focused_docket = f.title;
      if (ctx.focus.type === "dataset" && f.title) ui.focused_dataset = f.title;
      if (ctx.focus.type === "substation" && f.name) ui.focused_substation = f.name;
      if (ctx.focus.type === "candidate_site" && f.name) ui.focused_site = f.name;
    }

    // BOT-CHC — page_context block. Merged under the `page_context` key so the
    // backend can keep supporting the legacy flat shape while `build_system_prompt`
    // reads the structured block (project.*, lifecycle_tab, pathway, as_of_year).
    ui.page_context = buildPageContext({
      workspace: activeWorkspace,
      viewMode: activeViewMode,
      project: ctx.project,
      lifecycleTab: ctx.lifecycleTab,
      pathway: mapTime?.fesPathway || null,
      asOf: mapTime?.asOf || null,
    });
    return ui;
  }, [activeWorkspace, activeViewMode, projectId, parcelId, mapTime?.fesPathway, mapTime?.asOf]);

  const suggestions = useMemo(
    () => getSuggestions({
      workspace: activeWorkspace,
      viewMode: activeViewMode,
      lifecycleTab: chatContext.lifecycleTab,
      pathname: chatContext.pathname,
      projectContext: chatContext.projectContext || { hasProject: !!projectId },
      focus: chatContext.focus,
    }),
    [activeWorkspace, activeViewMode, chatContext.lifecycleTab, chatContext.pathname, chatContext.projectContext, chatContext.focus, projectId],
  );

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

  const send = useCallback(async (explicitText = null) => {
    // Callers pass either a string (pill-click prompt) or nothing. onClick
    // handlers pass an event — coerce anything non-string back to null so
    // we read the input state instead.
    const override = typeof explicitText === "string" ? explicitText : null;
    const text = (override ?? input).trim();
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
        body: JSON.stringify({ message: text, context: buildUiContext() }),
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
              body: JSON.stringify({ message: text, context: buildUiContext() }),
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

  // Pill click → auto-send. Chosen over "fill + review" because the pills
  // are curated prompts (not freeform user input), demo velocity matters,
  // and the user can still edit before pressing Enter if they type first
  // (pills are gated by an empty-message state). send() accepts an explicit
  // text override so we bypass the input-state round trip.
  const handlePillClick = useCallback((prompt) => {
    if (streaming) return;
    send(prompt);
  }, [streaming, send]);

  // COLLAPSED — small floating bubble bottom-right, like the original
  // CopilotWidget. Click to expand into a floating chat card.
  // Skipped entirely in inline mode (the parent container hosts the chat).
  if (collapsed && !inline) {
    return (
      <>
        <button
          className="cr-pill-collapsed"
          onClick={() => setCollapsed(false)}
          title="Open chat (⌘K)"
          aria-label="Open chat"
        >
          <span className="cr-pill-collapsed-dot" />
          <span className="cr-pill-collapsed-icon">◆</span>
          <span className="cr-pill-collapsed-lbl">Ask Princeps</span>
        </button>
        <style>{baseCSS}</style>
      </>
    );
  }

  return (
    <aside
      className={"cr-root cr-expanded" + (inline ? " cr-inline" : "")}
      role="complementary"
    >
      <div className="cr-header">
        <div className="cr-title">
          <span className="cr-dot" />
          Princeps AI
        </div>
        {!inline && (
          <button className="cr-collapse" onClick={() => setCollapsed(true)} title="Collapse">▸</button>
        )}
      </div>

      <div className="cr-list">
        {messages.length === 0 && (
          <div className="cr-empty">
            <Suspense fallback={null}>
              <GridCanvas className="cr-empty-bg" />
            </Suspense>
            <div className="cr-empty-fg">
              <div className="cr-empty-title">How can I help?</div>
              <div className="cr-empty-sub">
                {suggestions.header || "Ask about grid connection, site scoring, demand, planning."}
              </div>
              {suggestions.pills && suggestions.pills.length > 0 && (
                <div className="cr-pills" role="list">
                  {suggestions.pills.map((p, i) => (
                    <button
                      key={p.label + i}
                      type="button"
                      role="listitem"
                      className="cr-pill"
                      onClick={() => handlePillClick(p.prompt)}
                      disabled={streaming}
                      title={p.prompt}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              )}
              <div className="cr-hint">⌘K to focus input</div>
            </div>
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
  /* EXPANDED — floating card bottom-right, not a full-height rail. */
  .cr-root {
    position: fixed;
    right: 20px; bottom: 52px;
    width: 380px; height: 560px;
    max-height: calc(100vh - 80px);
    display: flex; flex-direction: column;
    background: var(--cds-layer-01);
    border: 1px solid var(--cds-border-subtle);
    border-radius: 14px;
    box-shadow: 0 16px 48px rgba(0,0,0,0.18), 0 4px 12px rgba(0,0,0,0.08);
    font-family: "DM Sans", -apple-system, sans-serif;
    z-index: 990;
    animation: cr-slide-in 180ms ease-out;
    overflow: hidden;
  }
  @keyframes cr-slide-in {
    from { opacity: 0; transform: translateY(12px) scale(0.98); }
    to   { opacity: 1; transform: translateY(0) scale(1); }
  }

  /* INLINE — fill the parent container instead of floating bottom-right.
     Used by IntelligenceShell's right-rail "Chat" tab so the chat lives
     inside the panel rather than on top of it. */
  .cr-root.cr-inline {
    position: relative;
    inset: auto;
    right: auto; bottom: auto;
    width: 100%; height: 100%;
    max-height: none;
    border: none;
    border-radius: 0;
    box-shadow: none;
    z-index: auto;
    animation: none;
    background: transparent;
  }

  /* COLLAPSED — floating pill bubble bottom-right. Class is distinct from
     .cr-bubble (thread message bubble) so fixed positioning never leaks
     into the thread render. */
  .cr-pill-collapsed {
    position: fixed;
    right: 20px; bottom: 52px;
    display: inline-flex; align-items: center; gap: 8px;
    padding: 10px 16px;
    background: var(--ink);
    color: #fff;
    border: none; border-radius: 999px;
    font-family: "DM Sans", -apple-system, sans-serif;
    font-size: 13px; font-weight: 600;
    cursor: pointer;
    box-shadow: 0 8px 24px rgba(0,0,0,0.18), 0 2px 6px rgba(0,0,0,0.12);
    transition: transform 140ms, box-shadow 140ms;
    z-index: 990;
  }
  .cr-pill-collapsed:hover {
    transform: translateY(-2px);
    box-shadow: 0 12px 32px rgba(0,0,0,0.22), 0 3px 8px rgba(0,0,0,0.14);
  }
  .cr-pill-collapsed-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--gold);
    box-shadow: 0 0 0 3px rgba(var(--accent-rgb), 0.35);
    animation: cr-pulse 2.2s ease-in-out infinite;
  }
  @keyframes cr-pulse {
    0%, 100% { box-shadow: 0 0 0 3px rgba(var(--accent-rgb), 0.35); }
    50%      { box-shadow: 0 0 0 7px rgba(var(--accent-rgb), 0.08); }
  }
  .cr-pill-collapsed-icon { font-size: 12px; color: var(--gold); }
  .cr-pill-collapsed-lbl { font-size: 13px; }

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
    position: relative;
    flex: 1;
    display: flex; align-items: flex-start; justify-content: center;
    padding: 40px 20px 0 20px;
    color: var(--cds-text-helper);
    overflow: hidden;
    min-height: 320px;
  }
  .cr-empty-bg {
    position: absolute !important;
    inset: 0; width: 100%; height: 100%;
    opacity: 0.65;
    pointer-events: none;
    z-index: 0;
  }
  .cr-empty-fg {
    position: relative; z-index: 1;
    text-align: center;
    padding-top: 24px;
  }
  .cr-empty-title {
    font-size: 16px; font-weight: 700;
    color: var(--ink);
    margin-bottom: 6px;
    letter-spacing: -0.01em;
  }
  .cr-empty-sub {
    font-size: 12px; line-height: 1.5;
    color: var(--cds-text-secondary);
    max-width: 260px; margin: 0 auto;
  }
  .cr-hint {
    font-family: var(--mono); font-size: 10px;
    margin-top: 18px;
    color: var(--cds-text-helper);
    letter-spacing: 0.04em;
  }

  /* Suggested-prompt pills — shown in empty-state only, per-context content. */
  .cr-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    justify-content: center;
    max-width: 300px;
    margin: 18px auto 0;
  }
  .cr-pill {
    font-family: "DM Sans", -apple-system, sans-serif;
    font-size: 11.5px; font-weight: 500;
    padding: 6px 12px;
    border-radius: 999px;
    border: 1px solid rgba(var(--accent-rgb), 0.45);
    background: rgba(var(--accent-rgb), 0.04);
    color: var(--cds-text-primary);
    cursor: pointer;
    line-height: 1.2;
    white-space: nowrap;
    transition: background 120ms ease, border-color 120ms ease, transform 120ms ease;
  }
  .cr-pill:hover:not(:disabled) {
    background: rgba(201, 166, 75, 0.12);
    border-color: var(--gold);
    transform: translateY(-1px);
  }
  .cr-pill:active:not(:disabled) { transform: translateY(0); }
  .cr-pill:disabled { opacity: 0.5; cursor: not-allowed; }

  .cr-msg { display: flex; }
  .cr-msg-user { justify-content: flex-end; }
  .cr-msg-assistant { justify-content: flex-start; }
  /* Thread bubble — MUST be position: static (default flow) so it sits
     inside .cr-list and scrolls with the thread. Explicit here to prevent
     leaks from any other .cr-bubble rule that might survive a bundle. */
  .cr-bubble {
    position: static;
    right: auto; bottom: auto; left: auto; top: auto;
    max-width: 92%;
    padding: 10px 12px;
    border-radius: 12px;
    font-size: 13px; line-height: 1.5;
    white-space: pre-wrap; word-wrap: break-word;
    box-shadow: none;
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
