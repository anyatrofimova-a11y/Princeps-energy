/**
 * AgentDispatcher — AI analysis overlay triggered from the globe.
 *
 * When a user clicks a substation/location and requests AI analysis,
 * this component dispatches the request to the backend agent endpoint
 * and streams results in a floating panel on the globe.
 *
 * Props:
 *   intent       — analysis intent (grid_connection, grid_study, demand_forecast, etc.)
 *   context      — context object (substation data, line data, location)
 *   onClose      — callback to close the panel
 *   onFlyTo(loc) — fly camera to result location
 */
import React, { useState, useEffect, useRef } from "react";

const INTENT_LABELS = {
  grid_connection: "Grid Connection Analysis",
  grid_study: "Grid Study",
  demand_forecast: "Demand Forecast",
  feasibility: "Site Feasibility",
  financial: "Financial Analysis",
  planning: "Planning Risk",
  environmental: "Environmental",
  satellite: "Satellite Assessment",
  legacy_compliance: "Compliance Check",
  grid_efficiency: "Grid Efficiency",
  site_prospecting: "Site Prospecting",
};

export default function AgentDispatcher({ intent, context, onClose, onFlyTo }) {
  const [status, setStatus] = useState("connecting"); // connecting, streaming, complete, error
  const [chunks, setChunks] = useState([]);
  const [verdict, setVerdict] = useState(null);
  const [actions, setActions] = useState([]);
  const abortRef = useRef(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    if (!intent || !context) return;
    setStatus("connecting");
    setChunks([]);
    setVerdict(null);
    setActions([]);

    const controller = new AbortController();
    abortRef.current = controller;

    // Build agent request
    const body = {
      intent,
      site: context.substation ? {
        name: context.substation.name,
        lat: context.substation.lat,
        lon: context.substation.lon,
        capacity_mw: context.substation.capacity_mw,
      } : context.line ? {
        name: `${context.line.from} to ${context.line.to}`,
        lat: (context.line.from_coords[1] + context.line.to_coords[1]) / 2,
        lon: (context.line.from_coords[0] + context.line.to_coords[0]) / 2,
      } : context,
    };

    // Stream from agent endpoint
    fetch("/api/agent/analyse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    }).then(async (res) => {
      if (!res.ok) {
        setStatus("error");
        setChunks([{ text: `Error: ${res.status} ${res.statusText}` }]);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      setStatus("streaming");
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6).trim();
          if (payload === "[DONE]") continue;

          try {
            const evt = JSON.parse(payload);
            if (evt.type === "text" || evt.type === "chunk") {
              setChunks(prev => [...prev, { text: evt.content || evt.text }]);
            } else if (evt.type === "verdict") {
              setVerdict(evt);
            } else if (evt.type === "actions") {
              setActions(evt.actions || []);
            } else if (evt.type === "tool_call") {
              setChunks(prev => [...prev, {
                text: `Running: ${evt.name}`,
                tool: true,
              }]);
            }
          } catch {
            // Non-JSON line, treat as text
            if (payload.length > 0) {
              setChunks(prev => [...prev, { text: payload }]);
            }
          }
        }
      }

      setStatus("complete");
    }).catch((err) => {
      if (err.name !== "AbortError") {
        setStatus("error");
        setChunks(prev => [...prev, { text: `Connection error: ${err.message}` }]);
      }
    });

    return () => controller.abort();
  }, [intent, context]);

  // Auto-scroll
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [chunks]);

  const verdictColor = verdict?.verdict === "GO" ? "#52c41a"
    : verdict?.verdict === "CAUTION" ? "#fa8c16"
    : verdict?.verdict === "NO-GO" ? "#f5222d"
    : "#D4A018";

  return (
    <div className="ad-panel">
      {/* Header */}
      <div className="ad-header">
        <div className="ad-header-left">
          <div className="ad-status-dot" data-status={status} />
          <span className="ad-intent">{INTENT_LABELS[intent] || intent}</span>
        </div>
        <button className="ad-close" onClick={onClose}>&times;</button>
      </div>

      {/* Context summary */}
      {context?.substation && (
        <div className="ad-context">
          <span className="ad-context-name">{context.substation.name}</span>
          <span className="ad-context-detail">
            {context.substation.voltage_kv} kV &middot; {Math.round(context.substation.demand_mw)} MW
          </span>
        </div>
      )}
      {context?.line && (
        <div className="ad-context">
          <span className="ad-context-name">{context.line.from} → {context.line.to}</span>
          <span className="ad-context-detail">
            {context.line.voltage_kv} kV &middot; {context.line.loading_pct.toFixed(0)}% loaded
          </span>
        </div>
      )}

      {/* Verdict badge */}
      {verdict && (
        <div className="ad-verdict" style={{ borderColor: verdictColor }}>
          <span className="ad-verdict-badge" style={{ background: verdictColor }}>
            {verdict.verdict}
          </span>
          <span className="ad-verdict-text">{verdict.summary}</span>
          {verdict.confidence && (
            <span className="ad-verdict-conf">Confidence: {verdict.confidence}%</span>
          )}
        </div>
      )}

      {/* Streaming output */}
      <div className="ad-output" ref={scrollRef}>
        {chunks.map((c, i) => (
          <div key={i} className={`ad-chunk ${c.tool ? "ad-chunk-tool" : ""}`}>
            {c.tool && (
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#D4A018" strokeWidth="2" style={{ marginRight: 4, flexShrink: 0 }}>
                <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/>
              </svg>
            )}
            {c.text}
          </div>
        ))}
        {status === "connecting" && (
          <div className="ad-chunk ad-chunk-loading">
            <div className="ad-loading-dots"><span/><span/><span/></div>
            Connecting to AI agent...
          </div>
        )}
        {status === "streaming" && chunks.length > 0 && (
          <div className="ad-cursor" />
        )}
      </div>

      {/* Actions */}
      {actions.length > 0 && (
        <div className="ad-actions">
          {actions.map((a, i) => (
            <button key={i} className="ad-action-btn" onClick={() => {
              if (a.flyTo) onFlyTo?.(a.flyTo);
            }}>
              {a.label}
            </button>
          ))}
        </div>
      )}

      {/* Status bar */}
      <div className="ad-status-bar">
        <span className="ad-status-text">
          {status === "connecting" && "Initialising..."}
          {status === "streaming" && "Analysing..."}
          {status === "complete" && "Analysis complete"}
          {status === "error" && "Error occurred"}
        </span>
      </div>
    </div>
  );
}
