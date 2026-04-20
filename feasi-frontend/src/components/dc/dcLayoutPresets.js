/**
 * dcLayoutPresets — Campus layout recipes parametrised by IT load, Tier and
 * cooling type.
 *
 * Replaces the "one big purple box" shell with a structured hyperscaler
 * campus: halls + spine, MV/LV building, genset yard, TX yard, water plant,
 * office/NOC, security gatehouse, loading bay. All dimensions in metres,
 * all positions in a local metres frame with the shell centroid at (0, 0).
 *
 * Reference footprints (sanity-checked against Equinix LD5, Digital Realty
 * LHR-15, Stack LON-1):
 *
 *   IT white space     ~440 m² per MW  (2.5 m² × ~176 racks/MW @ 8 kW/rack,
 *                                        plus hot/cold aisles)
 *   Data hall          1,500-2,500 m² per hall, 4-12 halls per shell
 *   Spine corridor     6 m wide, full shell length
 *   MV/LV building     18 m × (shell_length), 6 m tall — along one shell edge
 *   Genset yard        5 MW gensets at ~100 m² each + 50 m hazard buffer
 *   TX yard            20 MVA transformers at ~150 m² each + 8 m firewalls
 *   Water plant        cooling-type dependent (see _coolingPlantFootprint)
 *   Office / NOC       25 × 15 m (2-storey) near gatehouse
 *   Security gatehouse 12 × 6 m at the entrance
 *   Loading bay        18 × 12 m on MV/LV side
 */

// ── Role colour palette (RGBA). Used by both the 3D meshes and the legend.
export const ROLE_COLOURS = {
  shell:       [58, 58, 64, 235],     // charcoal — shell outline / data halls
  hall:        [219, 188, 126, 230],  // pale gold — IT white-space halls
  spine:       [90, 85, 78, 200],     // muted bronze — central corridor
  mvlv:        [96, 125, 139, 235],   // blue-grey — MV / LV switchgear
  genset:      [46, 87, 53, 235],     // dark green — genset compound
  tx:          [161, 98, 43, 235],    // orange-brown — TX compound
  water:       [41, 121, 201, 230],   // blue — water / chiller plant
  office:      [237, 226, 196, 230],  // cream — office / NOC
  security:    [245, 183, 49, 240],   // amber — gatehouse
  loading:     [120, 110, 96, 230],   // taupe — loading bay / HGV bay
  diesel:      [120, 60, 40, 230],    // rust — diesel bulk tanks
  fence:       [156, 163, 175, 200],  // grey — perimeter fence
};

// ── Human labels + dominant-purpose strings (shown in legend + inspector).
export const ROLE_META = {
  shell:    { label: "Shell envelope",   purpose: "Outer roof line / GFA" },
  hall:     { label: "Data halls",       purpose: "IT white space (racks)" },
  spine:    { label: "Central spine",    purpose: "Cabling / MEP corridor" },
  mvlv:     { label: "MV / LV building", purpose: "Switchgear + UPS" },
  genset:   { label: "Genset yard",      purpose: "Standby diesel (N+1)" },
  tx:       { label: "Transformer yard", purpose: "33/132 kV step-down" },
  water:    { label: "Water plant",      purpose: "Chillers / cooling towers" },
  office:   { label: "Office / NOC",     purpose: "Control + admin (2-storey)" },
  security: { label: "Gatehouse",        purpose: "Access control + ANPR" },
  loading:  { label: "Loading bay",      purpose: "HGV turning + dock" },
  diesel:   { label: "Diesel tanks",     purpose: "Bulk fuel (24-96 h)" },
};

// ── Generator sizing — 5 MW "standard" hyperscale gensets, N+1 redundancy.
function genCount(itLoadMw, redundancy) {
  const perUnitMw = 5;
  const base = Math.ceil(itLoadMw * 1.15 / perUnitMw);  // 15% PUE overhead
  if (redundancy === "2N" || redundancy === "2N+1") return base * 2;
  return base + 1;  // N+1
}

