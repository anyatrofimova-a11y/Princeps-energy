import React, { useState, useRef, useEffect, useCallback } from "react";
import { useSite } from "../SiteContext";

/**
 * ChatPanel — Floating conversational AI panel with streaming SSE,
 * tool call display, file upload, and map layer injection.
 */

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
  score_planning_risk: "Planning Risk",
  batch_screen_sites: "Batch Screening",
};

/**
 * ChatSection — The inner chat content (messages + input) without any
 * positioning wrapper. Used by CommandPanel.
 */
export function ChatSection({ onMapLayer, onZoomTo }) {
  const { parcelId } = useSite();
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [expandedTools, setExpandedTools] = useState({});
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const abortRef = useRef(null);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Create session on first open
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

  // Send message via SSE (POST + streaming body reader)
  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    setStreaming(true);

    // Add user message
    const userMsg = { role: "user", content: text, timestamp: Date.now() };
    setMessages(prev => [...prev, userMsg]);

    // Add placeholder for assistant
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

      // Session lost (server restart) — recreate and retry once
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
        } catch { /* fall through to error handling below */ }
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
          try {
            event = JSON.parse(line.slice(6));
          } catch { continue; }

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
            // Inject into map
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
          // "done" — just stop streaming
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
  }, [input, streaming, ensureSession, onMapLayer]);

  // File upload handler
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

      // Add system message about the upload
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
    <div className="chat-section">
      {/* Messages */}
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-welcome">
            <div className="chat-welcome-title">Feasibly AI</div>
            <div className="chat-welcome-sub">
              Ask about solar yield, grid connections, energy pricing, or upload data for analysis.
            </div>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`chat-msg chat-msg-${msg.role}`}>
            <div className="chat-msg-label">
              {msg.role === "user" ? "You" : msg.role === "system" ? "System" : "AI"}
            </div>
            <div className="chat-msg-content">
              {msg.content && <MessageText text={msg.content} />}

              {/* Tool calls */}
              {msg.toolCalls?.map((tc, j) => {
                const key = `${i}-${j}`;
                const expanded = expandedTools[key];
                return (
                  <div key={j} className={`chat-tool ${tc.status === "running" ? "chat-tool-running" : ""}`}>
                    <div className="chat-tool-header" onClick={() => toggleTool(key)}>
                      <span className="chat-tool-icon">{tc.status === "running" ? "\u2699" : "\u2713"}</span>
                      <span className="chat-tool-name">{TOOL_LABELS[tc.name] || tc.name}</span>
                      <span className="chat-tool-expand">{expanded ? "\u25B4" : "\u25BE"}</span>
                    </div>
                    {expanded && tc.result && (
                      <pre className="chat-tool-result">
                        {typeof tc.result === "string" ? tc.result : JSON.stringify(tc.result, null, 2)}
                      </pre>
                    )}
                  </div>
                );
              })}

              {/* Map layer buttons */}
              {msg.mapLayers?.map((layer, j) => (
                <div key={j} className="chat-map-layer">
                  <span className="chat-map-layer-dot" style={{ background: layer.color || "#D4A018" }} />
                  {layer.name} added to map
                </div>
              ))}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input bar */}
      <div className="chat-input-bar">
        <button
          className="chat-attach-btn"
          onClick={() => fileInputRef.current?.click()}
          title="Upload CSV, Excel, or PDF"
          disabled={streaming}
        >
          +
        </button>
        <input
          type="file"
          ref={fileInputRef}
          style={{ display: "none" }}
          accept=".csv,.xlsx,.xls,.pdf"
          onChange={handleFileUpload}
        />
        <textarea
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about energy, solar, grid..."
          rows={1}
          disabled={streaming}
        />
        <button
          className="chat-send-btn"
          onClick={sendMessage}
          disabled={!input.trim() || streaming}
          title="Send"
        >
          {streaming ? "..." : "\u25B6"}
        </button>
      </div>
    </div>
  );
}

/**
 * ChatPanel — Legacy floating wrapper (kept for backwards compat).
 * New layout uses ChatSection directly inside CommandPanel.
 */
export default function ChatPanel({ onMapLayer }) {
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <button className="chat-toggle-btn" onClick={() => setOpen(true)} title="Open AI Chat">
        AI
      </button>
    );
  }
  return (
    <div className="chat-panel">
      <div className="chat-header">
        <span className="chat-header-title">Feasibly AI</span>
        <button className="chat-close-btn" onClick={() => setOpen(false)}>&times;</button>
      </div>
      <ChatSection onMapLayer={onMapLayer} />
    </div>
  );
}


/** Simple markdown-ish text renderer (bold, code, newlines) */
function MessageText({ text }) {
  if (!text) return null;
  // Split into paragraphs, render bold (**text**) and inline code (`code`)
  const parts = text.split("\n").map((line, i) => {
    const rendered = line
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`(.+?)`/g, "<code>$1</code>");
    return <span key={i} dangerouslySetInnerHTML={{ __html: rendered + (i < text.split("\n").length - 1 ? "<br/>" : "") }} />;
  });
  return <>{parts}</>;
}
