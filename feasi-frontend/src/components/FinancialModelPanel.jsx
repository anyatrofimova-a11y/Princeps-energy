import React, { useState, useCallback, useEffect, useMemo } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";
import LenderCovenantTable from "./LenderCovenantTable";

/* ── UK Benchmark Defaults by Technology ────────────────────────────────── */
const TECH_BENCHMARKS = {
  solar: {
    label: "Solar PV",
    modules_per_kw: 450, bos_per_kw: 120, epc_per_kw: 80,
    dev_costs: 250000, land_per_acre_yr: 1000,
    om_per_kw_yr: 12, insurance_pct: 0.5, land_lease_yr: 25000, grid_charges_mwh: 6,
    ppa_price_mwh: 55, capacity_factor: 0.11,
  },
  wind: {
    label: "Wind",
    modules_per_kw: 900, bos_per_kw: 200, epc_per_kw: 150,
    dev_costs: 500000, land_per_acre_yr: 1200,
    om_per_kw_yr: 25, insurance_pct: 0.5, land_lease_yr: 40000, grid_charges_mwh: 5,
    ppa_price_mwh: 50, capacity_factor: 0.28,
  },
  bess: {
    label: "BESS",
    modules_per_kw: 350, bos_per_kw: 100, epc_per_kw: 60,
    dev_costs: 200000, land_per_acre_yr: 800,
    om_per_kw_yr: 8, insurance_pct: 0.6, land_lease_yr: 15000, grid_charges_mwh: 8,
    ppa_price_mwh: 65, capacity_factor: 0.15,
  },
  hybrid: {
    label: "Hybrid",
    modules_per_kw: 550, bos_per_kw: 160, epc_per_kw: 100,
    dev_costs: 400000, land_per_acre_yr: 1100,
    om_per_kw_yr: 18, insurance_pct: 0.5, land_lease_yr: 35000, grid_charges_mwh: 6,
    ppa_price_mwh: 52, capacity_factor: 0.18,
  },
  dc: {
    label: "Data Centre",
    modules_per_kw: 600, bos_per_kw: 250, epc_per_kw: 200,
    dev_costs: 1000000, land_per_acre_yr: 2500,
    om_per_kw_yr: 30, insurance_pct: 0.6, land_lease_yr: 80000, grid_charges_mwh: 10,
    ppa_price_mwh: 60, capacity_factor: 0.90,
  },
};

const PPA_STRUCTURES = [
  { id: "fixed", label: "Fixed Price" },
  { id: "indexed", label: "CPI Indexed" },
  { id: "floor_upside", label: "Floor + Upside" },
  { id: "merchant", label: "Full Merchant" },
];