// ── Transformer sizing — 20 MVA units, N+1.
function txCount(itLoadMw, redundancy) {
  const perUnitMva = 20;
  // ~0.95 PF, plus PUE overhead → installed MVA ≈ itMw × 1.25
  const base = Math.ceil(itLoadMw * 1.25 / perUnitMva);
  if (redundancy === "2N" || redundancy === "2N+1") return Math.max(2, base * 2);
  return Math.max(2, base + 1);
}

// ── Data hall count — 1 hall per ~1.5 MW IT load for hyperscale workloads.
function hallCount(itLoadMw) {
  if (itLoadMw <= 5)   return 2;
  if (itLoadMw <= 15)  return 4;
  if (itLoadMw <= 30)  return 6;
  if (itLoadMw <= 60)  return 8;
  if (itLoadMw <= 100) return 10;
  return Math.min(16, Math.ceil(itLoadMw / 8));
}

// ── Water / cooling plant footprint depends on cooling type.
function _coolingPlantFootprint(itLoadMw, coolingType) {
  const t = coolingType || "hybrid";
  // m² per MW IT load
  const perMw = {
    mechanical:   55,    // chillers only
    free_cooling: 35,    // air-side economiser
    hybrid:       50,    // chillers + economiser
    evaporative:  65,    // cooling towers (bigger footprint)
    // D2-vocabulary aliases (InsiderDCDesign → DCDesignTwin)
    a2_dry:       30,
    a3_evap:      55,
    l2c:          45,
    immersion_1p: 25,
    immersion_2p: 25,
  }[t] ?? 50;
  const area = Math.max(250, itLoadMw * perMw);
  // cooling towers are long-and-thin, chillers are more square
  const aspect = (t === "evaporative" || t === "a3_evap") ? 2.0 : 1.4;
  const width = Math.sqrt(area * aspect);
  const depth = area / width;
  const height = (t === "evaporative" || t === "a3_evap") ? 9 : 5;
  return { width, depth, area, height };
}

/**
 * Build the campus layout recipe.
 *
 * All rectangles returned in a **local metres frame** with the shell
 * centroid at (0, 0). `+x` = east, `+y` = north. The caller (DCDesignTwin)
 * projects into lon/lat before handing to deck.gl.
 *
 * @param {object} opts
 * @param {number} opts.itLoadMw
 * @param {number} opts.tier             1–4
 * @param {string} opts.redundancy       "N" | "N+1" | "2N" | "2N+1"
 * @param {string} [opts.coolingType]    "mechanical" | "free_cooling" | "hybrid" | "evaporative" | D2 key
 * @returns {object} layout recipe with keys: shell, halls[], spine, mvlv,
 *                   genset, gensets[], dieselTanks[], tx, transformers[],
 *                   water, office, security, loading, fence, bbox
 */
