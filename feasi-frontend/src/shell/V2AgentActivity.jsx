import {useState, useEffect, useRef} from 'react';

/**
 * V2 agent activity band — a single living line that rotates through
 * recent agent activities, sibling to V2LiveTape. Conveys that Princeps
 * is a live multi-agent system, not a static dashboard.
 *
 * v1: static rotating fixtures (every 4s, crossfade). Drop-in upgrade
 * path: replace `FIXTURES` with a fetch from `/api/agent/activity`
 * inside the existing interval — same shape ({actor, verb, body}).
 *
 *   ● Pandapower  load-flow completed for Slough Hyperscale DC…   12 events / min
 */

const FIXTURES = [
  {actor: 'Princeps AI',verb: 'reasoning across',    body: '47,832 grid nodes for Thames BESS'},
  {actor: 'Council',    verb: 'reviewed',            body: 'Lower Farm Drointon BNG status — verdict: GO'},
  {actor: 'Pandapower', verb: 'load-flow completed for', body: 'Slough Hyperscale DC — 72 MW firm headroom confirmed'},
  {actor: 'Princeps AI',verb: 'cross-referencing',   body: '1.2M REPD planning decisions for Pembroke BESS'},
  {actor: 'NESO Watch', verb: 'monitoring',          body: 'TEC register for queue-position changes — 4 projects'},
  {actor: 'OSGB36',     verb: 'reprojection cache warmed across', body: '348 LPA boundaries'},
  {actor: 'DTDL',       verb: 'ontology graph loaded —', body: '47k nodes, 218k edges'},
  {actor: 'SAM',        verb: 'PV yield simulated for', body: 'Pembroke 49.9 MW — 1,058 kWh/kWp/yr'},
  {actor: 'Council',    verb: 'verdict issued —',    body: 'CAUTION on Pembroke BESS (Grid Tier-2 headroom marginal)'},
  {actor: 'GeeFlow',    verb: 'DynamicWorld land use sampled for', body: 'Thames BESS candidate parcel — 92% pasture'},
  {actor: 'Pandapower', verb: 'N-1 contingency run on', body: 'Slough 132 kV — no thermal limits breached'},
  {actor: 'Princeps AI',verb: 'drafted DNO engagement letter for', body: 'SSEN — Drointon connection'},
  {actor: 'Planning ML', verb: 'predicted approval likelihood for', body: 'Pembroke BESS — 0.81 (XGBoost on 1.2M REPD)'},
  {actor: 'BMRS',       verb: 'demand outturn synced —', body: '24.1 GW national, +0.4 GW vs forecast'},
];

export default function V2AgentActivity() {
  const [idx, setIdx] = useState(0);
  const [fade, setFade] = useState('in');
  const [evtPerMin, setEvtPerMin] = useState(() => 9 + Math.floor(Math.random() * 6));
  const rotRef = useRef(null);
  const epmRef = useRef(null);

  useEffect(() => {
    rotRef.current = setInterval(() => {
      setFade('out');
      setTimeout(() => {
        setIdx(i => (i + 1) % FIXTURES.length);
        setFade('in');
      }, 280);
    }, 4000);
    // Wobble the events/min counter slightly so it feels live, not static.
    epmRef.current = setInterval(() => {
      setEvtPerMin(v => Math.max(6, Math.min(22, v + (Math.random() < 0.5 ? -1 : 1))));
    }, 6000);
    return () => {
      clearInterval(rotRef.current);
      clearInterval(epmRef.current);
    };
  }, []);

  const item = FIXTURES[idx];

  return (
    <div className="px2-agent-activity">
      <span className="px2-agent-dot" aria-hidden />
      <span className={`px2-agent-line is-fade-${fade}`}>
        <span className="px2-agent-actor">{item.actor}</span>
        <span className="px2-agent-verb"> {item.verb} </span>
        <span className="px2-agent-body">{item.body}</span>
        <span className="px2-agent-ellipsis">…</span>
      </span>
      <span className="px2-agent-rate" title="agent events per minute">
        <span className="px2-agent-rate-num">{evtPerMin}</span>
        <span className="px2-agent-rate-unit">events / min</span>
      </span>
    </div>
  );
}
