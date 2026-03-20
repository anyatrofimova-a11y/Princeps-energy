import React, { useState, useRef, useEffect, useCallback } from "react";
import { useSite } from "../SiteContext";
import NetworkMeshLanding from "./NetworkMeshLanding";

const TOOL_LABELS = {
  run_solar_yield: "Solar Simulation",
  get_site_context: "Site Analysis",
  create_site_parcel: "Create Parcel",
  get_grid_connection: "Grid Connection",
  run_financial_analysis: "Financial Analysis",
  get_energy_prices: "Energy Prices",
  get_demand_forecast: "Demand Forecast",
  query_planning_apps: "Planning Search",
  run_bipv_analysis: "BIPV Analysis",
  get_inventory_bom: "Bill of Materials",
  search_substations: "Substation Search",
  get_grid_live: "Grid Live Data",
  create_map_layer: "Map Layer",
  zoom_to_location: "Map Zoom",
  process_uploaded_file: "File Analysis",
  query_energy_scenario: "Energy Scenario",
  get_electricity_map: "Electricity Map",
  run_satellite_analysis: "Satellite Analysis",
  score_tender_sites: "Tender Site Scoring",
  run_geoai_analysis: "GeoAI Deep Learning",
  query_legacy_assets: "Legacy Assets",
  assess_asset_lifecycle: "Lifecycle Assessment",
  score_candidate_site_prospector: "Site Scoring",
  scan_region_for_sites: "Regional Scan",
  find_similar_sites: "Similar Sites",
};

const STAGE_PLACEHOLDERS = {
  site: "Search for a site or click the map...",
  study: "Ask about this site's feasibility...",
  plan: "Plan layout, procurement, storage...",
  act: "Export, tender, or take action...",
};

function MessageText({ text }) {
  if (!text) return null;
  const parts = text.split("\n").map((line, i) => {
    const rendered = line
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`(.+?)`/g, "<code>$1</code>");
    return <span key={i} dangerouslySetInnerHTML={{ __html: rendered + (i < text.split("\n").length - 1 ? "<br/>" : "") }} />;
  });
  return <>{parts}</>;
}

