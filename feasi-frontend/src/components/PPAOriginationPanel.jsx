import React, { useState, useCallback } from "react";
import { useSite } from "../SiteContext";
import api from "../services/api";

const BUYER_TYPES = [
  { id: "corporate", label: "Corporate" },
  { id: "utility", label: "Utility" },
  { id: "trader", label: "Trader" },
  { id: "data_centre", label: "Data Centre" },
];

const PPA_STRUCTURES = [
  { id: "fixed", label: "Fixed Price", desc: "Locked price for full tenor" },
  { id: "indexed", label: "Indexed", desc: "CPI/RPI-linked escalation" },
  { id: "cppa", label: "CPPA", desc: "Corporate PPA with sleeving" },
  { id: "virtual", label: "Virtual PPA", desc: "Financial contract, no physical delivery" },
];

const TECHNOLOGIES = ["solar", "wind", "bess", "hybrid"];

function fmtGbp(v) {
  if (v == null) return "--";
  return `£${v.toFixed(1)}/MWh`;
}

function creditBadge(rating) {
  const colors = { A: "#24a148", "BBB": "#F5B731", "BB": "#E8A012", B: "#da1e28" };
  return (
    <span className="po-credit" style={{ background: colors[rating] || "#6B7280" }}>
      {rating || "--"}
    </span>
  );
}

export default function PPAOriginationPanel({ onClose, embedded }) {
  const { samCapacity, explain } = useSite();
  const [buyerType, setBuyerType] = useState("corporate");
  const [technology, setTechnology] = useState("solar");
  const [capacityMw, setCapacityMw] = useState(() => Math.round((samCapacity || 50000) / 1000));
  const [structure, setStructure] = useState("fixed");
  const [loading, setLoading] = useState(false);
  const [matches, setMatches] = useState(null);
  const [priceEstimate, setPriceEstimate] = useState(null);

  const findMatches = useCallback(async () => {
    setLoading(true);
    try {
      const [matchRes, priceRes] = await Promise.all([
        api.ppa.match({ capacity_mw: capacityMw, technology, buyer_type: buyerType, structure }),
        api.ppa.priceEstimate({ capacity_mw: capacityMw, technology, structure }),
      ]);
      setMatches(matchRes?.buyers || matchRes?.matches || []);
      setPriceEstimate(priceRes);
    } catch (e) {
      console.warn("[PPA] Match failed:", e);
    } finally {
      setLoading(false);
    }
  }, [capacityMw, technology, buyerType, structure]);

  const expressInterest = useCallback((buyer) => {
    console.log("[PPA] Express interest:", { buyer, capacityMw, technology, structure });
  }, [capacityMw, technology, structure]);

  return (
    <div className="po-panel">
      {!embedded && (
        <div className="po-header">
          <span className="po-title">PPA Origination</span>
          <button className="po-close" onClick={onClose}>&times;</button>
        </div>
      )}

      <div className="po-body">
        {/* Inputs */}
        <div className="po-section">
          <label className="po-label">Technology</label>
          <div className="po-chips">
            {TECHNOLOGIES.map(t => (
              <button key={t} className={`po-chip${technology === t ? " active" : ""}`}
                onClick={() => setTechnology(t)}>{t}</button>
            ))}
          </div>

          <div className="po-row">
            <div className="po-field">
              <label className="po-label">Capacity (MW)</label>
              <input type="number" className="po-input" value={capacityMw}
                onChange={e => setCapacityMw(+e.target.value)} min={1} max={2000} />
            </div>
            <div className="po-field">
              <label className="po-label">Buyer Type</label>
              <select className="po-select" value={buyerType}
                onChange={e => setBuyerType(e.target.value)}>
                {BUYER_TYPES.map(b => <option key={b.id} value={b.id}>{b.label}</option>)}
              </select>
            </div>
          </div>

          <label className="po-label">PPA Structure</label>
          <div className="po-structures">
            {PPA_STRUCTURES.map(s => (
              <button key={s.id}
                className={`po-struct-btn${structure === s.id ? " active" : ""}`}
                onClick={() => setStructure(s.id)}>
                <span className="po-struct-name">{s.label}</span>
                <span className="po-struct-desc">{s.desc}</span>
              </button>
            ))}
          </div>

          <button className="po-btn-primary" onClick={findMatches} disabled={loading}>
            {loading ? "Searching..." : "Find Matches"}
          </button>
        </div>

        {/* Price Estimate */}
        {priceEstimate && (
          <div className="po-section po-price-box">
            <div className="po-price-label">Market Price Estimate</div>
            <div className="po-price-range">
              <span className="po-price-lo">{fmtGbp(priceEstimate.low)}</span>
              <span className="po-price-mid">{fmtGbp(priceEstimate.mid)}</span>
              <span className="po-price-hi">{fmtGbp(priceEstimate.high)}</span>
            </div>
            <div className="po-price-labels">
              <span>P10</span><span>P50</span><span>P90</span>
            </div>
          </div>
        )}

        {/* Results */}
        {matches && matches.length > 0 && (
          <div className="po-section">
            <div className="po-results-title">{matches.length} Potential Buyers</div>
            {matches.map((b, i) => (
              <div key={i} className="po-buyer-card">
                <div className="po-buyer-top">
                  <span className="po-buyer-name">{b.name || `Buyer ${i + 1}`}</span>
                  {creditBadge(b.credit_rating)}
                </div>
                <div className="po-buyer-meta">
                  <span>{b.type || buyerType}</span>
                  <span>{b.price_low && b.price_high ? `${fmtGbp(b.price_low)} - ${fmtGbp(b.price_high)}` : "--"}</span>
                  <span>{b.tenor_years ? `${b.tenor_years}yr tenor` : "--"}</span>
                </div>
                <button className="po-btn-sm" onClick={() => expressInterest(b)}>
                  Express Interest
                </button>
              </div>
            ))}
          </div>
        )}
        {matches && matches.length === 0 && (
          <div className="po-empty">No matching buyers found. Try adjusting filters.</div>
        )}
      </div>
    </div>
  );
}