export function buildCampusLayout({
  itLoadMw = 50,
  tier = 3,
  redundancy = "N+1",
  coolingType = "hybrid",
}) {
  const mw = Math.max(1, itLoadMw);

  // ── Shell sizing ──
  // ~440 m² IT white space + 40% support space ≈ 615 m²/MW total
  // Arranged as a long rectangle (hall row + spine + MV/LV along one side)
  const shellArea = mw * 615;
  // aspect ratio — halls in a row, so shell length >> shell depth
  const halls = hallCount(mw);
  const hallDepth = Math.min(45, 30 + mw * 0.2);          // 30-45 m
  const hallLength = Math.max(30, Math.sqrt((shellArea * 0.7) / halls / (hallDepth / 45)));
  const spineWidth = 6;                                    // central corridor
  const mvlvDepth = 18;                                    // MV/LV strip
  const shellDepth = hallDepth * 2 + spineWidth + mvlvDepth; // two hall rows on either side of spine
  const shellLength = Math.max(60, halls / 2 * hallLength + 20);  // +20 m for end plant rooms
  const shellHeight = Math.min(22, 14 + mw * 0.12);

  // ── Halls — two rows of hallCount/2 on either side of the spine.
  // North row has +y, south row has -y (both offset from centre).
  const hallsArr = [];
  const hallsPerRow = Math.ceil(halls / 2);
  const hallPitch = (shellLength - 20) / hallsPerRow;  // leave 10 m end-margin each side
  const hallLen = hallPitch - 2;                       // 2 m between halls for fire cell walls
  for (let row = 0; row < 2; row++) {
    const yCentre = (row === 0 ? 1 : -1) * (spineWidth / 2 + hallDepth / 2);
    for (let i = 0; i < hallsPerRow; i++) {
      if (row * hallsPerRow + i >= halls) break;
      const xCentre = -((shellLength - 20) / 2) + (i + 0.5) * hallPitch;
      hallsArr.push({
        key: `hall_${row}_${i}`,
        role: "hall",
        cx: xCentre, cy: yCentre,
        width: hallLen, depth: hallDepth,
        height: shellHeight - 1,                   // just below shell roof
        label: `Hall ${row * hallsPerRow + i + 1}`,
      });
    }
  }

  // ── Central spine — runs the length of the shell between the two hall rows.
  const spine = {
    key: "spine",
    role: "spine",
    cx: 0, cy: 0,
    width: shellLength - 20, depth: spineWidth,
    height: shellHeight - 2,
    label: "MEP spine",
  };

  // ── MV/LV building — along the shell's south edge (past the south hall row).
  const mvlv = {
    key: "mvlv",
    role: "mvlv",
    cx: 0,
    cy: -(spineWidth / 2 + hallDepth + mvlvDepth / 2),
    width: shellLength - 20, depth: mvlvDepth,
    height: 7,
    label: "MV / LV switchgear + UPS",
  };

  // ── Shell envelope — the outer footprint the halls+spine+MVLV sit inside.
  // Drawn as a thin wire outline only (no fill) so the halls dominate visually.
  const shell = {
    key: "shell",
    role: "shell",
    cx: 0,
    cy: -mvlvDepth / 2,      // centred on halls+MV/LV combined extent
    width: shellLength, depth: shellDepth,
    height: shellHeight,
    area: shellLength * shellDepth,
    hallCount: halls,
    itAreaM2: mw * 440,
  };

  // ── Genset yard — separate fenced compound to the east of the shell.
  const nGen = genCount(mw, redundancy);
  const gensetUnitLen = 12;   // 5 MW genset container ~12 × 3 m + radiator
  const gensetUnitDepth = 5;
  const gensetSpacing = 4;    // fire separation between units
  const gensetYardLen = nGen * (gensetUnitLen + gensetSpacing) + 8;
  const gensetYardDepth = gensetUnitDepth + 25;  // +25 m for diesel tanks behind
  const gensetBuffer = 50;     // 50 m hazard buffer from shell
  const gensetCx = shellLength / 2 + gensetBuffer + gensetYardLen / 2;
  const gensetCy = 0;
  const genset = {
    key: "genset_yard",
    role: "genset",
    cx: gensetCx, cy: gensetCy,
    width: gensetYardLen, depth: gensetYardDepth,
    height: 0.5,   // flat concrete pad (meshes on top)
    area: gensetYardLen * gensetYardDepth,
    label: `Genset yard (${nGen} × 5 MW)`,
  };
  const gensets = [];
  const gensetRowY = gensetCy + gensetYardDepth / 2 - gensetUnitDepth / 2 - 2;
  for (let i = 0; i < nGen; i++) {
    const xCentre = gensetCx - gensetYardLen / 2 + 4 + (i + 0.5) * (gensetUnitLen + gensetSpacing);
    gensets.push({
      key: `gen_${i}`,
      role: "genset",
      cx: xCentre, cy: gensetRowY,
      width: gensetUnitLen, depth: gensetUnitDepth,
      height: 4.5,
      label: `Genset #${i + 1} · 5 MW`,
    });
  }
  // Diesel bulk tanks (cylindrical-ish — approximated as squat boxes) behind gensets
  const dieselTanks = [];
  const tankPitch = Math.ceil(nGen / 2);
  for (let i = 0; i < tankPitch; i++) {
    const xCentre = gensetCx - gensetYardLen / 2 + 8 + i * (gensetYardLen - 16) / Math.max(1, tankPitch - 1);
    dieselTanks.push({
      key: `tank_${i}`,
      role: "diesel",
      cx: xCentre,
      cy: gensetCy - gensetYardDepth / 2 + 6,
      width: 6, depth: 6, height: 4,
      label: `Diesel tank #${i + 1}`,
    });
  }

  // ── Transformer yard — separate fenced compound to the west of the shell.
  const nTx = txCount(mw, redundancy);
  const txUnitSide = 9;
  const txSpacing = 8;   // 8 m fire-wall separation between transformers
  const txYardLen = nTx * (txUnitSide + txSpacing) + 10;
  const txYardDepth = txUnitSide + 14;  // access bay behind
  const txBuffer = 20;
  const txCx = -(shellLength / 2 + txBuffer + txYardLen / 2);
  const txCy = 0;
  const tx = {
    key: "tx_yard",
    role: "tx",
    cx: txCx, cy: txCy,
    width: txYardLen, depth: txYardDepth,
    height: 0.5,
    area: txYardLen * txYardDepth,
    label: `Transformer yard (${nTx} × 20 MVA)`,
  };
  const transformers = [];
  for (let i = 0; i < nTx; i++) {
    const xCentre = txCx - txYardLen / 2 + 8 + (i + 0.5) * (txUnitSide + txSpacing);
    transformers.push({
      key: `tx_${i}`,
      role: "tx",
      cx: xCentre, cy: txCy + 2,
      width: txUnitSide, depth: txUnitSide,
      height: 5.5,
      label: `Transformer #${i + 1} · 20 MVA`,
    });
  }

  // ── Water plant — north of the shell (opposite side from MV/LV).
  const waterFp = _coolingPlantFootprint(mw, coolingType);
  const water = {
    key: "water",
    role: "water",
    cx: 0,
    cy: spineWidth / 2 + hallDepth + 10 + waterFp.depth / 2,
    width: waterFp.width, depth: waterFp.depth,
    height: waterFp.height,
    area: waterFp.area,
    label: "Water / cooling plant",
  };

  // ── Office / NOC — 2-storey block at south-west corner (entrance side).
  const office = {
    key: "office",
    role: "office",
    cx: -(shellLength / 2 - 18),
    cy: -(spineWidth / 2 + hallDepth + mvlvDepth + 18),
    width: 28, depth: 16, height: 7,
    area: 28 * 16,
    label: "Office / NOC (2-storey)",
  };

  // ── Security gatehouse — right at entrance (south).
  const security = {
    key: "security",
    role: "security",
    cx: -(shellLength / 2 - 40),
    cy: -(spineWidth / 2 + hallDepth + mvlvDepth + 32),
    width: 12, depth: 6, height: 3,
    area: 12 * 6,
    label: "Security gatehouse",
  };

  // ── Loading bay — on the MV/LV (south) side of the shell, toward east end.
  const loading = {
    key: "loading",
    role: "loading",
    cx: shellLength / 2 - 14,
    cy: -(spineWidth / 2 + hallDepth + mvlvDepth + 10),
    width: 20, depth: 14, height: 5,
    area: 20 * 14,
    label: "Loading bay / HGV dock",
  };

  // ── Site fence — wraps every compound with a 5 m vehicle setback.
  // Compute bounding box of all compounds (shell + genset + tx + water + office + loading).
  const all = [shell, genset, tx, water, office, security, loading];
  let minX = +Infinity, maxX = -Infinity, minY = +Infinity, maxY = -Infinity;
  all.forEach(c => {
    minX = Math.min(minX, c.cx - c.width / 2);
    maxX = Math.max(maxX, c.cx + c.width / 2);
    minY = Math.min(minY, c.cy - c.depth / 2);
    maxY = Math.max(maxY, c.cy + c.depth / 2);
  });
  const fenceMargin = 8;
  const fence = {
    key: "fence",
    role: "fence",
    cx: (minX + maxX) / 2,
    cy: (minY + maxY) / 2,
    width: (maxX - minX) + 2 * fenceMargin,
    depth: (maxY - minY) + 2 * fenceMargin,
    height: 3.5,
  };

  return {
    shell,
    halls: hallsArr,
    spine,
    mvlv,
    genset,
    gensets,
    dieselTanks,
    tx,
    transformers,
    water,
    office,
    security,
    loading,
    fence,
    bbox: { minX, maxX, minY, maxY },
    meta: {
      itLoadMw: mw,
      tier,
      redundancy,
      coolingType,
      hallCount: halls,
      genCount: nGen,
      txCount: nTx,
      shellArea: shell.area,
      shellHeight,
    },
  };
}
