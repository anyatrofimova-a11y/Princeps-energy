import React, { useState, useMemo, useEffect } from "react";
import api from "../services/api";

/**
 * EnergyFlowPanel — SVG Sankey / node-flow diagram
 * Shows energy flowing through placed assets: Generation → Conversion → Grid/Storage → Revenue
 * Every node is clickable for drill-down.
 */

const NODE_COLORS = {
  solar_array: "#D4A018",
  wind_turbine: "#00b0ff",
  bess: "#16a34a",
  inverter: "#ff9800",
  transformer: "#0891b2",
  substation: "#78909c",
  cable_33kv: "#607d8b",
  meter: "#e91e63",
  grid: "#8B3A3A",
  revenue: "#D4A018",
  curtailed: "#dc2626",
};

function FlowNode({ x, y, w, h, label, sublabel, color, value, unit, onClick, active }) {
  return (
    <g
      onClick={onClick}
      style={{ cursor: onClick ? "pointer" : "default" }}
      className={`flow-node ${active ? "flow-node-active" : ""}`}
    >
      <rect
        x={x} y={y} width={w} height={h} rx={8}
        fill={`${color}11`}
        stroke={active ? color : `${color}44`}
        strokeWidth={active ? 2 : 1.5}
      />
      {/* Icon bar at top */}
      <rect x={x} y={y} width={w} height={6} rx={4} fill={color} opacity={0.6}/>
      {/* Label */}
      <text x={x + w / 2} y={y + 24} textAnchor="middle"
        fill="#0F0E0A" fontSize="11" fontWeight="700" fontFamily="Roboto"
        letterSpacing="0.02em"
      >
        {label}
      </text>
      {/* Value */}
      {value != null && (
        <text x={x + w / 2} y={y + 42} textAnchor="middle"
          fill={color} fontSize="16" fontWeight="900" fontFamily="Roboto"
        >
          {value}{unit && <tspan fontSize="9" fill="#5A5650"> {unit}</tspan>}
        </text>
      )}
      {/* Sub label */}
      {sublabel && (
        <text x={x + w / 2} y={y + 58} textAnchor="middle"
          fill="#8A857D" fontSize="9" fontFamily="Roboto"
        >
          {sublabel}
        </text>
      )}
    </g>
  );
}

function FlowEdge({ x1, y1, x2, y2, color, width = 2, animated = false, label }) {
  const midX = (x1 + x2) / 2;
  const d = `M${x1},${y1} C${midX},${y1} ${midX},${y2} ${x2},${y2}`;
  return (
    <g>
      <path d={d} fill="none" stroke={`${color}33`} strokeWidth={width + 4} />
      <path d={d} fill="none" stroke={color} strokeWidth={width} opacity={0.6}
        strokeDasharray={animated ? "8 4" : "none"}
      >
        {animated && (
          <animate attributeName="stroke-dashoffset" from="24" to="0" dur="1.5s" repeatCount="indefinite" />
        )}
      </path>
      {label && (
        <text x={midX} y={(y1 + y2) / 2 - 6} textAnchor="middle"
          fill="#5A5650" fontSize="8" fontFamily="Roboto" fontWeight="500"
        >
          {label}
        </text>
      )}
    </g>
  );
}