/* ── Formatters ────────────────────────────────────────────────────────── */
function fmtGbp(v) {
  if (v == null || isNaN(v)) return "--";
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}\u00A3${(abs / 1e9).toFixed(1)}bn`;
  if (abs >= 1e6) return `${sign}\u00A3${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}\u00A3${(abs / 1e3).toFixed(0)}k`;
  return `${sign}\u00A3${abs.toFixed(0)}`;
}
function fmtNum(v, dp = 1) {
  if (v == null || isNaN(v)) return "--";
  return v.toLocaleString("en-GB", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}
function fmtPct(v, dp = 1) {
  if (v == null || isNaN(v)) return "--";
  return `${(v * 100).toFixed(dp)}%`;
}
function fmtPctRaw(v, dp = 1) {
  if (v == null || isNaN(v)) return "--";
  return `${v.toFixed(dp)}%`;
}

/* ── Local cashflow model (client-side, mirrors backend logic) ─────────── */
function buildCashflow(params) {
  const {
    capacityMw, technology, modulesCost, bosCost, epcCost, gridCost, devCosts, landLeaseAcre,
    omPerKw, insurancePct, landLeaseYr, gridChargesMwh,
    ppaPrice, escalation, cfdSubsidy, capacityMarket, ancillary,
    gearing, debtTenor, interestRate, dscrReq, lifetime,
  } = params;

  const capacityKw = capacityMw * 1000;
  const bench = TECH_BENCHMARKS[technology] || TECH_BENCHMARKS.solar;
  const cf = bench.capacity_factor;

  // CAPEX
  const totalCapex = (modulesCost * capacityKw) + (bosCost * capacityKw) + (epcCost * capacityKw) + gridCost + devCosts;

  // Annual generation
  const annualMwh = capacityMw * cf * 8760;

  // Debt/equity split
  const debtQuantum = totalCapex * gearing;
  const equityQuantum = totalCapex * (1 - gearing);
  const annualDebtService = debtTenor > 0
    ? debtQuantum * (interestRate / 100 * Math.pow(1 + interestRate / 100, debtTenor)) / (Math.pow(1 + interestRate / 100, debtTenor) - 1)
    : 0;

  const years = [];
  let cumulativeCf = -equityQuantum;
  let npv = -totalCapex;
  const discountRate = 0.08;
  let paybackYear = null;

  for (let yr = 1; yr <= lifetime; yr++) {
    const esc = Math.pow(1 + (escalation || 0) / 100, yr - 1);
    const ppaRev = annualMwh * ppaPrice * esc;
    const cfdRev = (cfdSubsidy || 0) * annualMwh;
    const cmRev = (capacityMarket || 0) * capacityKw;
    const ancRev = (ancillary || 0) * capacityMw;
    const grossRev = ppaRev + cfdRev + cmRev + ancRev;

    const opex = (omPerKw * capacityKw) + (insurancePct / 100 * totalCapex) + landLeaseYr + (gridChargesMwh * annualMwh);
    const ebitda = grossRev - opex;
    const debtSvc = yr <= debtTenor ? annualDebtService : 0;
    const netCf = ebitda - debtSvc;
    const dscr = debtSvc > 0 ? ebitda / debtSvc : 99;

    cumulativeCf += netCf;
    npv += ebitda / Math.pow(1 + discountRate, yr);

    if (cumulativeCf >= 0 && !paybackYear) paybackYear = yr;

    years.push({
      year: yr, grossRev, opex, ebitda, debtSvc, netCf, dscr,
      cumulativeCf, ppaRev, cfdRev, cmRev, ancRev,
    });
  }

  // LCOE
  let totalGenPv = 0;
  for (let yr = 1; yr <= lifetime; yr++) {
    totalGenPv += annualMwh / Math.pow(1 + discountRate, yr);
  }
  const lcoe = totalCapex / totalGenPv;

  // Approximate unlevered IRR via Newton's method
  let irr = 0.08;
  for (let iter = 0; iter < 50; iter++) {
    let npvCalc = -totalCapex;
    let dnpv = 0;
    for (let yr = 1; yr <= lifetime; yr++) {
      const cf_yr = years[yr - 1].ebitda;
      npvCalc += cf_yr / Math.pow(1 + irr, yr);
      dnpv -= yr * cf_yr / Math.pow(1 + irr, yr + 1);
    }
    if (Math.abs(dnpv) < 1e-10) break;
    irr = irr - npvCalc / dnpv;
    if (Math.abs(npvCalc) < 100) break;
  }

  // Equity IRR
  let equityIrr = 0.10;
  for (let iter = 0; iter < 50; iter++) {
    let npvCalc = -equityQuantum;
    let dnpv = 0;
    for (let yr = 1; yr <= lifetime; yr++) {
      const cf_yr = years[yr - 1].netCf;
      npvCalc += cf_yr / Math.pow(1 + equityIrr, yr);
      dnpv -= yr * cf_yr / Math.pow(1 + equityIrr, yr + 1);
    }
    if (Math.abs(dnpv) < 1e-10) break;
    equityIrr = equityIrr - npvCalc / dnpv;
    if (Math.abs(npvCalc) < 100) break;
  }

  const minDscr = Math.min(...years.filter(y => y.debtSvc > 0).map(y => y.dscr));

  return {
    totalCapex, annualMwh, debtQuantum, equityQuantum, annualDebtService,
    irr, equityIrr, npv, lcoe, paybackYear, minDscr,
    years, lifetime, gearing, debtTenor,
  };
}

/* ── Sensitivity table builder ─────────────────────────────────────────── */
function buildSensitivity(baseParams) {
  const capexRange = [-20, -10, -5, 0, 5, 10, 20];
  const revRange = [-20, -10, -5, 0, 5, 10, 20];

  const rows = revRange.map(revDelta => {
    const cells = capexRange.map(capexDelta => {
      const adjusted = {
        ...baseParams,
        modulesCost: baseParams.modulesCost * (1 + capexDelta / 100),
        bosCost: baseParams.bosCost * (1 + capexDelta / 100),
        epcCost: baseParams.epcCost * (1 + capexDelta / 100),
        ppaPrice: baseParams.ppaPrice * (1 + revDelta / 100),
      };
      const result = buildCashflow(adjusted);
      return { irr: result.irr, capexDelta, revDelta };
    });
    return { revDelta, cells };
  });

  return { capexRange, revRange, rows };
}

/* ── Tornado chart data ────────────────────────────────────────────────── */
function buildTornado(baseParams) {
  const baseIrr = buildCashflow(baseParams).irr;
  const factors = [
    { key: "ppaPrice", label: "PPA Price", field: "ppaPrice", delta: 0.15 },
    { key: "modulesCost", label: "Module Cost", field: "modulesCost", delta: 0.2 },
    { key: "capacityMw", label: "Capacity", field: "capacityMw", delta: 0.15 },
    { key: "gearing", label: "Gearing", field: "gearing", delta: 0.15 },
    { key: "interestRate", label: "Interest Rate", field: "interestRate", delta: 0.3 },
    { key: "gridCost", label: "Grid Connection", field: "gridCost", delta: 0.3 },
    { key: "omPerKw", label: "O&M Cost", field: "omPerKw", delta: 0.25 },
    { key: "escalation", label: "PPA Escalation", field: "escalation", delta: 0.5 },
    { key: "landLeaseYr", label: "Land Lease", field: "landLeaseYr", delta: 0.3 },
    { key: "insurancePct", label: "Insurance", field: "insurancePct", delta: 0.5 },
  ];

  const results = factors.map(f => {
    const lo = { ...baseParams, [f.field]: baseParams[f.field] * (1 - f.delta) };
    const hi = { ...baseParams, [f.field]: baseParams[f.field] * (1 + f.delta) };
    const irrLo = buildCashflow(lo).irr;
    const irrHi = buildCashflow(hi).irr;
    return { ...f, irrLo, irrHi, spread: Math.abs(irrHi - irrLo), baseIrr };
  });

  results.sort((a, b) => b.spread - a.spread);
  return results.slice(0, 10);
}

/* ── SVG Cashflow Waterfall Chart ──────────────────────────────────────── */
function WaterfallChart({ years, width = 580, height = 180 }) {
  if (!years?.length) return null;
  const pad = { l: 55, r: 10, t: 10, b: 28 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;

  const maxVal = Math.max(...years.map(y => Math.abs(y.netCf)));
  const minVal = Math.min(...years.map(y => y.cumulativeCf), 0);
  const yRange = Math.max(maxVal, Math.abs(minVal)) * 1.2;
  const zeroY = pad.t + h / 2;

  const barW = Math.min(w / years.length * 0.7, 16);
  const gap = w / years.length;

  const y = (v) => zeroY - (v / yRange) * (h / 2);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="fm-chart" style={{ width: "100%", height: "auto" }}>
      {/* Zero line */}
      <line x1={pad.l} y1={zeroY} x2={width - pad.r} y2={zeroY} stroke="rgba(255,255,255,0.15)" strokeWidth={1} />

      {/* Y-axis labels */}
      {[-yRange, -yRange / 2, 0, yRange / 2, yRange].map((v, i) => (
        <text key={i} x={pad.l - 6} y={y(v) + 3} textAnchor="end" fill="rgba(255,255,255,0.35)" fontSize="8" fontFamily="var(--mono)">
          {fmtGbp(v)}
        </text>
      ))}

      {/* Bars */}
      {years.map((yr, i) => {
        const xc = pad.l + i * gap + gap / 2;
        const cfVal = yr.netCf;
        const isPos = cfVal >= 0;
        const barH = Math.max(1, Math.abs(cfVal) / yRange * (h / 2));
        return (
          <g key={yr.year}>
            <rect
              x={xc - barW / 2}
              y={isPos ? zeroY - barH : zeroY}
              width={barW}
              height={barH}
              fill={isPos ? "rgba(245, 183, 49, 0.7)" : "rgba(220, 38, 38, 0.6)"}
              rx={1}
            />
            {/* Cumulative line marker */}
            <circle
              cx={xc}
              cy={y(yr.cumulativeCf)}
              r={2}
              fill="#fff"
              opacity={0.6}
            />
            {i % 5 === 0 && (
              <text x={xc} y={height - 6} textAnchor="middle" fill="rgba(255,255,255,0.35)" fontSize="7" fontFamily="var(--mono)">
                Y{yr.year}
              </text>
            )}
          </g>
        );
      })}

      {/* Cumulative line */}
      <path
        d={years.map((yr, i) => {
          const xc = pad.l + i * gap + gap / 2;
          return `${i === 0 ? "M" : "L"}${xc},${y(yr.cumulativeCf)}`;
        }).join(" ")}
        fill="none"
        stroke="#fff"
        strokeWidth={1.2}
        opacity={0.5}
      />
    </svg>
  );
}

/* ── SVG DSCR Profile Chart ────────────────────────────────────────────── */
function DscrChart({ years, dscrReq = 1.3, width = 580, height = 140 }) {
  const debtYears = years?.filter(y => y.debtSvc > 0);
  if (!debtYears?.length) return null;

  const pad = { l: 40, r: 10, t: 10, b: 24 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;

  const maxDscr = Math.max(...debtYears.map(y => y.dscr), dscrReq * 1.5);
  const gap = w / debtYears.length;
  const barW = Math.min(gap * 0.6, 14);

  const y = (v) => pad.t + h - (v / maxDscr) * h;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="fm-chart" style={{ width: "100%", height: "auto" }}>
      {/* Requirement line */}
      <line x1={pad.l} y1={y(dscrReq)} x2={width - pad.r} y2={y(dscrReq)}
        stroke="#f5222d" strokeDasharray="4 2" strokeWidth={1} opacity={0.6} />
      <text x={width - pad.r + 2} y={y(dscrReq) + 3} fill="#f5222d" fontSize="7" fontFamily="var(--mono)">
        {dscrReq.toFixed(1)}x
      </text>

      {debtYears.map((yr, i) => {
        const xc = pad.l + i * gap + gap / 2;
        const barH = Math.max(1, (yr.dscr / maxDscr) * h);
        const color = yr.dscr >= dscrReq ? "rgba(245, 183, 49, 0.7)" : "rgba(220, 38, 38, 0.6)";
        return (
          <g key={yr.year}>
            <rect x={xc - barW / 2} y={pad.t + h - barH} width={barW} height={barH} fill={color} rx={1} />
            {i % 3 === 0 && (
              <text x={xc} y={height - 6} textAnchor="middle" fill="rgba(255,255,255,0.35)" fontSize="7" fontFamily="var(--mono)">
                Y{yr.year}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/* ── SVG Tornado Chart ─────────────────────────────────────────────────── */
function TornadoChart({ data, width = 580, height = 240 }) {
  if (!data?.length) return null;
  const pad = { l: 100, r: 50, t: 6, b: 6 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const rowH = h / data.length;

  const baseIrr = data[0]?.baseIrr || 0;
  const maxSpread = Math.max(...data.map(d => d.spread)) * 1.2;
  const scale = (v) => pad.l + w / 2 + ((v - baseIrr) / maxSpread) * w;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="fm-chart" style={{ width: "100%", height: "auto" }}>
      {/* Base line */}
      <line x1={scale(baseIrr)} y1={pad.t} x2={scale(baseIrr)} y2={pad.t + h}
        stroke="rgba(255,255,255,0.3)" strokeWidth={1} />
      <text x={scale(baseIrr)} y={pad.t - 1} textAnchor="middle" fill="rgba(255,255,255,0.5)" fontSize="7" fontFamily="var(--mono)">
        {fmtPct(baseIrr)}
      </text>

      {data.map((d, i) => {
        const cy = pad.t + i * rowH + rowH / 2;
        const x1 = scale(Math.min(d.irrLo, d.irrHi));
        const x2 = scale(Math.max(d.irrLo, d.irrHi));
        return (
          <g key={d.key}>
            <text x={pad.l - 4} y={cy + 3} textAnchor="end" fill="rgba(255,255,255,0.6)" fontSize="8">
              {d.label}
            </text>
            <rect x={x1} y={cy - rowH * 0.3} width={Math.max(1, x2 - x1)} height={rowH * 0.6}
              fill="rgba(245, 183, 49, 0.5)" rx={2} />
            <text x={x1 - 3} y={cy + 3} textAnchor="end" fill="rgba(255,255,255,0.4)" fontSize="7" fontFamily="var(--mono)">
              {fmtPct(Math.min(d.irrLo, d.irrHi))}
            </text>
            <text x={x2 + 3} y={cy + 3} textAnchor="start" fill="rgba(255,255,255,0.4)" fontSize="7" fontFamily="var(--mono)">
              {fmtPct(Math.max(d.irrLo, d.irrHi))}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* ── Revenue Waterfall SVG ─────────────────────────────────────────────── */
function RevenueWaterfallChart({ data, width = 580, height = 160 }) {
  if (!data) return null;
  const items = [
    { label: "Gross Gen", value: data.grossGen, color: "rgba(245,183,49,0.7)" },
    { label: "Curtailment", value: -data.curtailment, color: "rgba(220,38,38,0.6)" },
    { label: "Grid Losses", value: -data.gridLosses, color: "rgba(220,38,38,0.5)" },
    { label: "PPA Revenue", value: data.ppaRevenue, color: "rgba(59,130,246,0.7)" },
    { label: "Merchant", value: data.merchantRevenue, color: "rgba(139,92,246,0.6)" },
    { label: "Ancillary", value: data.ancillaryRevenue, color: "rgba(16,163,74,0.6)" },
    { label: "Net Revenue", value: data.netRevenue, color: "rgba(245,183,49,0.9)" },
  ].filter(i => Math.abs(i.value) > 0);

  const pad = { l: 65, r: 10, t: 10, b: 28 };
  const w = width - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const maxVal = Math.max(...items.map(i => Math.abs(i.value)));
  const barW = Math.min(w / items.length * 0.6, 40);
  const gap = w / items.length;
  const y = (v) => pad.t + h - (v / maxVal) * h;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="fm-chart" style={{ width: "100%", height: "auto" }}>
      <line x1={pad.l} y1={pad.t + h} x2={width - pad.r} y2={pad.t + h} stroke="rgba(255,255,255,0.1)" />
      {items.map((item, i) => {
        const xc = pad.l + i * gap + gap / 2;
        const barH = Math.max(1, (Math.abs(item.value) / maxVal) * h);
        const isNeg = item.value < 0;
        return (
          <g key={item.label}>
            <rect
              x={xc - barW / 2}
              y={isNeg ? pad.t + h - barH : pad.t + h - barH}
              width={barW} height={barH}
              fill={item.color} rx={2}
            />
            <text x={xc} y={pad.t + h - barH - 4} textAnchor="middle" fill="rgba(255,255,255,0.6)" fontSize="7" fontFamily="var(--mono)">
              {fmtGbp(item.value)}
            </text>
            <text x={xc} y={height - 4} textAnchor="middle" fill="rgba(255,255,255,0.4)" fontSize="7">
              {item.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   FinancialModelPanel — right slide-in panel
   ══════════════════════════════════════════════════════════════════════════ */
export default function FinancialModelPanel({ onClose }) {
  const { selectedParcel, explain, samCapacity } = useSite();

  const [activeTab, setActiveTab] = useState("project");
  const [technology, setTechnology] = useState("solar");
  const [capacityMw, setCapacityMw] = useState(50);
  const [loading, setLoading] = useState(false);
  const [backendResult, setBackendResult] = useState(null);
  const [showCashflow, setShowCashflow] = useState(false);
  const [scenario, setScenario] = useState("central");

  // CAPEX inputs
  const bench = TECH_BENCHMARKS[technology] || TECH_BENCHMARKS.solar;
  const [modulesCost, setModulesCost] = useState(bench.modules_per_kw);
  const [bosCost, setBosCost] = useState(bench.bos_per_kw);
  const [epcCost, setEpcCost] = useState(bench.epc_per_kw);
  const [gridCost, setGridCost] = useState(500000);
  const [devCosts, setDevCosts] = useState(bench.dev_costs);
  const [landLeaseAcre, setLandLeaseAcre] = useState(bench.land_per_acre_yr);

  // OPEX inputs
  const [omPerKw, setOmPerKw] = useState(bench.om_per_kw_yr);
  const [insurancePct, setInsurancePct] = useState(bench.insurance_pct);
  const [landLeaseYr, setLandLeaseYr] = useState(bench.land_lease_yr);
  const [gridChargesMwh, setGridChargesMwh] = useState(bench.grid_charges_mwh);

  // Revenue inputs
  const [ppaPrice, setPpaPrice] = useState(bench.ppa_price_mwh);
  const [escalation, setEscalation] = useState(2.0);
  const [cfdSubsidy, setCfdSubsidy] = useState(0);
  const [capacityMarket, setCapacityMarket] = useState(0);
  const [ancillary, setAncillary] = useState(0);

  // Debt & Equity inputs
  const [gearing, setGearing] = useState(70);
  const [debtTenor, setDebtTenor] = useState(18);
  const [interestRate, setInterestRate] = useState(5.5);
  const [dscrReq, setDscrReq] = useState(1.3);
  const [equityIrrTarget, setEquityIrrTarget] = useState(10);
  const [lifetime, setLifetime] = useState(25);

  // PPA tab
  const [ppaStructure, setPpaStructure] = useState("fixed");
  const [ppaTenor, setPpaTenor] = useState(15);
  const [curtailmentPct, setCurtailmentPct] = useState(3);

  // Sync technology benchmarks
  useEffect(() => {
    const b = TECH_BENCHMARKS[technology] || TECH_BENCHMARKS.solar;
    setModulesCost(b.modules_per_kw);
    setBosCost(b.bos_per_kw);
    setEpcCost(b.epc_per_kw);
    setDevCosts(b.dev_costs);
    setOmPerKw(b.om_per_kw_yr);
    setInsurancePct(b.insurance_pct);
    setLandLeaseYr(b.land_lease_yr);
    setGridChargesMwh(b.grid_charges_mwh);
    setPpaPrice(b.ppa_price_mwh);
  }, [technology]);

  // Sync capacity from samCapacity
  useEffect(() => {
    if (samCapacity && samCapacity > 100) setCapacityMw(samCapacity / 1000);
  }, [samCapacity]);

  // Build the model params
  const modelParams = useMemo(() => ({
    capacityMw, technology, modulesCost, bosCost, epcCost, gridCost, devCosts, landLeaseAcre,
    omPerKw, insurancePct, landLeaseYr, gridChargesMwh,
    ppaPrice, escalation, cfdSubsidy, capacityMarket, ancillary,
    gearing: gearing / 100, debtTenor, interestRate, dscrReq, lifetime,
  }), [capacityMw, technology, modulesCost, bosCost, epcCost, gridCost, devCosts, landLeaseAcre,
    omPerKw, insurancePct, landLeaseYr, gridChargesMwh,
    ppaPrice, escalation, cfdSubsidy, capacityMarket, ancillary,
    gearing, debtTenor, interestRate, dscrReq, lifetime]);

  const model = useMemo(() => buildCashflow(modelParams), [modelParams]);
  const sensitivity = useMemo(() => activeTab === "sensitivity" ? buildSensitivity(modelParams) : null, [activeTab, modelParams]);
  const tornado = useMemo(() => activeTab === "sensitivity" ? buildTornado(modelParams) : null, [activeTab, modelParams]);

  // Revenue waterfall data for PPA tab
  const revenueData = useMemo(() => {
    if (!model) return null;
    const yr1 = model.years[0];
    if (!yr1) return null;
    return {
      grossGen: model.annualMwh,
      curtailment: model.annualMwh * (curtailmentPct / 100),
      gridLosses: model.annualMwh * 0.02,
      ppaRevenue: yr1.ppaRev,
      merchantRevenue: yr1.cfdRev,
      ancillaryRevenue: yr1.cmRev + yr1.ancRev,
      netRevenue: yr1.grossRev,
    };
  }, [model, curtailmentPct]);

  // Optionally fetch from backend
  const fetchBackend = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.investment.projectFinance(capacityMw, technology, "England", ppaPrice);
      setBackendResult(data);
    } catch (e) { /* silent */ }
    setLoading(false);
  }, [capacityMw, technology, ppaPrice]);

  const irrClass = (v) => {
    if (v == null) return "";
    if (v >= 0.10) return "fm-positive";
    if (v >= 0.06) return "fm-caution";
    return "fm-negative";
  };

  const sensClass = (irr) => {
    if (irr >= 0.10) return "fm-sens-green";
    if (irr >= 0.06) return "fm-sens-amber";
    return "fm-sens-red";
  };

  return (
    <div className="gc-panel fm-panel">
      {/* Header */}
      <div className="gc-panel-header">
        <div className="gc-panel-title">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6" />
          </svg>
          Project Finance
        </div>
        <button className="gc-close" onClick={onClose} title="Close">&times;</button>
      </div>

      {/* Input bar */}
      <div className="gc-input-bar">
        <div className="gc-input-group">
          <label className="gc-input-label">Capacity (MW)</label>
          <input type="number" value={capacityMw} min={0.1} step={1}
            onChange={e => setCapacityMw(+e.target.value)} className="gc-input" />
        </div>
        <div className="gc-input-group">
          <label className="gc-input-label">Technology</label>
          <select value={technology} onChange={e => setTechnology(e.target.value)} className="gc-input">
            {Object.entries(TECH_BENCHMARKS).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </select>
        </div>
        <button onClick={fetchBackend} disabled={loading}
          className={`gc-assess-btn${loading ? " gc-assess-btn--loading" : ""}`}>
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {/* Tabs */}
      <div className="df-tabs fm-tabs">
        {[
          { id: "project", label: "Project Model" },
          { id: "debt", label: "Debt & Equity" },
          { id: "ppa", label: "PPA & Revenue" },
          { id: "sensitivity", label: "Sensitivity" },
        ].map(tab => (
          <button key={tab.id}
            className={`df-tab ${activeTab === tab.id ? "active" : ""}`}
            onClick={() => setActiveTab(tab.id)}>
            {tab.label}
          </button>
        ))}
      </div>

      <div className="gc-panel-body">
        {/* ═══════════════════════════════════════════════════════════
            TAB 1: Project Model
           ═══════════════════════════════════════════════════════════ */}
        {activeTab === "project" && (
          <>
            {/* Key Outputs */}
            <div className="fm-kpi-strip">
              <div className="fm-kpi">
                <div className="fm-kpi-label">IRR</div>
                <div className={`fm-kpi-value ${irrClass(model.irr)}`}>{fmtPct(model.irr)}</div>
              </div>
              <div className="fm-kpi">
                <div className="fm-kpi-label">NPV</div>
                <div className={`fm-kpi-value ${model.npv >= 0 ? "fm-positive" : "fm-negative"}`}>{fmtGbp(model.npv)}</div>
              </div>
              <div className="fm-kpi">
                <div className="fm-kpi-label">LCOE</div>
                <div className="fm-kpi-value">{`\u00A3${model.lcoe?.toFixed(1)}/MWh`}</div>
              </div>
              <div className="fm-kpi">
                <div className="fm-kpi-label">Payback</div>
                <div className="fm-kpi-value">{model.paybackYear ? `${model.paybackYear} yrs` : ">25"}</div>
              </div>
              <div className="fm-kpi">
                <div className="fm-kpi-label">DSCR (min)</div>
                <div className={`fm-kpi-value ${model.minDscr >= dscrReq ? "fm-positive" : "fm-negative"}`}>
                  {model.minDscr < 99 ? `${model.minDscr?.toFixed(2)}x` : "--"}
                </div>
              </div>
            </div>

            {/* CAPEX Section */}
            <div className="gc-section">
              <div className="gc-section-header">
                <span className="gc-section-title">CAPEX</span>
                <span className="gc-section-badge">{fmtGbp(model.totalCapex)}</span>
              </div>
              <div className="fm-input-grid">
                <div className="fm-field">
                  <label>Modules/Turbines (\u00A3/kW)</label>
                  <input type="number" value={modulesCost} onChange={e => setModulesCost(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>BOS (\u00A3/kW)</label>
                  <input type="number" value={bosCost} onChange={e => setBosCost(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>EPC (\u00A3/kW)</label>
                  <input type="number" value={epcCost} onChange={e => setEpcCost(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>Grid Connection (\u00A3)</label>
                  <input type="number" value={gridCost} onChange={e => setGridCost(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>Development (\u00A3)</label>
                  <input type="number" value={devCosts} onChange={e => setDevCosts(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>Land (\u00A3/acre/yr)</label>
                  <input type="number" value={landLeaseAcre} onChange={e => setLandLeaseAcre(+e.target.value)} />
                </div>
              </div>
            </div>

            {/* OPEX Section */}
            <div className="gc-section">
              <div className="gc-section-header">
                <span className="gc-section-title">OPEX (Annual)</span>
                <span className="gc-section-badge">
                  {fmtGbp(omPerKw * capacityMw * 1000 + (insurancePct / 100 * model.totalCapex) + landLeaseYr + gridChargesMwh * model.annualMwh)}
                </span>
              </div>
              <div className="fm-input-grid">
                <div className="fm-field">
                  <label>O&M (\u00A3/kW/yr)</label>
                  <input type="number" value={omPerKw} onChange={e => setOmPerKw(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>Insurance (% CAPEX)</label>
                  <input type="number" value={insurancePct} step={0.1} onChange={e => setInsurancePct(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>Land Lease (\u00A3/yr)</label>
                  <input type="number" value={landLeaseYr} onChange={e => setLandLeaseYr(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>Grid Charges (\u00A3/MWh)</label>
                  <input type="number" value={gridChargesMwh} step={0.5} onChange={e => setGridChargesMwh(+e.target.value)} />
                </div>
              </div>
            </div>

            {/* Revenue Assumptions */}
            <div className="gc-section">
              <div className="gc-section-header">
                <span className="gc-section-title">Revenue</span>
                <span className="gc-section-badge">{fmtGbp(model.years[0]?.grossRev)}/yr</span>
              </div>
              <div className="fm-input-grid">
                <div className="fm-field">
                  <label>PPA Price (\u00A3/MWh)</label>
                  <input type="number" value={ppaPrice} step={1} onChange={e => setPpaPrice(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>Escalation (%/yr)</label>
                  <input type="number" value={escalation} step={0.5} onChange={e => setEscalation(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>CfD/ROC (\u00A3/MWh)</label>
                  <input type="number" value={cfdSubsidy} onChange={e => setCfdSubsidy(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>Capacity Mkt (\u00A3/kW)</label>
                  <input type="number" value={capacityMarket} onChange={e => setCapacityMarket(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>Ancillary (\u00A3/MW)</label>
                  <input type="number" value={ancillary} onChange={e => setAncillary(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>Project Life (yrs)</label>
                  <input type="number" value={lifetime} min={1} max={40} onChange={e => setLifetime(+e.target.value)} />
                </div>
              </div>
            </div>

            {/* Cashflow Chart */}
            <div className="gc-section">
              <div className="gc-section-header">
                <span className="gc-section-title">Cashflow Waterfall</span>
                <span className="gc-section-badge">{lifetime} years</span>
              </div>
              <div className="fm-chart-wrap">
                <WaterfallChart years={model.years} />
              </div>
              <div className="fm-chart-legend">
                <span><span className="fm-legend-bar fm-legend-pos" /> Net cashflow</span>
                <span><span className="fm-legend-line" /> Cumulative</span>
              </div>
            </div>

            {/* Expandable cashflow table */}
            <div className="gc-section">
              <button className="fm-expand-btn" onClick={() => setShowCashflow(!showCashflow)}>
                {showCashflow ? "Hide" : "Show"} 25-Year Cashflow Table
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                  style={{ transform: showCashflow ? "rotate(180deg)" : "none", transition: "transform 0.2s" }}>
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </button>
              {showCashflow && (
                <div className="fm-cashflow-table">
                  <div className="fm-table-header">
                    <span>Year</span><span>Revenue</span><span>OPEX</span><span>EBITDA</span>
                    <span>Debt Svc</span><span>Net CF</span><span>DSCR</span>
                  </div>
                  {model.years.map(yr => (
                    <div key={yr.year} className={`fm-table-row ${yr.netCf < 0 ? "fm-row-neg" : ""}`}>
                      <span className="fm-table-year">{yr.year}</span>
                      <span className="fm-table-num">{fmtGbp(yr.grossRev)}</span>
                      <span className="fm-table-num fm-negative">{fmtGbp(-yr.opex)}</span>
                      <span className="fm-table-num">{fmtGbp(yr.ebitda)}</span>
                      <span className="fm-table-num">{yr.debtSvc > 0 ? fmtGbp(-yr.debtSvc) : "--"}</span>
                      <span className={`fm-table-num ${yr.netCf >= 0 ? "fm-positive" : "fm-negative"}`}>
                        {fmtGbp(yr.netCf)}
                      </span>
                      <span className={`fm-table-num ${yr.dscr >= dscrReq ? "fm-positive" : yr.dscr < 99 ? "fm-negative" : ""}`}>
                        {yr.dscr < 99 ? `${yr.dscr.toFixed(2)}x` : "--"}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

        {/* ═══════════════════════════════════════════════════════════
            TAB 2: Debt & Equity
           ═══════════════════════════════════════════════════════════ */}
        {activeTab === "debt" && (
          <>
            {/* Capital Structure */}
            <div className="gc-section">
              <div className="gc-section-header">
                <span className="gc-section-title">Capital Structure</span>
                <span className="gc-section-badge">{fmtGbp(model.totalCapex)}</span>
              </div>

              <div className="fm-slider-row">
                <label>Gearing</label>
                <input type="range" min={0} max={90} value={gearing}
                  onChange={e => setGearing(+e.target.value)} className="fm-slider" />
                <span className="fm-slider-val">{gearing}%</span>
              </div>
              <div className="fm-input-grid">
                <div className="fm-field">
                  <label>Debt Tenor (yrs)</label>
                  <input type="number" value={debtTenor} min={1} max={30} onChange={e => setDebtTenor(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>Interest Rate (%)</label>
                  <input type="number" value={interestRate} step={0.25} onChange={e => setInterestRate(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>DSCR Req.</label>
                  <input type="number" value={dscrReq} step={0.05} onChange={e => setDscrReq(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>Equity IRR Target (%)</label>
                  <input type="number" value={equityIrrTarget} step={0.5} onChange={e => setEquityIrrTarget(+e.target.value)} />
                </div>
              </div>
            </div>

            {/* Sources & Uses */}
            <div className="gc-section">
              <div className="gc-section-header">
                <span className="gc-section-title">Sources & Uses</span>
              </div>
              <div className="fm-sources-uses">
                <div className="fm-su-section">
                  <div className="fm-su-title">Sources</div>
                  <div className="fm-su-row">
                    <span>Senior Debt</span>
                    <span className="fm-su-value">{fmtGbp(model.debtQuantum)}</span>
                  </div>
                  <div className="fm-su-row">
                    <span>Equity</span>
                    <span className="fm-su-value">{fmtGbp(model.equityQuantum)}</span>
                  </div>
                  <div className="fm-su-row fm-su-total">
                    <span>Total Sources</span>
                    <span className="fm-su-value">{fmtGbp(model.totalCapex)}</span>
                  </div>
                </div>
                <div className="fm-su-section">
                  <div className="fm-su-title">Uses</div>
                  <div className="fm-su-row">
                    <span>EPC / Equipment</span>
                    <span className="fm-su-value">{fmtGbp((modulesCost + bosCost + epcCost) * capacityMw * 1000)}</span>
                  </div>
                  <div className="fm-su-row">
                    <span>Grid Connection</span>
                    <span className="fm-su-value">{fmtGbp(gridCost)}</span>
                  </div>
                  <div className="fm-su-row">
                    <span>Development</span>
                    <span className="fm-su-value">{fmtGbp(devCosts)}</span>
                  </div>
                  <div className="fm-su-row fm-su-total">
                    <span>Total Uses</span>
                    <span className="fm-su-value">{fmtGbp(model.totalCapex)}</span>
                  </div>
                </div>
              </div>

              {/* Gearing visual bar */}
              <div className="fm-gearing-bar">
                <div className="fm-gearing-debt" style={{ width: `${gearing}%` }}>
                  <span>Debt {gearing}%</span>
                </div>
                <div className="fm-gearing-equity" style={{ width: `${100 - gearing}%` }}>
                  <span>Equity {100 - gearing}%</span>
                </div>
              </div>
            </div>

            {/* Outputs */}
            <div className="fm-kpi-strip">
              <div className="fm-kpi">
                <div className="fm-kpi-label">Debt Quantum</div>
                <div className="fm-kpi-value">{fmtGbp(model.debtQuantum)}</div>
              </div>
              <div className="fm-kpi">
                <div className="fm-kpi-label">Annual Debt Svc</div>
                <div className="fm-kpi-value">{fmtGbp(model.annualDebtService)}</div>
              </div>
              <div className="fm-kpi">
                <div className="fm-kpi-label">Equity IRR</div>
                <div className={`fm-kpi-value ${irrClass(model.equityIrr)}`}>{fmtPct(model.equityIrr)}</div>
              </div>
              <div className="fm-kpi">
                <div className="fm-kpi-label">Min DSCR</div>
                <div className={`fm-kpi-value ${model.minDscr >= dscrReq ? "fm-positive" : "fm-negative"}`}>
                  {model.minDscr < 99 ? `${model.minDscr?.toFixed(2)}x` : "--"}
                </div>
              </div>
            </div>

            {/* DSCR Profile Chart */}
            <div className="gc-section">
              <div className="gc-section-header">
                <span className="gc-section-title">DSCR Profile</span>
                <span className="gc-section-badge">{debtTenor} yr debt</span>
              </div>
              <div className="fm-chart-wrap">
                <DscrChart years={model.years} dscrReq={dscrReq} />
              </div>
            </div>

            {/* Lender Covenant Table — DSCR / LLCR / PLCR / ICR / Gearing */}
            <div className="gc-section">
              <LenderCovenantTable
                capex={model.totalCapex}
                revenueSchedule={model.years.map(y => y.grossRev)}
                opexSchedule={model.years.map(y => y.opex)}
                debtPrincipal={model.debtQuantum}
                debtRate={interestRate / 100}
                debtTermYears={debtTenor}
                wacc={0.08}
                costOfEquity={Math.max(equityIrrTarget / 100, 0.10)}
                taxRate={0.25}
                terminalGrowth={0.02}
                thresholds={{
                  dscr_min: dscrReq,
                  llcr_min: 1.30,
                  plcr_min: 1.40,
                  icr_min: 2.00,
                  gearing_max: 0.75,
                }}
                title="Lender Covenants"
              />
            </div>
          </>
        )}

        {/* ═══════════════════════════════════════════════════════════
            TAB 3: PPA & Revenue
           ═══════════════════════════════════════════════════════════ */}
        {activeTab === "ppa" && (
          <>
            <div className="gc-section">
              <div className="gc-section-header">
                <span className="gc-section-title">PPA Structure</span>
              </div>
              <div className="fm-ppa-structure">
                {PPA_STRUCTURES.map(s => (
                  <button key={s.id}
                    className={`fm-ppa-btn ${ppaStructure === s.id ? "active" : ""}`}
                    onClick={() => setPpaStructure(s.id)}>
                    {s.label}
                  </button>
                ))}
              </div>
              <div className="fm-input-grid">
                <div className="fm-field">
                  <label>PPA Tenor (yrs)</label>
                  <input type="number" value={ppaTenor} min={1} max={25} onChange={e => setPpaTenor(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>Base Price (\u00A3/MWh)</label>
                  <input type="number" value={ppaPrice} step={1} onChange={e => setPpaPrice(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>Escalation (%/yr)</label>
                  <input type="number" value={escalation} step={0.5} onChange={e => setEscalation(+e.target.value)} />
                </div>
                <div className="fm-field">
                  <label>Curtailment (%)</label>
                  <input type="number" value={curtailmentPct} step={0.5} onChange={e => setCurtailmentPct(+e.target.value)} />
                </div>
              </div>
            </div>

            {/* Revenue KPIs */}
            <div className="fm-kpi-strip">
              <div className="fm-kpi">
                <div className="fm-kpi-label">Annual Generation</div>
                <div className="fm-kpi-value">{fmtNum(model.annualMwh, 0)} MWh</div>
              </div>
              <div className="fm-kpi">
                <div className="fm-kpi-label">Yr 1 Revenue</div>
                <div className="fm-kpi-value">{fmtGbp(model.years[0]?.grossRev)}</div>
              </div>
              <div className="fm-kpi">
                <div className="fm-kpi-label">Net Curtailment</div>
                <div className="fm-kpi-value fm-negative">-{fmtPctRaw(curtailmentPct)}</div>
              </div>
            </div>

            {/* Revenue Waterfall */}
            <div className="gc-section">
              <div className="gc-section-header">
                <span className="gc-section-title">Revenue Waterfall</span>
                <span className="gc-section-badge">Year 1</span>
              </div>
              <div className="fm-chart-wrap">
                {revenueData && <RevenueWaterfallChart data={revenueData} />}
              </div>
            </div>

            {/* Monthly Revenue Profile */}
            <div className="gc-section">
              <div className="gc-section-header">
                <span className="gc-section-title">PPA Price Trajectory</span>
              </div>
              <div className="fm-ppa-trajectory">
                {[1, 5, 10, 15, 20, 25].filter(y => y <= lifetime).map(yr => {
                  const price = ppaPrice * Math.pow(1 + escalation / 100, yr - 1);
                  return (
                    <div key={yr} className="fm-ppa-yr">
                      <span className="fm-ppa-yr-label">Year {yr}</span>
                      <span className="fm-ppa-yr-price">{`\u00A3${price.toFixed(1)}`}/MWh</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </>
        )}

        {/* ═══════════════════════════════════════════════════════════
            TAB 4: Sensitivity
           ═══════════════════════════════════════════════════════════ */}
        {activeTab === "sensitivity" && (
          <>
            {/* 2D Sensitivity Table */}
            <div className="gc-section">
              <div className="gc-section-header">
                <span className="gc-section-title">IRR Sensitivity Matrix</span>
                <span className="gc-section-badge">CAPEX vs Revenue</span>
              </div>
              {sensitivity && (
                <div className="fm-sens-table-wrap">
                  <table className="fm-sens-table">
                    <thead>
                      <tr>
                        <th className="fm-sens-corner">Rev \ Cap</th>
                        {sensitivity.capexRange.map(c => (
                          <th key={c}>{c > 0 ? "+" : ""}{c}%</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {sensitivity.rows.map(row => (
                        <tr key={row.revDelta}>
                          <td className="fm-sens-row-label">{row.revDelta > 0 ? "+" : ""}{row.revDelta}%</td>
                          {row.cells.map((cell, i) => (
                            <td key={i} className={`fm-sens-cell ${sensClass(cell.irr)} ${cell.capexDelta === 0 && cell.revDelta === 0 ? "fm-sens-base" : ""}`}>
                              {fmtPct(cell.irr)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Tornado Chart */}
            <div className="gc-section">
              <div className="gc-section-header">
                <span className="gc-section-title">Tornado Chart</span>
                <span className="gc-section-badge">Top 10 Drivers</span>
              </div>
              <div className="fm-chart-wrap">
                {tornado && <TornadoChart data={tornado} />}
              </div>
            </div>

            {/* Scenario toggles */}
            <div className="gc-section">
              <div className="gc-section-header">
                <span className="gc-section-title">Scenario Analysis</span>
              </div>
              <div className="fm-scenario-btns">
                {[
                  { id: "optimistic", label: "Optimistic", ppa: ppaPrice * 1.15, capex: 0.9 },
                  { id: "central", label: "Central", ppa: ppaPrice, capex: 1.0 },
                  { id: "conservative", label: "Conservative", ppa: ppaPrice * 0.85, capex: 1.1 },
                ].map(s => {
                  const scenParams = {
                    ...modelParams,
                    ppaPrice: s.ppa,
                    modulesCost: modelParams.modulesCost * s.capex,
                    bosCost: modelParams.bosCost * s.capex,
                    epcCost: modelParams.epcCost * s.capex,
                  };
                  const scenResult = buildCashflow(scenParams);
                  return (
                    <div key={s.id} className={`fm-scenario-card ${scenario === s.id ? "active" : ""}`}
                      onClick={() => setScenario(s.id)}>
                      <div className="fm-scenario-name">{s.label}</div>
                      <div className={`fm-scenario-irr ${irrClass(scenResult.irr)}`}>{fmtPct(scenResult.irr)}</div>
                      <div className="fm-scenario-meta">
                        NPV {fmtGbp(scenResult.npv)} | Payback {scenResult.paybackYear || ">25"} yrs
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Footer */}
      <div className="fm-footer">
        <span>Princeps Financial Model</span>
        <span>{capacityMw} MW {TECH_BENCHMARKS[technology]?.label}</span>
      </div>
    </div>
  );
}
