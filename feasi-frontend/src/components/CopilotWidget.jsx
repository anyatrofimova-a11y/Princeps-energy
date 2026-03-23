import React, { useState, useRef, useEffect, useCallback } from "react";
import { useSite } from "../SiteContext";
import { useWorkspace } from "../contexts/WorkspaceContext";
import api from "../services/api";
import GridCanvas from "./GridCanvas";

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

/** Copilot tab definitions — simplified to just chat */
const COPILOT_TABS = [
  { id: "chat",    label: "AI Copilot",  icon: "M12 2a10 10 0 0 1 10 10 10 10 0 0 1-10 10 10 10 0 0 1-7.07-2.93M2 12h4l2-3 3 6 2-3h3" },
];

function MessageText({ text }) {
  if (!text) return null;
  const parts = text.split("\n").map((line, i) => {
    const rendered = line
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`(.+?)`/g, "<code>$1</code>");
    return (
      <span key={i} dangerouslySetInnerHTML={{
        __html: rendered + (i < text.split("\n").length - 1 ? "<br/>" : ""),
      }} />
    );
  });
  return <>{parts}</>;
}

function fmtMw(v) {
  if (v == null) return "--";
  return v >= 1000 ? `${(v / 1000).toFixed(1)} GW` : `${Number(v).toFixed(1)} MW`;
}

/* ══════════════════════════════════════════════════════════
   NodeInspector — inline panel for clicked substations
   ══════════════════════════════════════════════════════════ */
