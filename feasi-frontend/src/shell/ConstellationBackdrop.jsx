import {useMemo} from 'react';

/**
 * Subtle network-graph backdrop for the v2 shell — matches the original
 * Mission Control hero. Procedurally generated nodes + sparse edges,
 * rendered as a single inline SVG that fills the shell behind everything.
 *
 * Deterministic with a fixed seed so layouts don't shimmer between
 * renders. Pure CSS opacity, no animation — the backdrop is decorative
 * only; never receives pointer events.
 */
export function ConstellationBackdrop() {
  const {nodes, edges} = useMemo(() => buildGraph(), []);

  return (
    <svg
      className="px2-constellation"
      preserveAspectRatio="none"
      viewBox="0 0 100 60"
      aria-hidden
    >
      {edges.map(([i, j], k) => (
        <line
          key={k}
          x1={nodes[i].x} y1={nodes[i].y}
          x2={nodes[j].x} y2={nodes[j].y}
          className="px2-constellation-edge"
        />
      ))}
      {nodes.map((n, i) => (
        <circle
          key={i}
          cx={n.x} cy={n.y}
          r={n.r}
          className={`px2-constellation-node${n.gold ? ' is-gold' : ''}`}
        />
      ))}
    </svg>
  );
}

function buildGraph() {
  // Tiny seeded PRNG so the layout is stable across renders.
  let s = 1729;
  const rng = () => { s = (s * 9301 + 49297) % 233280; return s / 233280; };
  const N = 60;
  const nodes = Array.from({length: N}, () => ({
    x: rng() * 100,
    y: rng() * 60,
    r: 0.18 + rng() * 0.18,
    gold: rng() < 0.08,  // ~5 gold accents scattered
  }));
  const edges = [];
  for (let i = 0; i < N; i++) {
    for (let j = i + 1; j < N; j++) {
      const d = Math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y);
      if (d < 9) edges.push([i, j]);
    }
  }
  return {nodes, edges};
}