export default function EnergyFlowPanel({ placedAssets = [], solarYield, gridContext, onClose, onNodeClick }) {
  const [activeNode, setActiveNode] = useState(null);
  const [assumptions, setAssumptions] = useState(null);

  // Load CB7 assumptions once
  useEffect(() => {
    api.energy.assumptions().then(a => { if (a) setAssumptions(a); });
  }, []);

  // Compute flow data from placed assets using CB7 assumptions
  const flow = useMemo(() => {
    const solarMW = placedAssets
      .filter(a => a.assetType === "solar_array")
      .reduce((s, a) => s + (a.mw || 0), 0);
    const bessMWh = placedAssets
      .filter(a => a.assetType === "bess")
      .reduce((s, a) => s + (a.mw || 0) * 4, 0); // assume 4hr duration
    const windMW = placedAssets
      .filter(a => a.assetType === "wind_turbine")
      .reduce((s, a) => s + (a.mw || 0), 0);
    const hasBess = bessMWh > 0;
    const hasWind = windMW > 0;
    const hasSolar = solarMW > 0;

    // Use CB7 capacity factors when available, fall back to SAM yield
    const solarCF = assumptions?.renewables?.solar?.capacity_factor || (solarYield?.capacity_factor_pct ? solarYield.capacity_factor_pct / 100 : 0.108);
    const windCF = assumptions?.renewables?.onshore_wind?.capacity_factor || 0.293;
    const cf = solarYield?.capacity_factor_pct || solarCF * 100;

    const annualMWh = solarMW * solarCF * 8760 + windMW * windCF * 8760;
    const curtailed = hasBess ? annualMWh * 0.02 : annualMWh * 0.08;
    const exported = annualMWh - curtailed;

    // Use PPA price from CB7 financial defaults
    const ppaPrice = assumptions?.financial_defaults?.ppa_price_gbp_mwh || 55;
    const revenue = exported * ppaPrice;

    // LCOE from CB7
    const solarLCOE = assumptions?.renewables?.solar?.lcoe_gbp_mwh || 30;
    const windLCOE = assumptions?.renewables?.onshore_wind?.lcoe_gbp_mwh || 36;

    return { solarMW, windMW, bessMWh, hasBess, hasWind, hasSolar, annualMWh, curtailed, exported, revenue, cf, solarLCOE, windLCOE, ppaPrice };
  }, [placedAssets, solarYield, assumptions]);

  const handleNodeClick = (nodeId) => {
    setActiveNode(activeNode === nodeId ? null : nodeId);
    onNodeClick?.(nodeId);
  };

  const hasAssets = placedAssets.length > 0;
  const gridCap = gridContext?.nearest_substation?.headroom_mw;

  return (
    <div className="energy-flow-panel">
      <div className="efp-header">
        <div>
          <div className="efp-title">ENERGY FLOW</div>
          <div className="efp-subtitle">
            {hasAssets ? `${placedAssets.length} components · Live model` : "Place assets to see flows"}
          </div>
        </div>
        {onClose && (
          <button className="efp-close" onClick={onClose}>&times;</button>
        )}
      </div>

      <div className="efp-canvas">
        <svg viewBox="0 0 320 480" width="100%" preserveAspectRatio="xMidYMid meet">
          {hasAssets ? (
            <>
              {/* ── GENERATION TIER ── */}
              {flow.hasSolar && (
                <FlowNode
                  x={10} y={10} w={140} h={68}
                  label="SOLAR ARRAY" sublabel={`CF ${flow.cf.toFixed(1)}%`}
                  value={flow.solarMW.toFixed(0)} unit="MW"
                  color={NODE_COLORS.solar_array}
                  onClick={() => handleNodeClick("solar")}
                  active={activeNode === "solar"}
                />
              )}
              {flow.hasWind && (
                <FlowNode
                  x={170} y={10} w={140} h={68}
                  label="WIND" sublabel="Onshore"
                  value={flow.windMW.toFixed(0)} unit="MW"
                  color={NODE_COLORS.wind_turbine}
                  onClick={() => handleNodeClick("wind")}
                  active={activeNode === "wind"}
                />
              )}

              {/* ── CONVERSION TIER ── */}
              <FlowNode
                x={60} y={120} w={140} h={68}
                label="INVERTER" sublabel="DC → AC conversion"
                value="98.2" unit="% eff"
                color={NODE_COLORS.inverter}
                onClick={() => handleNodeClick("inverter")}
                active={activeNode === "inverter"}
              />

              {/* Edges: Gen → Inverter */}
              {flow.hasSolar && (
                <FlowEdge x1={80} y1={78} x2={130} y2={120} color={NODE_COLORS.solar_array} width={3} animated />
              )}
              {flow.hasWind && (
                <FlowEdge x1={240} y1={78} x2={200} y2={120} color={NODE_COLORS.wind_turbine} width={2} animated />
              )}

              {/* ── STORAGE TIER (conditional) ── */}
              {flow.hasBess && (
                <>
                  <FlowNode
                    x={170} y={230} w={140} h={68}
                    label="BESS" sublabel={`${(flow.bessMWh / 4).toFixed(0)} MW / ${flow.bessMWh.toFixed(0)} MWh`}
                    value={flow.bessMWh.toFixed(0)} unit="MWh"
                    color={NODE_COLORS.bess}
                    onClick={() => handleNodeClick("bess")}
                    active={activeNode === "bess"}
                  />
                  <FlowEdge x1={200} y1={188} x2={240} y2={230} color={NODE_COLORS.bess} width={2} animated
                    label="charge"
                  />
                </>
              )}

              {/* ── GRID CONNECTION TIER ── */}
              <FlowNode
                x={10} y={230} w={140} h={68}
                label="GRID CONNECTION"
                sublabel={gridCap ? `${gridCap.toFixed(0)} MW headroom` : "33kV connection"}
                value={gridContext ? "GO" : "—"} unit=""
                color={gridContext ? "#16a34a" : NODE_COLORS.grid}
                onClick={() => handleNodeClick("grid")}
                active={activeNode === "grid"}
              />
              <FlowEdge x1={130} y1={188} x2={80} y2={230} color={NODE_COLORS.transformer} width={3} animated
                label={`${flow.exported.toFixed(0)} MWh/yr`}
              />

              {/* ── REVENUE TIER ── */}
              <FlowNode
                x={10} y={340} w={140} h={68}
                label="REVENUE"
                sublabel="PPA + Merchant + CfD"
                value={`£${(flow.revenue / 1e6).toFixed(1)}M`} unit="/yr"
                color={NODE_COLORS.revenue}
                onClick={() => handleNodeClick("revenue")}
                active={activeNode === "revenue"}
              />
              <FlowEdge x1={80} y1={298} x2={80} y2={340} color={NODE_COLORS.revenue} width={2} />

              {/* ── CURTAILED ── */}
              <FlowNode
                x={170} y={340} w={140} h={68}
                label="CURTAILED"
                sublabel={flow.hasBess ? "Minimised by BESS" : "No storage — high curtailment"}
                value={flow.curtailed.toFixed(0)} unit="MWh/yr"
                color={NODE_COLORS.curtailed}
                onClick={() => handleNodeClick("curtailed")}
                active={activeNode === "curtailed"}
              />
              <FlowEdge x1={130} y1={264} x2={240} y2={340} color="#dc262644" width={1} label="lost" />

              {/* ── SUMMARY STRIP ── */}
              <rect x={10} y={430} width={300} height={40} rx={8} fill="#0F0E0A" opacity={0.05}/>
              <text x={160} y={446} textAnchor="middle" fill="#0F0E0A" fontSize="9" fontWeight="700" fontFamily="Roboto" letterSpacing="0.08em">
                LCOE ESTIMATE
              </text>
              <text x={160} y={462} textAnchor="middle" fill="#D4A018" fontSize="14" fontWeight="900" fontFamily="Roboto">
                £{(flow.revenue > 0 ? (flow.annualMWh * 25 * 0.6 / flow.revenue * 55).toFixed(1) : "—")}/MWh
                <tspan fill="#5A5650" fontSize="9" fontWeight="400">  over 25 years</tspan>
              </text>
            </>
          ) : (
            /* Empty state */
            <g>
              <rect x={40} y={160} width={240} height={120} rx={16} fill="#0F0E0A" opacity={0.03}
                stroke="#D4A018" strokeWidth={1} strokeDasharray="6 4" opacity={0.3}/>
              <text x={160} y={210} textAnchor="middle" fill="#8A857D" fontSize="12" fontFamily="Roboto" fontWeight="500">
                Drag assets onto the map
              </text>
              <text x={160} y={228} textAnchor="middle" fill="#8A857D" fontSize="10" fontFamily="Roboto" fontWeight="300">
                Energy flows will appear here
              </text>
              <text x={160} y={256} textAnchor="middle" fill="#D4A018" fontSize="20">
                ↓
              </text>
            </g>
          )}
        </svg>
      </div>

      {/* Active node detail drawer */}
      {activeNode && (
        <div className="efp-detail">
          <div className="efp-detail-header">
            <span className="efp-detail-title">{activeNode.toUpperCase()} DETAIL</span>
            <button className="efp-detail-close" onClick={() => setActiveNode(null)}>×</button>
          </div>
          <div className="efp-detail-body">
            {activeNode === "solar" && (
              <div className="efp-detail-rows">
                <div className="efp-detail-row"><span>Capacity</span><span>{flow.solarMW.toFixed(0)} MW</span></div>
                <div className="efp-detail-row"><span>Capacity Factor</span><span>{flow.cf.toFixed(1)}%</span></div>
                <div className="efp-detail-row"><span>Annual Yield</span><span>{(flow.solarMW * flow.cf / 100 * 8760).toFixed(0)} MWh</span></div>
                <div className="efp-detail-row"><span>Panels (est.)</span><span>{Math.round(flow.solarMW * 1000 / 0.55).toLocaleString()}</span></div>
                <div className="efp-detail-row"><span>Area Required</span><span>{(flow.solarMW * 2).toFixed(0)} ha</span></div>
              </div>
            )}
            {activeNode === "grid" && (
              <div className="efp-detail-rows">
                <div className="efp-detail-row"><span>Nearest Substation</span><span>{gridContext?.nearest_substation?.name || "—"}</span></div>
                <div className="efp-detail-row"><span>Distance</span><span>{gridContext?.nearest_substation?.distance_km?.toFixed(1) || "—"} km</span></div>
                <div className="efp-detail-row"><span>Headroom</span><span>{gridCap?.toFixed(0) || "—"} MW</span></div>
                <div className="efp-detail-row"><span>Voltage</span><span>33 kV</span></div>
                <div className="efp-detail-row"><span>Est. Connection Cost</span><span>£{((gridContext?.nearest_substation?.distance_km || 3) * 150000 / 1e6).toFixed(1)}M</span></div>
              </div>
            )}
            {activeNode === "revenue" && (
              <div className="efp-detail-rows">
                <div className="efp-detail-row"><span>Gross Revenue</span><span>£{(flow.revenue / 1e6).toFixed(1)}M/yr</span></div>
                <div className="efp-detail-row"><span>Avg Price</span><span>£55/MWh</span></div>
                <div className="efp-detail-row"><span>Exported</span><span>{flow.exported.toFixed(0)} MWh/yr</span></div>
                <div className="efp-detail-row"><span>25yr NPV (est.)</span><span>£{(flow.revenue * 15 / 1e6).toFixed(0)}M</span></div>
              </div>
            )}
            {activeNode === "bess" && (
              <div className="efp-detail-rows">
                <div className="efp-detail-row"><span>Power</span><span>{(flow.bessMWh / 4).toFixed(0)} MW</span></div>
                <div className="efp-detail-row"><span>Energy</span><span>{flow.bessMWh.toFixed(0)} MWh</span></div>
                <div className="efp-detail-row"><span>Duration</span><span>4 hours</span></div>
                <div className="efp-detail-row"><span>Curtailment Saved</span><span>{(flow.annualMWh * 0.06).toFixed(0)} MWh/yr</span></div>
              </div>
            )}
            {activeNode === "curtailed" && (
              <div className="efp-detail-rows">
                <div className="efp-detail-row"><span>Energy Lost</span><span>{flow.curtailed.toFixed(0)} MWh/yr</span></div>
                <div className="efp-detail-row"><span>Revenue Lost</span><span>£{(flow.curtailed * 55 / 1e3).toFixed(0)}k/yr</span></div>
                <div className="efp-detail-row"><span>Fix</span><span>{flow.hasBess ? "BESS absorbs excess" : "Add BESS to reduce"}</span></div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