function NodeInspector({ node, onClose, onZoomTo }) {
  const [detail, setDetail] = useState(null);
  const [queueData, setQueueData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!node?.id) return;
    setLoading(true);
    Promise.all([
      fetch(`/api/grid/substation/${node.id}`).then((r) => (r.ok ? r.json() : null)).catch(() => null),
      fetch(`/api/grid/queue-depth/${node.id}`).then((r) => (r.ok ? r.json() : null)).catch(() => null),
    ]).then(([d, q]) => {
      setDetail(d);
      setQueueData(q);
      setLoading(false);
    });
  }, [node?.id]);

  if (!node) return null;

  const ragColor = { green: "#24a148", amber: "#f1c21b", red: "#da1e28" };

  return (
    <div className="node-inspector">
      <div className="ni-header">
        <div className="ni-header-left">
          <span className="ni-voltage-dot" style={{
            background: node.voltage_kv >= 275 ? "#f44336" : node.voltage_kv >= 132 ? "#ff9800" : node.voltage_kv >= 33 ? "#4caf50" : "#D4A018",
          }} />
          <div>
            <div className="ni-name">{node.name}</div>
            <div className="ni-sub">{node.voltage_kv} kV &middot; {node.dno || "Unknown DNO"}</div>
          </div>
        </div>
        <div className="ni-header-actions">
          {node.lat && (
            <button className="ni-btn" onClick={() => onZoomTo?.({ lat: node.lat, lon: node.lon, zoom: 14 })} title="Zoom to">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" /></svg>
            </button>
          )}
          <button className="ni-btn" onClick={onClose} title="Close">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12" /></svg>
          </button>
        </div>
      </div>

      <div className="ni-body">
        {/* RAG status */}
        <div className="ni-rag-row">
          <div className="ni-rag">
            <span className="ni-rag-dot" style={{ background: ragColor[node.rag_demand] || "#8d8d8d" }} />
            <span className="ni-rag-label">Demand</span>
            <span className="ni-rag-value">{fmtMw(node.demand_headroom_mw)} headroom</span>
          </div>
          <div className="ni-rag">
            <span className="ni-rag-dot" style={{ background: ragColor[node.rag_generation] || "#8d8d8d" }} />
            <span className="ni-rag-label">Generation</span>
            <span className="ni-rag-value">{fmtMw(node.gen_headroom_mw)} headroom</span>
          </div>
        </div>

        {/* Properties */}
        <div className="ni-section">
          <div className="ni-section-title">Properties</div>
          {[
            ["Demand", fmtMw(node.demand_mw)],
            ["Generation", fmtMw(node.generation_mw)],
            ["Transformer", node.transformer_mva ? `${node.transformer_mva} MVA` : "--"],
            ["Fault level", node.fault_level_ka ? `${node.fault_level_ka} kA` : "--"],
            ["Type", node.site_type || "--"],
          ].map(([label, value]) => (
            <div key={label} className="ni-prop">
              <span className="ni-prop-label">{label}</span>
              <span className="ni-prop-value">{value}</span>
            </div>
          ))}
        </div>

        {/* Queue detail from API */}
        {loading && <div className="ni-loading">Loading detail...</div>}
        {detail?.queue_summary && (
          <div className="ni-section">
            <div className="ni-section-title">Connection Queue</div>
            {[
              ["Accepted", detail.queue_summary.accepted],
              ["Queued", detail.queue_summary.queued],
              ["Connected", detail.queue_summary.connected],
              ["Total capacity", detail.queue_summary.total_capacity_mw ? fmtMw(detail.queue_summary.total_capacity_mw) : "--"],
            ].map(([label, value]) => (
              <div key={label} className="ni-prop">
                <span className="ni-prop-label">{label}</span>
                <span className="ni-prop-value">{value ?? "--"}</span>
              </div>
            ))}
          </div>
        )}

        {/* Connected DER */}
        {detail?.connected_der?.length > 0 && (
          <div className="ni-section">
            <div className="ni-section-title">Connected DER ({detail.connected_der.length})</div>
            <div className="ni-der-list">
              {detail.connected_der.slice(0, 8).map((d, i) => (
                <div key={i} className="ni-der-item">
                  <span className="ni-der-tech">{d.technology}</span>
                  <span className="ni-der-cap">{fmtMw(d.capacity_mw)}</span>
                </div>
              ))}
              {detail.connected_der.length > 8 && (
                <div className="ni-der-more">+{detail.connected_der.length - 8} more</div>
              )}
            </div>
          </div>
        )}

        {/* Queue Timeline */}
        {queueData && (
          <div className="ni-section">
            <div className="ni-section-title">Queue Timeline</div>
            <div className="ni-queue-wait">
              <span className={`ni-queue-badge ni-queue-${queueData.risk_level}`}>
                {queueData.estimated_wait_months} months
              </span>
              <span className="ni-queue-risk">{queueData.risk_level} risk</span>
            </div>
            {/* Queued vs Accepted bar */}
            {(queueData.queued_count > 0 || queueData.accepted_count > 0) && (
              <div className="ni-queue-bars">
                <div className="ni-queue-bar-row">
                  <span className="ni-queue-bar-label">Queued</span>
                  <div className="ni-queue-bar-track">
                    <div className="ni-queue-bar-fill ni-queue-bar-queued"
                      style={{ width: `${Math.min(100, (queueData.queued_count / Math.max(1, queueData.queued_count + queueData.accepted_count)) * 100)}%` }} />
                  </div>
                  <span className="ni-queue-bar-val">{queueData.queued_count}</span>
                </div>
                <div className="ni-queue-bar-row">
                  <span className="ni-queue-bar-label">Accepted</span>
                  <div className="ni-queue-bar-track">
                    <div className="ni-queue-bar-fill ni-queue-bar-accepted"
                      style={{ width: `${Math.min(100, (queueData.accepted_count / Math.max(1, queueData.queued_count + queueData.accepted_count)) * 100)}%` }} />
                  </div>
                  <span className="ni-queue-bar-val">{queueData.accepted_count}</span>
                </div>
              </div>
            )}
            <div className="ni-prop">
              <span className="ni-prop-label">Total queued</span>
              <span className="ni-prop-value">{fmtMw(queueData.total_queued_mw)}</span>
            </div>
          </div>
        )}

        {/* Coordinates */}
        {node.lat && (
          <div className="ni-coords">
            {Number(node.lat).toFixed(5)}, {Number(node.lon).toFixed(5)}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Auto-suggestions based on context ── */
function _getFollowUpSuggestions(stage, toolsUsed, hasSite, hasGrid) {
  const suggestions = [];

  // Tool-specific follow-ups — the next logical step
  if (toolsUsed.includes("get_site_context") || toolsUsed.includes("create_site_parcel")) {
    suggestions.push("Run full feasibility assessment on this site");
    suggestions.push("What are the environmental constraints?");
    suggestions.push("Show grid capacity within 10km");
  }
  if (toolsUsed.includes("run_solar_yield")) {
    suggestions.push("What will the grid connection cost?");
    suggestions.push("Calculate IRR at £55/MWh PPA");
    suggestions.push("Generate one-click report PDF");
  }
  if (toolsUsed.includes("get_grid_connection") || toolsUsed.includes("forecast_grid_connection")) {
    suggestions.push("What's the planning approval probability?");
    suggestions.push("Generate G99 application pack");
    suggestions.push("Show me the connection offer timeline");
  }
  if (toolsUsed.includes("run_financial_analysis")) {
    suggestions.push("Compare solar vs BESS vs hybrid on this site");
    suggestions.push("What lease rate is fair for this land?");
    suggestions.push("Generate financial report PDF");
  }
  if (toolsUsed.includes("search_colocation_opportunities")) {
    suggestions.push("Score the top opportunity");
    suggestions.push("Who owns the land near the best site?");
    suggestions.push("What's the BESS revenue stack here?");
  }
  if (toolsUsed.includes("assess_dc_colocation") || toolsUsed.includes("score_dc_site_extended")) {
    suggestions.push("Run 24h physics simulation for this DC");
    suggestions.push("What's the achievable CFE% with 50MW solar?");
    suggestions.push("Compare Waltham Cross vs Slough vs Teesside");
  }

  // Stage-based fallbacks with actionable, specific prompts
  if (suggestions.length === 0) {
    if (!hasSite) {
      suggestions.push("Find the best 50MW solar site near Birmingham");
      suggestions.push("Search for co-location opportunities in the South East");
      suggestions.push("Show me all substations with >30MW headroom");
      suggestions.push("What sites have stalled in REPD that I could acquire?");
    } else if (!hasGrid) {
      suggestions.push("Assess grid connection for this site");
      suggestions.push("What's the planning risk here?");
      suggestions.push("Check for SSSI, AONB, or flood zone constraints");
    } else if (stage === "study") {
      suggestions.push("Generate a one-click feasibility report");
      suggestions.push("Compare all technology options for this site");
      suggestions.push("Predict the connection offer timeline");
      suggestions.push("What would a data centre look like here?");
    } else if (stage === "plan") {
      suggestions.push("Auto-generate the optimal PV layout");
      suggestions.push("Calculate the 16-category loss budget");
      suggestions.push("Generate construction timeline");
    } else if (stage === "act") {
      suggestions.push("Generate G99 application pack");
      suggestions.push("Download XLSX financial model");
      suggestions.push("Create planning application summary");
    } else {
      suggestions.push("Generate full site assessment report");
      suggestions.push("Create construction schedule");
    }
  }

  return suggestions.slice(0, 3);
}

/* ══════════════════════════════════════════════════════════
   CopilotWidget
   ══════════════════════════════════════════════════════════ */
export default function CopilotWidget({ onMapLayer, onZoomTo, onAction }) {
  const site = useSite();
  const ws = useWorkspace();

  const {
    parcelId, workflowStage, explain, solarYield, gridContext,
    gridConnectionOpen, setGridConnectionOpen,
    demandForecastOpen, gridTwinOpen, setGridTwinOpen,
    geeflowData, pickedLocation, chatLayers,
    layers, setLayers,
  } = site;

  const { activeWorkspace, activeIntent, activeViewMode } = ws;

  const [activeTab, setActiveTab] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [expandedTools, setExpandedTools] = useState({});
  const [selectedNode, setSelectedNode] = useState(null);
  const [selectedAsset, setSelectedAsset] = useState(null);
  const [landListings, setLandListings] = useState([]);
  const [landLoading, setLandLoading] = useState(false);

  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const abortRef = useRef(null);
  const inputRef = useRef(null);
  const pendingRef = useRef(null);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-open chat with welcome message on first visit (after 2s delay)
  useEffect(() => {
    const hasSeenWelcome = sessionStorage.getItem("princeps_chat_welcomed");
    if (hasSeenWelcome) return;
    const timer = setTimeout(() => {
      setActiveTab("chat");
      sessionStorage.setItem("princeps_chat_welcomed", "1");
      // Add a welcome message with context-aware suggestions
      setMessages([{
        role: "assistant",
        content: "I'm your energy development copilot. I have access to 50+ AI tools — grid analysis, solar simulation, planning intelligence, financial modelling, and document automation.\n\nDrop a pin on the map, or try one of these:",
        timestamp: Date.now(),
        suggestions: [
          "Find me a 50MW solar site with good grid headroom",
          "Search for co-location opportunities near London",
          "What substations have capacity for a data centre?",
          "Generate a full feasibility report for 52.5N, -1.5W",
        ],
      }]);
    }, 2000);
    return () => clearTimeout(timer);
  }, []);

  // Listen for princeps-chat events
  useEffect(() => {
    const handler = (e) => {
      if (e.detail?.text) {
        pendingRef.current = e.detail.text;
        setInput(e.detail.text);
        setActiveTab("chat");
      }
    };
    window.addEventListener("princeps-chat", handler);
    return () => window.removeEventListener("princeps-chat", handler);
  }, []);

  useEffect(() => {
    if (pendingRef.current && input === pendingRef.current && !streaming) {
      pendingRef.current = null;
      sendMessage();
    }
  }, [input]);

  // Listen for substation clicks from the map
  useEffect(() => {
    const handler = (e) => {
      setSelectedNode(e.detail);
      setActiveTab("node");
    };
    window.addEventListener("princeps-node-click", handler);
    return () => window.removeEventListener("princeps-node-click", handler);
  }, []);

  // Listen for 3D asset clicks
  useEffect(() => {
    const handler = (e) => {
      setSelectedAsset(e.detail);
      setActiveTab("design");
    };
    window.addEventListener("princeps-asset-click", handler);
    return () => window.removeEventListener("princeps-asset-click", handler);
  }, []);

  // Ctrl+J to toggle chat tab
  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "j") {
        e.preventDefault();
        setActiveTab((prev) => (prev === "chat" ? null : "chat"));
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // When Node or Grid tab is active, ensure gridCapacity layer is on
  useEffect(() => {
    if (activeTab === "node" || activeTab === "grid") {
      if (!layers.gridCapacity) {
        setLayers((prev) => ({ ...prev, gridCapacity: true }));
      }
    }
  }, [activeTab]);

  // Fetch land listings when Land tab opens with a location
  useEffect(() => {
    if (activeTab !== "land" || !pickedLocation) return;
    setLandLoading(true);
    fetch(`/api/land/listings?lat=${pickedLocation.lat}&lon=${pickedLocation.lon}&radius_km=10`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => { setLandListings(Array.isArray(data) ? data : []); setLandLoading(false); })
      .catch(() => setLandLoading(false));
  }, [activeTab, pickedLocation?.lat, pickedLocation?.lon]);

  // Tab click handler
  const handleTabClick = useCallback(
    (tabId) => {
      if (tabId === activeTab) {
        setActiveTab(null);
        return;
      }
      setActiveTab(tabId);

      // Non-chat tabs trigger app-level actions
      if (tabId === "grid") {
        setLayers((prev) => ({ ...prev, gridCapacity: true }));
      }
      if (tabId === "node") {
        setLayers((prev) => ({ ...prev, gridCapacity: true }));
      }
      if (tabId === "connect") {
        if (parcelId) {
          setGridConnectionOpen?.(true);
        }
        // Panel will show connection info even without parcelId
      }
      if (tabId === "land") {
        setLayers((prev) => ({ ...prev, landParcels: true }));
      }
    },
    [activeTab, setLayers, setGridConnectionOpen]
  );

  // Build context snapshot
  const buildContext = useCallback(() => {
    const ctx = { workspace: activeWorkspace, view: activeViewMode, stage: workflowStage };
    if (activeIntent) ctx.intent = activeIntent;
    if (parcelId) ctx.parcel_id = parcelId;
    if (pickedLocation) ctx.picked_location = { lat: pickedLocation.lat, lon: pickedLocation.lon };
    const visible = [];
    if (explain) visible.push("site_explanation");
    if (solarYield) visible.push("solar_yield");
    if (gridContext) visible.push("grid_context");
    if (geeflowData) visible.push("satellite_data");
    if (visible.length) ctx.visible_data = visible;
    const panels = [];
    if (gridConnectionOpen) panels.push("grid_connection");
    if (demandForecastOpen) panels.push("demand_forecast");
    if (gridTwinOpen) panels.push("grid_twin");
    if (panels.length) ctx.open_panels = panels;
    if (chatLayers?.length) ctx.map_layers = chatLayers.map((l) => l.name || "unnamed");
    if (selectedNode) ctx.selected_substation = { id: selectedNode.id, name: selectedNode.name, voltage_kv: selectedNode.voltage_kv };
    return ctx;
  }, [
    activeWorkspace, activeViewMode, activeIntent, workflowStage, parcelId,
    pickedLocation, explain, solarYield, gridContext, geeflowData,
    gridConnectionOpen, demandForecastOpen, gridTwinOpen, chatLayers, selectedNode,
  ]);

  const ensureSession = useCallback(async () => {
    if (sessionId) return sessionId;
    try {
      const res = await fetch("/chat/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parcel_id: parcelId || null }),
      });
      const data = await res.json();
      if (data.session_id) { setSessionId(data.session_id); return data.session_id; }
    } catch (err) { console.error("Failed to create chat session:", err); }
    return null;
  }, [sessionId, parcelId]);

  const toggleTool = useCallback((key) => {
    setExpandedTools((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    setStreaming(true);
    setActiveTab("chat");

    setMessages((prev) => [...prev, { role: "user", content: text, timestamp: Date.now() }]);
    setMessages((prev) => [...prev, { role: "assistant", content: "", toolCalls: [], mapLayers: [], timestamp: Date.now() }]);

    const sid = await ensureSession();
    if (!sid) {
      setMessages((prev) => { const c = [...prev]; c[c.length - 1].content = "Failed to create chat session."; return c; });
      setStreaming(false);
      return;
    }

    const context = buildContext();

    try {
      abortRef.current = new AbortController();
      let res = await fetch(`/chat/${sid}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, context }),
        signal: abortRef.current.signal,
      });

      if (res.status === 404) {
        setSessionId(null);
        try {
          const sessRes = await fetch("/chat/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ parcel_id: parcelId || null }) });
          const sessData = await sessRes.json();
          if (sessData.session_id) {
            setSessionId(sessData.session_id);
            res = await fetch(`/chat/${sessData.session_id}/message`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: text, context }), signal: abortRef.current.signal });
          }
        } catch { /* fall through */ }
      }

      if (!res.ok) {
        const errText = await res.text().catch(() => "");
        setMessages((prev) => { const c = [...prev]; c[c.length - 1] = { ...c[c.length - 1], content: `[Error ${res.status}: ${errText.slice(0, 120) || "request failed"}]` }; return c; });
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
            setMessages((prev) => { const c = [...prev]; const l = { ...c[c.length - 1] }; l.content += event.content; c[c.length - 1] = l; return c; });
          } else if (event.type === "tool_call") {
            setMessages((prev) => { const c = [...prev]; const l = { ...c[c.length - 1] }; l.toolCalls = [...l.toolCalls, { name: event.name, args: event.args, status: "running" }]; c[c.length - 1] = l; return c; });
          } else if (event.type === "tool_result") {
            setMessages((prev) => { const c = [...prev]; const l = { ...c[c.length - 1] }; const tc = [...l.toolCalls]; const idx = tc.findLastIndex((t) => t.name === event.name && t.status === "running"); if (idx >= 0) tc[idx] = { ...tc[idx], result: event.result, status: "done" }; l.toolCalls = tc; c[c.length - 1] = l; return c; });
          } else if (event.type === "map_layer") {
            setMessages((prev) => { const c = [...prev]; const l = { ...c[c.length - 1] }; l.mapLayers = [...l.mapLayers, event.layer]; c[c.length - 1] = l; return c; });
            if (onMapLayer) onMapLayer(event.layer);
          } else if (event.type === "zoom_to") {
            if (onZoomTo) onZoomTo({ lat: event.lat, lon: event.lon, zoom: event.zoom, label: event.label });
          } else if (event.type === "action") {
            if (onAction) onAction(event.action, event.payload);
          } else if (event.type === "error") {
            setMessages((prev) => { const c = [...prev]; const l = { ...c[c.length - 1] }; l.content += `\n\n[Error: ${event.message}]`; c[c.length - 1] = l; return c; });
          }
        }
      }
    } catch (err) {
      if (err.name !== "AbortError") {
        console.error("Chat stream error:", err);
        setMessages((prev) => { const c = [...prev]; const l = { ...c[c.length - 1] }; l.content += "\n\n[Connection error]"; c[c.length - 1] = l; return c; });
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;

      // Auto-generate follow-up suggestions based on what just happened
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (!last || last.role !== "assistant" || last.suggestions) return prev;
        const tools = (last.toolCalls || []).map((t) => t.name);
        const suggestions = _getFollowUpSuggestions(workflowStage, tools, !!pickedLocation, !!gridContext);
        if (suggestions.length === 0) return prev;
        const copy = [...prev];
        copy[copy.length - 1] = { ...copy[copy.length - 1], suggestions };
        return copy;
      });
    }
  }, [input, streaming, ensureSession, buildContext, onMapLayer, onZoomTo, onAction, parcelId, workflowStage, pickedLocation, gridContext]);

  const handleFileUpload = useCallback(async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    const sid = await ensureSession();
    if (!sid) return;
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch(`/chat/${sid}/upload`, { method: "POST", body: form });
      const data = await res.json();
      setMessages((prev) => [...prev, { role: "system", content: `Uploaded: **${data.filename}** (${(data.size / 1024).toFixed(1)} KB, ${data.type})`, timestamp: Date.now() }]);
    } catch (err) { console.error("Upload failed:", err); }
  }, [ensureSession]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    if (e.key === "Escape") setActiveTab(null);
  };

  const clearChat = useCallback(() => {
    setMessages([]);
    setSessionId(null);
    setExpandedTools({});
  }, []);

  // Send a prompt from a non-chat tab → opens chat and sends
  const handlePromptFromTab = useCallback((text) => {
    setInput(text);
    setActiveTab("chat");
    pendingRef.current = text;
  }, []);

  const chatOpen = activeTab === "chat";
  const nodeOpen = activeTab === "node";
  const gridOpen = activeTab === "grid";

  return (
    <div className="copilot-dock">
      {/* ── Chat panel ── */}
      {chatOpen && (
        <div className="copilot-chat-panel">
          <div className="copilot-chat-header">
            <div className="copilot-chat-header-left">
              <svg width="24" height="24" viewBox="0 0 48 52" fill="none" style={{ flexShrink: 0 }}>
                <polygon points="2,2 38,2 30,15 10,15" fill="#D4A018"/>
                <rect x="26" y="18" width="18" height="7" fill="#D4A018"/>
                <polygon points="10,18 28,18 36,31 2,31" fill="#D4A018"/>
                <rect x="6" y="38" width="22" height="8" rx="1" fill="#D4A018"/>
              </svg>
              <div>
                <span className="copilot-chat-title">PRINCEPS</span>
                <span className="copilot-chat-subtitle">CO-PILOT</span>
              </div>
            </div>
            <div className="copilot-chat-header-actions">
              <button className="copilot-chat-hdr-btn" onClick={clearChat} title="New conversation">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14" /></svg>
              </button>
              <button className="copilot-chat-hdr-btn" onClick={() => setActiveTab(null)} title="Collapse">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 15 12 9 18 15" /></svg>
              </button>
            </div>
          </div>

          <div className="copilot-chat-messages-wrap">
            <GridCanvas style={{ position: "absolute", inset: 0, zIndex: 0 }} />
            <div className="copilot-chat-messages">
            {messages.length === 0 && (
              <div className="copilot-chat-welcome">
                <div className="copilot-chat-welcome-title">Princeps Copilot</div>
                <div className="copilot-chat-welcome-sub">
                  {workflowStage === "site" && "Find a site to begin your assessment."}
                  {workflowStage === "study" && "Site selected. Ready to run feasibility analysis."}
                  {workflowStage === "connect" && "Assessing grid connection options."}
                  {workflowStage === "plan" && "Design your layout — drag assets onto the map."}
                  {workflowStage === "impact" && "Prepare planning application — check constraints."}
                  {workflowStage === "act" && "Ready to export reports and begin procurement."}
                </div>
                <div className="copilot-chat-suggestions">
                  {(workflowStage === "site" ? [
                    "Find a 50MW solar site near Didcot",
                    "Show me sites with grid headroom >20MW",
                    "Search for available land in Somerset",
                  ] : workflowStage === "study" ? [
                    "Run full feasibility assessment",
                    "What are the planning risks here?",
                    "Check environmental constraints",
                  ] : workflowStage === "connect" ? [
                    "Forecast grid connection timeline",
                    "Show nearby substations with headroom",
                    "Estimate connection cost",
                  ] : workflowStage === "plan" ? [
                    "Calculate energy flow for this layout",
                    "Run revenue stacking analysis",
                    "Open 3D digital twin",
                  ] : workflowStage === "impact" ? [
                    "Run shadow flicker assessment",
                    "Calculate noise contours",
                    "Check viewshed from nearest houses",
                  ] : [
                    "Generate PDF site report",
                    "Create construction schedule",
                    "Estimate construction traffic",
                  ]).map((q) => (
                    <button key={q} className="copilot-chat-chip" onClick={() => { setInput(q); setTimeout(() => { pendingRef.current = q; }, 0); }}>{q}</button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, i) => (
              <div key={i} className={`cpc-msg cpc-msg-${msg.role}`}>
                {msg.role === "assistant" && <div className="cpc-msg-avatar"><img src="/logo-princeps.png" alt="" width="18" height="18" style={{ objectFit: "contain" }} /></div>}
                <div className="cpc-msg-body">
                  {msg.content && <MessageText text={msg.content} />}
                  {msg.suggestions && (
                    <div className="cpc-suggestions">
                      {msg.suggestions.map((s, si) => (
                        <button key={si} className="cpc-suggestion-pill" onClick={() => { setInput(s); pendingRef.current = s; setActiveTab("chat"); }}>
                          {s}
                        </button>
                      ))}
                    </div>
                  )}
                  {msg.toolCalls?.map((tc, j) => {
                    const key = `${i}-${j}`;
                    const expanded = expandedTools[key];
                    return (
                      <div key={j} className={`cpc-tool ${tc.status === "running" ? "running" : ""}`}>
                        <button className="cpc-tool-hdr" onClick={() => toggleTool(key)}>
                          <span className={`cpc-tool-dot ${tc.status}`} />
                          <span className="cpc-tool-name">{TOOL_LABELS[tc.name] || tc.name}</span>
                          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                            style={{ transform: expanded ? "rotate(180deg)" : "none", transition: "transform 0.15s" }}>
                            <polyline points="6 9 12 15 18 9" />
                          </svg>
                        </button>
                        {expanded && tc.result && (
                          <pre className="cpc-tool-result">
                            {typeof tc.result === "string" ? tc.result : JSON.stringify(tc.result, null, 2)}
                          </pre>
                        )}
                      </div>
                    );
                  })}
                  {msg.mapLayers?.map((layer, j) => (
                    <div key={j} className="cpc-map-layer">
                      <span className="cpc-map-dot" style={{ background: layer.color || "var(--cds-interactive)" }} />
                      {layer.name} added to map
                    </div>
                  ))}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
          </div>

          <div className="copilot-chat-input">
            <button className="cpc-attach" onClick={() => fileInputRef.current?.click()} title="Upload file" disabled={streaming}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
              </svg>
            </button>
            <input type="file" ref={fileInputRef} style={{ display: "none" }}
              accept=".csv,.xlsx,.xls,.pdf,.jpg,.jpeg,.png,.tif,.tiff,.webp" onChange={handleFileUpload} />
            <textarea ref={inputRef} className="cpc-input" value={input}
              onChange={(e) => setInput(e.target.value)} onKeyDown={handleKeyDown}
              placeholder="Ask anything about this view..." rows={1} disabled={streaming} autoFocus />
            <button className="cpc-send" onClick={sendMessage} disabled={!input.trim() || streaming} title="Send">
              {streaming ? <div className="cpc-spinner" /> : (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              )}
            </button>
          </div>
        </div>
      )}

      {/* ── Node inspector panel ── */}
      {nodeOpen && (
        <div className="copilot-chat-panel" style={{ height: selectedNode ? "auto" : 120, maxHeight: "50vh" }}>
          <div className="copilot-chat-header">
            <div className="copilot-chat-header-left">
              <span className="copilot-chat-title">Grid Nodes</span>
              <span className="copilot-chat-ctx">
                Click a substation on the map to inspect
              </span>
            </div>
            <button className="copilot-chat-hdr-btn" onClick={() => setActiveTab(null)} title="Close">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 12 15 18 9" /></svg>
            </button>
          </div>
          {selectedNode ? (
            <NodeInspector
              node={selectedNode}
              onClose={() => setSelectedNode(null)}
              onZoomTo={onZoomTo}
            />
          ) : (
            <div className="ni-empty">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--cds-text-helper)" strokeWidth="1.5">
                <circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="3" />
                <line x1="12" y1="2" x2="12" y2="5" /><line x1="12" y1="19" x2="12" y2="22" />
                <line x1="2" y1="12" x2="5" y2="12" /><line x1="19" y1="12" x2="22" y2="12" />
              </svg>
              <span>Substations &amp; lines are now visible on the map.<br />Click any node to inspect.</span>
            </div>
          )}
        </div>
      )}

      {/* ── Grid panel — live grid status + layer controls ── */}
      {gridOpen && (
        <div className="copilot-chat-panel" style={{ height: "auto", maxHeight: "50vh" }}>
          <div className="copilot-chat-header">
            <div className="copilot-chat-header-left">
              <span className="copilot-chat-title">Grid Intelligence</span>
              <span className="copilot-chat-ctx">Live UK grid data + overlays</span>
            </div>
            <button className="copilot-chat-hdr-btn" onClick={() => setActiveTab(null)}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 12 15 18 9" /></svg>
            </button>
          </div>
          <div style={{ padding: "10px 14px", fontSize: 11 }}>
            {/* Layer toggles */}
            <div style={{ fontSize: 9, fontWeight: 700, color: "var(--cds-text-helper)", letterSpacing: "0.06em", marginBottom: 6 }}>MAP LAYERS</div>
            {[
              { id: "gridCapacity", label: "Substations & Capacity", color: "#D4A018" },
              { id: "gridConstraints", label: "Constraint Zones", color: "#f44336" },
              { id: "queueDepth", label: "Queue Depth", color: "#e040fb" },
              { id: "osmPower", label: "Power Lines (OSM)", color: "#B54EB2" },
              { id: "tecPipeline", label: "TEC Pipeline", color: "#0277bd" },
              { id: "repdProjects", label: "REPD Projects", color: "#ff6f00" },
            ].map(layer => (
              <button key={layer.id} onClick={() => setLayers(p => ({ ...p, [layer.id]: !p[layer.id] }))}
                style={{
                  display: "flex", alignItems: "center", gap: 8, width: "100%",
                  padding: "6px 8px", marginBottom: 2, border: "none", borderRadius: 6,
                  background: layers[layer.id] ? "rgba(var(--accent-rgb), 0.08)" : "transparent",
                  cursor: "pointer", textAlign: "left", fontSize: 11,
                  color: layers[layer.id] ? "var(--cds-text-primary)" : "var(--cds-text-secondary)",
                }}>
                <span style={{
                  width: 10, height: 10, borderRadius: 3, flexShrink: 0,
                  background: layers[layer.id] ? layer.color : "transparent",
                  border: `1.5px solid ${layers[layer.id] ? layer.color : "var(--cds-border-strong)"}`,
                }} />
                {layer.label}
                {layers[layer.id] && <span style={{ marginLeft: "auto", fontSize: 9, color: "#16a34a" }}>ON</span>}
              </button>
            ))}

            {/* Quick actions */}
            <div style={{ fontSize: 9, fontWeight: 700, color: "var(--cds-text-helper)", letterSpacing: "0.06em", marginTop: 10, marginBottom: 6 }}>ACTIONS</div>
            {[
              { label: "Find nearest substation", action: () => handlePromptFromTab("Find the nearest substation with available capacity") },
              { label: "Run grid connection study", action: () => handlePromptFromTab("Run a grid connection assessment for this site") },
              { label: "Show queue analysis", action: () => handlePromptFromTab("Show the connection queue depth at nearby substations") },
            ].map((a, i) => (
              <button key={i} onClick={a.action} style={{
                display: "block", width: "100%", padding: "6px 8px", marginBottom: 2,
                border: "1px solid var(--cds-border-subtle)", borderRadius: 6,
                background: "transparent", cursor: "pointer", textAlign: "left",
                fontSize: 10, color: "var(--cds-text-secondary)",
              }}>{a.label}</button>
            ))}
          </div>
        </div>
      )}

      {/* ── Connection tab — grid connection quick actions ── */}
      {activeTab === "connect" && (
        <div className="copilot-chat-panel" style={{ height: "auto", maxHeight: "40vh" }}>
          <div className="copilot-chat-header">
            <div className="copilot-chat-header-left">
              <span className="copilot-chat-title">Grid Connection</span>
              <span className="copilot-chat-ctx">{parcelId ? "Site selected" : "Select a site first"}</span>
            </div>
            <button className="copilot-chat-hdr-btn" onClick={() => setActiveTab(null)}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 12 15 18 9" /></svg>
            </button>
          </div>
          <div style={{ padding: "10px 14px" }}>
            {gridContext?.nearest_substation ? (
              <div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
                  <div style={{ textAlign: "center", padding: 8, background: "var(--cds-layer-02)", borderRadius: 6 }}>
                    <div style={{ fontSize: 7, color: "var(--cds-text-helper)", textTransform: "uppercase", fontWeight: 700 }}>Nearest</div>
                    <div style={{ fontSize: 11, fontWeight: 700, color: "var(--cds-text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {gridContext.nearest_substation.name}
                    </div>
                  </div>
                  <div style={{ textAlign: "center", padding: 8, background: "var(--cds-layer-02)", borderRadius: 6 }}>
                    <div style={{ fontSize: 7, color: "var(--cds-text-helper)", textTransform: "uppercase", fontWeight: 700 }}>Headroom</div>
                    <div style={{ fontSize: 14, fontWeight: 900, color: "#16a34a" }}>
                      {gridContext.nearest_substation.headroom_mw?.toFixed(0) || "—"} MW
                    </div>
                  </div>
                  <div style={{ textAlign: "center", padding: 8, background: "var(--cds-layer-02)", borderRadius: 6 }}>
                    <div style={{ fontSize: 7, color: "var(--cds-text-helper)", textTransform: "uppercase", fontWeight: 700 }}>Distance</div>
                    <div style={{ fontSize: 14, fontWeight: 900, color: "var(--cds-text-primary)" }}>
                      {gridContext.nearest_substation.distance_km?.toFixed(1) || "—"} km
                    </div>
                  </div>
                  <div style={{ textAlign: "center", padding: 8, background: "var(--cds-layer-02)", borderRadius: 6 }}>
                    <div style={{ fontSize: 7, color: "var(--cds-text-helper)", textTransform: "uppercase", fontWeight: 700 }}>Est. Cost</div>
                    <div style={{ fontSize: 14, fontWeight: 900, color: "var(--cds-interactive)" }}>
                      £{((gridContext.nearest_substation.distance_km || 2) * 150 / 1000).toFixed(1)}M
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ fontSize: 11, color: "var(--cds-text-helper)", marginBottom: 8 }}>
                No grid data yet. Select a site or run an analysis.
              </div>
            )}
            <div style={{ fontSize: 9, fontWeight: 700, color: "var(--cds-text-helper)", letterSpacing: "0.06em", marginBottom: 6 }}>ACTIONS</div>
            {[
              { label: "Run Tier 1 grid assessment", action: () => handlePromptFromTab("Run a grid connection assessment for this site") },
              { label: "Run Tier 2 power flow", action: () => handlePromptFromTab("Run a pandapower Tier 2 power flow simulation") },
              { label: "Estimate connection cost", action: () => handlePromptFromTab("Estimate grid connection cost with P10/P50/P90 ranges") },
              { label: "Download Grid Connection PDF", action: () => handlePromptFromTab("Generate a grid connection report PDF") },
            ].map((a, i) => (
              <button key={i} onClick={a.action} style={{
                display: "block", width: "100%", padding: "6px 8px", marginBottom: 2,
                border: "1px solid var(--cds-border-subtle)", borderRadius: 6,
                background: "transparent", cursor: "pointer", textAlign: "left",
                fontSize: 10, color: "var(--cds-text-secondary)",
              }}>{a.label}</button>
            ))}
          </div>
        </div>
      )}

      {/* ── Detail tab — site summary ── */}
      {activeTab === "detail" && (
        <div className="copilot-chat-panel" style={{ height: "auto", maxHeight: "40vh" }}>
          <div className="copilot-chat-header">
            <div className="copilot-chat-header-left">
              <span className="copilot-chat-title">Site Detail</span>
              <span className="copilot-chat-ctx">{parcelId || "No site selected"}</span>
            </div>
            <button className="copilot-chat-hdr-btn" onClick={() => setActiveTab(null)}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 12 15 18 9" /></svg>
            </button>
          </div>
          <div style={{ padding: "10px 14px" }}>
            {solarYield ? (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
                <div style={{ textAlign: "center", padding: 8, background: "var(--cds-layer-02)", borderRadius: 6 }}>
                  <div style={{ fontSize: 7, color: "var(--cds-text-helper)", textTransform: "uppercase", fontWeight: 700 }}>Yield</div>
                  <div style={{ fontSize: 14, fontWeight: 900, color: "var(--cds-interactive)" }}>
                    {solarYield.annual_energy_kwh ? `${(solarYield.annual_energy_kwh / 1000).toFixed(0)} MWh` : "—"}
                  </div>
                </div>
                <div style={{ textAlign: "center", padding: 8, background: "var(--cds-layer-02)", borderRadius: 6 }}>
                  <div style={{ fontSize: 7, color: "var(--cds-text-helper)", textTransform: "uppercase", fontWeight: 700 }}>CF</div>
                  <div style={{ fontSize: 14, fontWeight: 900, color: "var(--cds-text-primary)" }}>
                    {solarYield.capacity_factor_pct?.toFixed(1) || "—"}%
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ fontSize: 11, color: "var(--cds-text-helper)", marginBottom: 8 }}>
                Select a site to see detailed analysis.
              </div>
            )}
            <div style={{ fontSize: 9, fontWeight: 700, color: "var(--cds-text-helper)", letterSpacing: "0.06em", marginBottom: 6 }}>ACTIONS</div>
            {[
              { label: "Run full feasibility study", action: () => handlePromptFromTab("Run a complete feasibility study for this site") },
              { label: "Run financial analysis", action: () => handlePromptFromTab("Calculate IRR and NPV for this project") },
              { label: "Check environmental constraints", action: () => handlePromptFromTab("Check environmental constraints and planning risks") },
              { label: "Download Site Report PDF", action: () => handlePromptFromTab("Generate a site assessment report") },
            ].map((a, i) => (
              <button key={i} onClick={a.action} style={{
                display: "block", width: "100%", padding: "6px 8px", marginBottom: 2,
                border: "1px solid var(--cds-border-subtle)", borderRadius: 6,
                background: "transparent", cursor: "pointer", textAlign: "left",
                fontSize: 10, color: "var(--cds-text-secondary)",
              }}>{a.label}</button>
            ))}
          </div>
        </div>
      )}

      {/* ── Design tab — asset inspector ── */}
      {activeTab === "design" && (
        <div className="copilot-chat-panel" style={{ height: selectedAsset ? "auto" : 160, maxHeight: "40vh" }}>
          <div className="copilot-chat-header">
            <div className="copilot-chat-header-left">
              <span className="copilot-chat-title">Asset Design</span>
              <span className="copilot-chat-ctx">
                {selectedAsset ? selectedAsset.name : "Drag assets from the dock below"}
              </span>
            </div>
            <button className="copilot-chat-hdr-btn" onClick={() => setActiveTab(null)}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 12 15 18 9" /></svg>
            </button>
          </div>
          {selectedAsset ? (
            <div className="ni-body">
              <div className="ni-section">
                <div className="ni-section-title">Component</div>
                {[
                  ["Type", selectedAsset.assetType?.replace(/_/g, " ")],
                  ["Capacity", selectedAsset.mw ? `${selectedAsset.mw} MW` : "--"],
                  ["Height", selectedAsset.height ? `${selectedAsset.height}m` : "--"],
                ].map(([label, value]) => (
                  <div key={label} className="ni-prop">
                    <span className="ni-prop-label">{label}</span>
                    <span className="ni-prop-value">{value}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="ni-empty">
              <span>Drag assets from the dock onto the map to create 3D buildings.<br />Click any asset to edit parameters.</span>
            </div>
          )}
        </div>
      )}

      {/* ── Land tab — property rights & listings ── */}
      {activeTab === "land" && (
        <div className="copilot-chat-panel" style={{ height: 340, maxHeight: "45vh" }}>
          <div className="copilot-chat-header">
            <div className="copilot-chat-header-left">
              <span className="copilot-chat-title">Land &amp; Property</span>
              <span className="copilot-chat-ctx">
                HM Land Registry boundaries on map{pickedLocation ? " + listings nearby" : ""}
              </span>
            </div>
            <button className="copilot-chat-hdr-btn" onClick={() => { setLayers((p) => ({ ...p, landParcels: false })); setActiveTab(null); }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 12 15 18 9" /></svg>
            </button>
          </div>
          <div style={{ padding: "8px 14px", fontSize: 10, color: "var(--cds-text-helper)", borderBottom: "1px solid var(--cds-border-subtle)" }}>
            <span style={{ color: "#2563eb", fontWeight: 600 }}>Blue</span> = Freehold &nbsp;
            <span style={{ color: "#ea580c", fontWeight: 600 }}>Orange</span> = Leasehold &nbsp;
            <span style={{ color: "#16a34a", fontWeight: 600 }}>Green dot</span> = Available (&gt;2ha)
            <br />Zoom to 12+ to see parcel boundaries. Click parcels on map for title details.
          </div>
          <div className="copilot-chat-messages">
            {landLoading && <div className="ni-loading">Loading listings...</div>}
            {!landLoading && !pickedLocation && (
              <div className="ni-empty">
                <span>Select a site location first to see nearby land listings.</span>
              </div>
            )}
            {!landLoading && landListings.length > 0 && (
              <>
                <div style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.4px", color: "var(--cds-text-helper)", padding: "4px 0" }}>
                  {landListings.filter(l => l.type !== "search_link").length} sites + {landListings.filter(l => l.type === "search_link").length} portals
                </div>
                {landListings.map((l) => (
                  <div key={l.id} className={`land-listing-card${l.type === "search_link" ? " land-listing-link" : ""}`}
                    onClick={() => {
                      if (l.type === "search_link" && l.url) {
                        window.open(l.url, "_blank", "noopener");
                      } else {
                        // Zoom to listing and dispatch highlight event
                        onZoomTo?.({ lat: l.lat, lon: l.lon, zoom: 16 });
                        window.dispatchEvent(new CustomEvent("princeps-land-highlight", { detail: { lat: l.lat, lon: l.lon, id: l.id } }));
                      }
                    }}>
                    <div className="land-listing-header">
                      <span className={`land-listing-type land-type-${l.type}`}>
                        {l.type === "search_link" ? l.source : l.type.replace(/_/g, " ")}
                      </span>
                      {l.price_gbp ? (
                        <span className="land-listing-price">£{(l.price_gbp / 1000).toFixed(0)}k</span>
                      ) : (
                        <span className="land-listing-price" style={{ fontSize: 10, color: "var(--cds-interactive)" }}>
                          {l.type === "search_link" ? "Open" : "--"}
                          {l.type === "search_link" && (
                            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginLeft: 3, verticalAlign: "middle" }}>
                              <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3" />
                            </svg>
                          )}
                        </span>
                      )}
                    </div>
                    <div className="land-listing-title">{l.title}</div>
                    <div className="land-listing-meta">
                      {l.area_ha ? `${l.area_ha} ha` : ""}
                      {l.area_ha && l.price_per_ha_gbp ? ` · £${(l.price_per_ha_gbp / 1000).toFixed(0)}k/ha` : ""}
                      {l.source && l.type !== "search_link" ? ` · ${l.source}` : ""}
                      {l.status ? ` · ${l.status}` : ""}
                    </div>
                    {l.description && <div className="land-listing-desc">{l.description}</div>}
                  </div>
                ))}
              </>
            )}
            {!landLoading && pickedLocation && landListings.length === 0 && (
              <div className="ni-empty"><span>No listings found nearby.</span></div>
            )}
          </div>
        </div>
      )}

      {/* ── Tab strip ── */}
      <div className="copilot-tabs">
        {COPILOT_TABS.map((tab) => (
          <button
            key={tab.id}
            className={`copilot-tab${activeTab === tab.id ? " active" : ""}${tab.id === "chat" && streaming ? " streaming" : ""}`}
            onClick={() => handleTabClick(tab.id)}
            title={tab.label}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d={tab.icon} />
            </svg>
            <span>{tab.label}</span>
            {tab.id === "chat" && messages.length > 0 && !chatOpen && (
              <span className="copilot-tab-badge">{messages.length}</span>
            )}
            {tab.id === "node" && selectedNode && !nodeOpen && (
              <span className="copilot-tab-badge">1</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