export default function CommandBar({ onMapLayer, onZoomTo }) {
  const { parcelId, workflowStage } = useSite();
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [expandedTools, setExpandedTools] = useState({});
  const [panelOpen, setPanelOpen] = useState(false);
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const abortRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-open panel when messages arrive
  useEffect(() => {
    if (messages.length > 0 && !panelOpen) setPanelOpen(true);
  }, [messages.length]);

  // Auto-open panel in welcome state (site stage, no site picked)
  useEffect(() => {
    if (workflowStage === "site" && !parcelId && messages.length === 0) {
      setPanelOpen(true);
    }
  }, []);

  // Listen for messages from NetworkMeshLanding
  const pendingRef = useRef(null);
  useEffect(() => {
    const handler = (e) => {
      if (e.detail?.text) {
        pendingRef.current = e.detail.text;
        setInput(e.detail.text);
      }
    };
    window.addEventListener("princeps-chat", handler);
    return () => window.removeEventListener("princeps-chat", handler);
  }, []);

  // Auto-send when pending message is set via landing
  useEffect(() => {
    if (pendingRef.current && input === pendingRef.current && !streaming) {
      pendingRef.current = null;
      sendMessage();
    }
  }, [input]);

  const ensureSession = useCallback(async () => {
    if (sessionId) return sessionId;
    try {
      const res = await fetch("/chat/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parcel_id: parcelId || null }),
      });
      const data = await res.json();
      if (data.session_id) {
        setSessionId(data.session_id);
        return data.session_id;
      }
    } catch (err) {
      console.error("Failed to create chat session:", err);
    }
    return null;
  }, [sessionId, parcelId]);

  const toggleTool = useCallback((key) => {
    setExpandedTools(prev => ({ ...prev, [key]: !prev[key] }));
  }, []);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    setStreaming(true);
    setPanelOpen(true);

    const userMsg = { role: "user", content: text, timestamp: Date.now() };
    setMessages(prev => [...prev, userMsg]);

    const assistantMsg = {
      role: "assistant",
      content: "",
      toolCalls: [],
      mapLayers: [],
      timestamp: Date.now(),
    };
    setMessages(prev => [...prev, assistantMsg]);

    const sid = await ensureSession();
    if (!sid) {
      setMessages(prev => {
        const copy = [...prev];
        copy[copy.length - 1].content = "Failed to create chat session.";
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
          const sessRes = await fetch("/chat/session", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ parcel_id: parcelId || null }),
          });
          const sessData = await sessRes.json();
          if (sessData.session_id) {
            setSessionId(sessData.session_id);
            res = await fetch(`/chat/${sessData.session_id}/message`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ message: text }),
              signal: abortRef.current.signal,
            });
          }
        } catch { /* fall through */ }
      }

      if (!res.ok) {
        const errText = await res.text().catch(() => "");
        setMessages(prev => {
          const copy = [...prev];
          copy[copy.length - 1] = { ...copy[copy.length - 1], content: `[Error ${res.status}: ${errText.slice(0, 120) || "request failed"}]` };
          return copy;
        });
        setStreaming(false);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          let event;
          try { event = JSON.parse(line.slice(6)); } catch { continue; }

          if (event.type === "text_delta") {
            setMessages(prev => {
              const copy = [...prev];
              const last = { ...copy[copy.length - 1] };
              last.content += event.content;
              copy[copy.length - 1] = last;
              return copy;
            });
          } else if (event.type === "tool_call") {
            setMessages(prev => {
              const copy = [...prev];
              const last = { ...copy[copy.length - 1] };
              last.toolCalls = [...last.toolCalls, { name: event.name, args: event.args, status: "running" }];
              copy[copy.length - 1] = last;
              return copy;
            });
          } else if (event.type === "tool_result") {
            setMessages(prev => {
              const copy = [...prev];
              const last = { ...copy[copy.length - 1] };
              const tc = [...last.toolCalls];
              const idx = tc.findLastIndex(t => t.name === event.name && t.status === "running");
              if (idx >= 0) {
                tc[idx] = { ...tc[idx], result: event.result, status: "done" };
              }
              last.toolCalls = tc;
              copy[copy.length - 1] = last;
              return copy;
            });
          } else if (event.type === "map_layer") {
            setMessages(prev => {
              const copy = [...prev];
              const last = { ...copy[copy.length - 1] };
              last.mapLayers = [...last.mapLayers, event.layer];
              copy[copy.length - 1] = last;
              return copy;
            });
            if (onMapLayer) onMapLayer(event.layer);
          } else if (event.type === "zoom_to") {
            if (onZoomTo) onZoomTo({ lat: event.lat, lon: event.lon, zoom: event.zoom, label: event.label });
          } else if (event.type === "error") {
            setMessages(prev => {
              const copy = [...prev];
              const last = { ...copy[copy.length - 1] };
              last.content += `\n\n[Error: ${event.message}]`;
              copy[copy.length - 1] = last;
              return copy;
            });
          }
        }
      }
    } catch (err) {
      if (err.name !== "AbortError") {
        console.error("Chat stream error:", err);
        setMessages(prev => {
          const copy = [...prev];
          const last = { ...copy[copy.length - 1] };
          last.content += "\n\n[Connection error]";
          copy[copy.length - 1] = last;
          return copy;
        });
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }, [input, streaming, ensureSession, onMapLayer, onZoomTo, parcelId]);

  const handleFileUpload = useCallback(async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";

    const sid = await ensureSession();
    if (!sid) return;

    const form = new FormData();
    form.append("file", file);

    try {
      const res = await fetch(`/chat/${sid}/upload`, {
        method: "POST",
        body: form,
      });
      const data = await res.json();
      setMessages(prev => [
        ...prev,
        {
          role: "system",
          content: `Uploaded: **${data.filename}** (${(data.size / 1024).toFixed(1)} KB, ${data.type})`,
          timestamp: Date.now(),
        },
      ]);
    } catch (err) {
      console.error("Upload failed:", err);
    }
  }, [ensureSession]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <>
      {/* Expandable chat panel */}
      {panelOpen && (
        <div className="chat-panel-v3" style={messages.length === 0 ? { height: "70vh", maxHeight: "none" } : undefined}>
          <div className="chat-panel-header">
            <div className="chat-panel-title">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 2a10 10 0 0 1 10 10 10 10 0 0 1-10 10 10 10 0 0 1-7.07-2.93" />
                <path d="M2 12h4l2-3 3 6 2-3h3" />
              </svg>
              Princeps AI
            </div>
            <button className="chat-panel-close" onClick={() => setPanelOpen(false)}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>
          </div>
          <div className="chat-panel-messages" style={messages.length === 0 ? { position: "relative", overflow: "hidden" } : undefined}>
            {messages.length === 0 && (
              <div style={{ position: "absolute", inset: 0 }}>
                <NetworkMeshLanding
                  onSend={(text) => {
                    pendingRef.current = text;
                    setInput(text);
                  }}
                  onPickMode={() => {}}
                  streaming={streaming}
                />
              </div>
            )}
            {messages.map((msg, i) => (
              <div key={i} className={`chat-msg-v3 chat-msg-v3-${msg.role}`}>
                {msg.role === "user" && (
                  <div className="chat-msg-avatar chat-msg-avatar-user">Y</div>
                )}
                {msg.role === "assistant" && (
                  <div className="chat-msg-avatar chat-msg-avatar-ai">P</div>
                )}
                <div className="chat-msg-body">
                  {msg.content && <MessageText text={msg.content} />}
                  {msg.toolCalls?.map((tc, j) => {
                    const key = `${i}-${j}`;
                    const expanded = expandedTools[key];
                    return (
                      <div key={j} className={`chat-tool-v3 ${tc.status === "running" ? "chat-tool-running" : ""}`}>
                        <button className="chat-tool-header-v3" onClick={() => toggleTool(key)}>
                          <span className={`chat-tool-dot ${tc.status === "running" ? "running" : "done"}`} />
                          <span className="chat-tool-name-v3">{TOOL_LABELS[tc.name] || tc.name}</span>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ transform: expanded ? "rotate(180deg)" : "none", transition: "transform 0.15s" }}>
                            <polyline points="6 9 12 15 18 9" />
                          </svg>
                        </button>
                        {expanded && tc.result && (
                          <pre className="chat-tool-result-v3">
                            {typeof tc.result === "string" ? tc.result : JSON.stringify(tc.result, null, 2)}
                          </pre>
                        )}
                      </div>
                    );
                  })}
                  {msg.mapLayers?.map((layer, j) => (
                    <div key={j} className="chat-map-layer-v3">
                      <span className="chat-map-dot" style={{ background: layer.color || "var(--cds-interactive)" }} />
                      {layer.name} added to map
                    </div>
                  ))}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        </div>
      )}

      {/* Bottom command bar */}
      <div className="command-bar-v2">
        <button
          className={`cb-ai-btn${panelOpen ? " active" : ""}`}
          onClick={() => setPanelOpen(p => !p)}
          title="Toggle AI chat"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2a10 10 0 0 1 10 10 10 10 0 0 1-10 10 10 10 0 0 1-7.07-2.93" />
            <path d="M2 12h4l2-3 3 6 2-3h3" />
          </svg>
          {messages.length > 0 && !panelOpen && <span className="cb-badge">{messages.length}</span>}
        </button>

        <button
          className="cb-attach-btn"
          onClick={() => fileInputRef.current?.click()}
          title="Upload file"
          disabled={streaming}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
          </svg>
        </button>
        <input
          type="file"
          ref={fileInputRef}
          style={{ display: "none" }}
          accept=".csv,.xlsx,.xls,.pdf,.jpg,.jpeg,.png,.tif,.tiff,.webp"
          onChange={handleFileUpload}
        />

        <textarea
          ref={inputRef}
          className="cb-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={STAGE_PLACEHOLDERS[workflowStage] || "Ask Princeps AI..."}
          rows={1}
          disabled={streaming}
        />

        <button
          className="cb-send"
          onClick={sendMessage}
          disabled={!input.trim() || streaming}
          title="Send"
        >
          {streaming ? (
            <div className="cb-spinner" />
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          )}
        </button>
      </div>
    </>
  );
}
