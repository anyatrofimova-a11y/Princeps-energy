/**
 * GridParticleFlow — GPU-accelerated particle system for GridTwin.
 *
 * Renders thousands of particles flowing along transmission line arcs
 * using deck.gl ScatterplotLayer with animated positions computed per-frame.
 *
 * Each transmission line spawns N particles proportional to |flow_mw|.
 * Particles follow a great-circle arc path with height proportional to loading.
 * Speed is proportional to flow magnitude. Color by voltage level.
 *
 * This replaces the dash-animated ArcLayer for a much more visceral effect.
 */
import { ScatterplotLayer } from "@deck.gl/layers";

// Interpolate along a 3D arc between two [lon,lat] points
function arcPoint(from, to, t, height) {
  const lon = from[0] + (to[0] - from[0]) * t;
  const lat = from[1] + (to[1] - from[1]) * t;
  // Parabolic arc: max height at t=0.5
  const elev = height * 4 * t * (1 - t);
  return [lon, lat, elev];
}

const VOLTAGE_PARTICLE_COLORS = {
  400: [255, 80, 80, 220],
  275: [255, 180, 60, 200],
  132: [60, 160, 255, 200],
  66: [80, 200, 120, 180],
  33: [180, 80, 220, 180],
  11: [180, 180, 180, 160],
};

function particleColor(kv) {
  if (kv >= 400) return VOLTAGE_PARTICLE_COLORS[400];
  if (kv >= 275) return VOLTAGE_PARTICLE_COLORS[275];
  if (kv >= 132) return VOLTAGE_PARTICLE_COLORS[132];
  if (kv >= 66) return VOLTAGE_PARTICLE_COLORS[66];
  if (kv >= 33) return VOLTAGE_PARTICLE_COLORS[33];
  return VOLTAGE_PARTICLE_COLORS[11];
}

/**
 * Generate particle data from grid lines.
 *
 * @param {Array} lines - Grid lines with from_coords, to_coords, flow_mw, voltage_kv, loading_pct
 * @param {number} phase - Animation phase 0-1 (incremented each frame)
 * @param {number} maxParticlesPerLine - Cap per line
 * @returns {Array} Particle objects with position, color, radius
 */
export function generateParticles(lines, phase, maxParticlesPerLine = 20) {
  if (!lines || !lines.length) return [];

  const particles = [];

  for (const line of lines) {
    const flow = Math.abs(line.flow_mw || 0);
    if (flow < 5) continue; // Skip negligible flows

    const from = line.flow_mw >= 0 ? line.from_coords : line.to_coords;
    const to = line.flow_mw >= 0 ? line.to_coords : line.from_coords;
    const arcH = 8000 + (line.loading_pct || 0) * 200; // meters (deck.gl elevation)
    const color = particleColor(line.voltage_kv || 132);

    // Number of particles proportional to flow, capped
    const count = Math.min(maxParticlesPerLine, Math.max(3, Math.floor(flow / 15)));

    // Speed: faster flow = faster particles
    const speed = 0.3 + flow / 500;

    for (let i = 0; i < count; i++) {
      // Spread particles along the arc with offset
      const baseT = (i / count + phase * speed) % 1;

      // Add slight randomness for natural look (seeded by index)
      const jitter = ((i * 7919 + Math.floor(phase * 100)) % 100) / 10000;
      const t = (baseT + jitter) % 1;

      const pos = arcPoint(from, to, t, arcH);

      // Fade in/out at endpoints
      const edgeFade = Math.min(t * 8, (1 - t) * 8, 1);
      const alpha = color[3] * edgeFade;

      // Size: larger near center of arc, smaller at edges
      const sizeFactor = 0.6 + 0.4 * Math.sin(t * Math.PI);
      const radius = (60 + flow * 0.3) * sizeFactor;

      particles.push({
        position: pos,
        color: [color[0], color[1], color[2], Math.round(alpha)],
        radius,
        lineId: `${line.from}-${line.to}`,
      });
    }
  }

  return particles;
}

/**
 * Create a deck.gl ScatterplotLayer for the particle system.
 */
export function createParticleLayer(lines, phase) {
  const particles = generateParticles(lines, phase);

  return new ScatterplotLayer({
    id: "gt-gpu-particles",
    data: particles,
    getPosition: d => d.position,
    getFillColor: d => d.color,
    getRadius: d => d.radius,
    radiusUnits: "meters",
    radiusMinPixels: 1.5,
    radiusMaxPixels: 6,
    opacity: 0.9,
    pickable: false,
    billboard: true,
    antialiasing: true,
    parameters: {
      depthTest: false, // Always on top
    },
    updateTriggers: {
      getPosition: [phase],
      getFillColor: [phase],
      getRadius: [phase],
    },
  });
}
