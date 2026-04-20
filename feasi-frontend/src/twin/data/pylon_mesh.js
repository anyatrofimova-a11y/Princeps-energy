/**
 * Procedural UK lattice pylon geometry.
 *
 * Generates a simple L6-style lattice tower: tapered square trunk plus
 * three cross-arms. Returns a mesh object in the shape deck.gl's
 * SimpleMeshLayer expects: { positions: Float32Array, indices: Uint32Array }
 * with positions in LOCAL metres (Y-up) around origin at tower base.
 *
 * Shared single geometry — SimpleMeshLayer instances it per tower.
 * No licence — procedural.
 */

function line(pts, a, b, idx) {
  // emit a very thin triangle strip ("line") by duplicating the edge;
  // SimpleMeshLayer does not render GL_LINES, so we make a 2-triangle quad
  // with a tiny lateral offset (~5 cm) — visually a wire at twin scale.
  const off = 0.05;
  const dx = b[0] - a[0];
  const dz = b[2] - a[2];
  const len = Math.hypot(dx, dz) || 1;
  const nx = -dz / len;
  const nz = dx / len;
  const base = pts.length / 3;
  pts.push(
    a[0] - nx * off, a[1], a[2] - nz * off,
    a[0] + nx * off, a[1], a[2] + nz * off,
    b[0] + nx * off, b[1], b[2] + nz * off,
    b[0] - nx * off, b[1], b[2] - nz * off,
  );
  idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
}

function makePylonMesh({ height = 45, baseWidth = 8, topWidth = 2, arms = [0.55, 0.75, 0.92] } = {}) {
  const pts = [];
  const idx = [];
  // Four trunk legs (vertical tapered).
  const corners = [
    [1, 1], [-1, 1], [-1, -1], [1, -1],
  ];
  for (let i = 0; i < 4; i++) {
    const [cx, cz] = corners[i];
    line(pts, [cx * baseWidth / 2, 0, cz * baseWidth / 2], [cx * topWidth / 2, height, cz * topWidth / 2], idx);
    // Horizontal bracing at 4 levels.
    for (let lv = 1; lv <= 4; lv++) {
      const t0 = (lv - 1) / 4;
      const t1 = lv / 4;
      const w0 = baseWidth / 2 + (topWidth / 2 - baseWidth / 2) * t0;
      const w1 = baseWidth / 2 + (topWidth / 2 - baseWidth / 2) * t1;
      const next = corners[(i + 1) % 4];
      line(
        pts,
        [cx * w0, height * t0, cz * w0],
        [next[0] * w1, height * t1, next[1] * w1],
        idx,
      );
    }
  }
  // Cross-arms: three horizontal beams near the top carrying conductors.
  for (const armT of arms) {
    const y = height * armT;
    const span = baseWidth * 1.6;
    line(pts, [-span / 2, y, 0], [span / 2, y, 0], idx);
  }
  return {
    positions: new Float32Array(pts),
    indices: new Uint32Array(idx),
  };
}

let _cached = null;
export function getPylonMesh(params) {
  if (_cached && !params) return _cached;
  const mesh = makePylonMesh(params);
  if (!params) _cached = mesh;
  return mesh;
}
