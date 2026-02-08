import React from "react";
import { useSite } from "../../SiteContext";
import MetricCard from "../ui/MetricCard";

export default function DeferralCard() {
  const { deferral, loadMw, setLoadMw, genMw, setGenMw, runDeferral } = useSite();

  return (
    <MetricCard title="Deferral" accentColor="#607d8b">
      <div className="inline-controls">
        <label>Load <input type="number" value={loadMw} onChange={e => setLoadMw(Number(e.target.value))} style={{ width: 45 }} min={0} /> MW</label>
        <label>Gen <input type="number" value={genMw} onChange={e => setGenMw(Number(e.target.value))} style={{ width: 45 }} min={0} /> MW</label>
        <button onClick={() => runDeferral(loadMw, genMw)}>Run</button>
      </div>
      {deferral ? (
        <div className="deferral-table-wrap">
          <table className="deferral-table">
            <thead><tr><th>Node</th><th>Capacity</th><th>Load kW</th><th>Gen kW</th></tr></thead>
            <tbody>
              {Object.entries(deferral.allocations || {}).map(([nid, a]) => (
                <tr key={nid}>
                  <td>{nid}</td>
                  <td>{a.capacity_kw ? `${(a.capacity_kw / 1000).toFixed(0)} MVA` : "\u2014"}</td>
                  <td>{a.load_kw?.toFixed(1)}</td>
                  <td>{a.gen_kw?.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <span className="muted">Click Run</span>}
    </MetricCard>
  );
}
