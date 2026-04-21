# Connection Nodes — Associated Network Visualisation Spec

_Council: COUNCIL-CN · Read-only audit · 2026-04-19_

## 0. Problem

Clicking a substation in the Grid Graph (Map / Graph sub-view) today opens
`GridAssetDrawer` with a rich 8-tab payload, but the **map itself goes
silent** — nothing on the map indicates what is electrically or
geographically related to the clicked node. The `connections` tab lists
circuits, adjacent substations, and connected generators as prose, with
no visual join back to the map. A developer scoping a connection point
has to mentally reconstruct the local topology from text.

Goal: on every substation click, the map (or an adjacent mini-graph)
shows the **associated network** — the set of things that matter for
"can I connect here, and what else depends on this node".

---

## 1. What "Associated Nodes" Means — 6 Relationships

We decompose "associated" into six distinct relationships. They differ
in **physical meaning**, **typical result size**, **cost to compute**,
and **what a user reads from them**. Mixing them into one overlay would
be information-dead.

| # | Relationship               | Meaning                                                                                    | Backend source                                                                              | Typical size | Render style                          |
| - | -------------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------- | ------------ | ------------------------------------- |
| 1 | **Electrical neighbours** (1-hop) | Every substation directly wired to this one via `grid_lines`.                        | `detail.connections.circuits` (already in enriched payload) — derived from `grid_lines`     | 0–10         | Thicken edges in gold, glow endpoint subs |
| 2 | **Feeder upstream** (to GSP)      | BFS back through circuits until a `GridSupplyPoint` / `BulkSupplyPoint` is reached.   | `GET /grid/cim/circuit/{id}?depth=N` (Neo4j) — currently thin (see §2); Postgres recursive CTE on `grid_lines` is the fallback | 3–8 hops     | Directed chain in gold, arrowheads pointing UP |
| 3 | **Circuit downstream**            | All lower-voltage substations/feeders powered from this one.                          | `GET /grid/cim/downstream/{id}` (Neo4j) OR recursive CTE on `grid_lines` by voltage rule   | 0–50+        | Fan-out tree in muted gold, dotted  |
| 4 | **Queue at this node**            | Accepted + applied ECR/TEC projects whose `substation_id = this`.                     | `detail.queue.accepted` / `detail.queue.applied` (already in payload) + `grid_ecr` / `eso_tec_register` | 0–40         | Triangle icons stacked north of node  |
| 5 | **Adjacent capacity** (geo)       | Other substations within N km — NOT electrically connected, but relevant for siting. | `detail.connections.adjacent_substations` (already in payload — PostGIS `ST_DWithin`)      | 0–8 (capped) | Dashed faint circles, capacity labels |
| 6 | **Voltage-domain peers**          | Same-voltage substations in same DNO / licence area (peer benchmark set).            | New: Postgres `SELECT * FROM grid_substations WHERE voltage_kv=... AND dno=... LIMIT 20`   | 0–20         | Not on map — only in a side-panel chip list |

### Which matter most for the 80% use case

Developer scoping a connection point cares most about (in order):
1. **Electrical neighbours** (what's 1 hop away — do I have headroom next door?)
2. **Feeder upstream** (where does this node sit in the network — at the end of a 33 kV feeder with no BSP nearby? that's a risk)
3. **Queue at this node** (am I standing behind 12 competing projects?)
4. **Adjacent capacity** (if THIS node is full, is there a viable alternate?)
5. Downstream / peers (less common — more for network-planning personas)

---

## 2. Current State Audit

### 2.1 Substation click handler

- **`/Users/anyatrofimova/feasibly/feasi-frontend/src/components/grid-graph/GridGraphContainer.jsx:387`** — list-row click handler sets `selection` state (substation kind, feature.properties shape) and pins `pickedLocation`.
- **`GridGraphContainer.jsx:1143`** — `handleLayerClick` unwraps deck.gl picks; substation kind → `onSelect(sel.feature.properties)` → goes up to the same `handleRowClick`.
- **`gridGraphLayers.js:107`** — dot `onClick` delivers `{ kind: "substation", feature: { properties: object }, lngLat }`.
- **`GridAssetDrawer.jsx:56`** — on substation `id` change, fires `api.grid.substationDetail(id)` → `/api/grid/substation/{id}/detail`.
- **`api.js:109`** — maps to enriched payload via `utils/substation_detail.py :: enriched_substation_detail()`.
- **`utils/substation_detail.py:404-511`** — `_section_connections` populates `circuits` (from `grid_lines`), `adjacent_substations` (PostGIS `ST_DWithin` 20 km, LIMIT 8), `generators_connected` (from `grid_ecr` + `eso_tec_register`). **Note: the SQL selects `s_to.id AS to_id` (line 410) but the Python DROPS it from the response (line 419-425) — only `to_substation` NAME survives.** That is a blocker for any map highlight that wants to match by id.

### 2.2 CIM endpoints in the frontend

Grep result (`cim/circuit|cim/downstream|cim/path|cim/search`):
- **`feasi-frontend/src/services/api.js:109-114`** — functions declared: `api.grid.circuit()`, `circuitSearch`, `circuitPath`, `circuitDownstream`, `circuitHealth`.
- **Zero call sites outside `api.js`**. The helpers are mounted but nothing calls them. A dead API surface.

### 2.3 Ghost-highlight / fade-related features

- Searched `highlight|ghost|dim|fade` across `components/grid-graph/` and `components/GridTwin*`. No existing feature dims the rest of the map or glows a neighbour set. Only mechanics that exist: per-layer `visible` toggle (boolean on/off) and per-layer opacity (constant alpha in `getFillColor`).
- **`GridTwin.jsx:216-228`** has an `ArcLayer` that renders voltage-coloured power flow arcs from `lines`, with arc height = loading. **This is a reusable primitive** — the map-highlight direction could feed its own "related-edges" subset into a second `ArcLayer` that renders above the base and steals visual weight via width + higher alpha. Same for the `ColumnLayer` (substations as 3D columns) in `GridTwin.jsx`. Neither currently reacts to selection — adding a `getLineWidth`/`getFillColor` accessor that checks `isRelated(d)` is the minimum edit.

### 2.4 Neo4j CIM dataset — **biggest surprise**

`GET /grid/cim/health` on local returns `available: true` with 45 043 nodes (9573 Primary + 5004 Secondary substations, 20 984 PowerLines, 2249 Assets) but only **13 184 relationships total**, of which only `HAS_TERMINAL=2439`, `CONNECTED_TO=2439`, `FEEDS=424`, `CONTAINED_IN=190`. Translation: **the traversal edges are largely unpopulated**. Probing the enriched endpoint on real substations returns `nodes: 2, edges: 1` at `depth=3` — a substation + its own busbar and nothing else. Downstream returns `assets: [0]`.

**Implication for this feature:** Relationships 1, 2, 3 (electrical hops) cannot be served by the Neo4j `circuit/downstream/path` endpoints today. They will return empty or near-empty. The Postgres `grid_lines` + `grid_substations` + `grid_ecr` tables are richer and already power the drawer's `connections` section. **Build the map-highlight feature on Postgres-backed data, not Neo4j.** Neo4j can be the Tier-2 enhancement once the `neo4j_graph_populator.py` rerun is finished (see `project_council_bots_session_2026_04_19.md` task #21).

---

## 3. UX Model — **Direction C (Hybrid)** — map highlight + compact sidecar chip strip

**Chosen: C, but weighted toward A.** The map highlight carries the visual weight; the sidecar is a minimal 1-column chip strip, NOT a react-flow graph view.

### Why not pure A

Map-only highlight is elegant but loses the **ranked list** — "show me the 3 adjacent subs sorted by headroom". Users will want to click a specific neighbour, not hunt pixels.

### Why not pure B (full react-flow sidecar)

A react-flow graph next to the drawer creates **three competing visual regions** (map + graph + drawer) and eats horizontal space the drawer is already taking (360 px + 260 px = ~620 px of chrome on a 1440 px laptop). The drawer's `connections` tab already carries the list view — rebuilding it as a graph duplicates effort without adding geographic context, which is the thing the map brings for free.

### Why C (hybrid) wins

- The **map** is already the hero surface. Highlighting on it is zero new UI real estate.
- A **small sidecar rail** (inserted between map and drawer, ~40 px wide) shows stacked chips for each connected node: voltage-coloured dot + 2-letter ID + distance. Hovering a chip pulses the node on the map; clicking re-roots.
- Drawer stays on the right, unchanged, serving its 8 tabs. Its `connections` tab gains a "highlight on map" button per row.

### Wireframe (ASCII)

```
┌────────┬───────────────────────────────────────┬─┬──────────────────┐
│ Grid   │                                       │S│ Asset Drawer     │
│ Assets │       MAPBOX + deck.gl                │i│                  │
│ list   │                                       │d│  Identity        │
│        │   (faded dots for unrelated)          │e│  Electrical      │
│        │   (GOLD dots for electrical           │c│  Capacity        │
│        │    neighbours, BOLD gold              │a│  Connections  ←  │
│        │    edges connecting them,             │r│  Queue           │
│        │    DIRECTED chain gold → up           │ │  Regulatory      │
│        │    to GSP, DASHED circles             │r│  Environment     │
│        │    around geo-adjacent subs)          │a│  Engineering     │
│        │                                       │i│                  │
│        │                                       │l│                  │
│  280px │            ~700px                      │40px      360px    │
└────────┴───────────────────────────────────────┴─┴──────────────────┘
```

### Sidecar rail content (top to bottom)

```
┌────┐
│ •  │  ← selected substation (gold filled)
├────┤
│ ↑  │  FEEDER (1)
│ BR │  Bridgwater GSP 132 kV        12.4 km
├────┤
│ ~  │  NEIGHBOURS (3)
│ AV │  Avonmouth BSP  132 kV         8.1 km
│ BS │  Bradley Stoke BSP 132 kV      14.2 km
│ CA │  Camborne BSP 132 kV          42.1 km
├────┤
│ ↓  │  DOWNSTREAM (12)   [expand]
├────┤
│ ○  │  GEO-ADJACENT (5)  [expand]
├────┤
│ △  │  QUEUE (18)                   click → drawer
└────┘
```

Numbered chip groups. Collapsed by default past the first 3 rows per
section. Voltage-coloured dots use the shared `gridPalette`.

### Reset affordance

Clicking any empty map area, pressing **Esc**, or a dedicated "X clear selection" button in the sidecar header restores the full network view and clears highlights. Clicking the already-selected substation also clears.

---

## 4. Interaction Model

| Control              | Behaviour                                                                                               |
| -------------------- | ------------------------------------------------------------------------------------------------------- |
| **Single click**     | Select node. Fetch neighbourhood at depth=1 (instant) + depth=3 (lazy). Highlight depth-1 immediately. |
| **Shift-click node** | Extend selection — keeps current root, adds this node + its edges to the highlighted set. (Multi-root compare mode.) |
| **Click highlighted neighbour** | Re-root — old root fades back to base style, new root becomes selection.                       |
| **Click empty map**  | Clear selection (same as Esc).                                                                          |
| **Esc key**          | Clear selection + close drawer.                                                                         |
| **Hop-depth slider** | Mounted in the sidecar header: 1 / 2 / 3. Default 2. At 1 = only direct neighbours; at 3 = feeder-chain depth. Refetches on change; results cached per-(id, depth). |
| **Arrow Up / Down**  | Cycle through sidecar chips. Enter = re-root. (Keyboard power-user path.)                              |
| **"Pin to compare"** | Right-click chip → pins it into a parallel sidecar column. Out of scope for v1; document as v2 follow-up. |
| **Touch / mobile**   | Out of scope. The Grid Graph is desktop-only by the existing CSS (`width: 280px` sidebar, no responsive breakpoint). |

---

## 5. Data Model + Performance

### 5.1 Size bounds (empirical + conservative upper bounds)

- 1-hop neighbours: `grid_lines` `LIMIT 30` already capped in `_section_connections`. Real-world max ~10 at 132 kV, ~4 at 33 kV.
- 2-hop: multiply by ~5 average branching → ≤ 50 nodes.
- 3-hop at 400 kV transmission: can explode to 200+ nodes / 400+ edges. Must cap.
- Adjacent-capacity (geo): already `LIMIT 8` at 20 km. Fine.
- Queue at node: `LIMIT 20` per register = ≤ 40 combined.

**Render budget**: deck.gl ScatterplotLayer + PathLayer at 500 features is sub-frame. No perf issue until ~10 000 — we are 2 orders of magnitude below risk.

**Fetch budget**: worst case depth=3, one Postgres recursive CTE returns in ~40 ms on the existing `grid_lines` GIST index. Neo4j Cypher at depth 3 with `*1..12` pattern is 100–200 ms but currently returns empty, so moot.

### 5.2 Caching

- **SessionStorage**: key `grid:neighbourhood:{id}:{depth}` → JSON of `{ nodes, edges, adjacent, queue }`. TTL session-scope; mental model "until tab close".
- **In-memory LRU (size 50)** in a `useGridNeighbourhood(id, depth)` hook, to avoid double-fetch on chip hover + re-click.
- Cache invalidation: on a successful ingest (demand refresh / ECR refresh) the server emits a version header — bump the cache key suffix when it changes. Stretch; not blocking.

### 5.3 Eager vs lazy

**Eager at depth=1, lazy at depth=2+**:
- Depth 1 is already in the enriched detail payload (`connections.circuits` + `adjacent_substations`) — zero new round-trip.
- Depth 2/3 fetched only on slider change. Pre-warm: during `substationDetail` resolution fire-and-forget a depth=3 request so the slider is snappy if used.

### 5.4 Shape the frontend needs

Propose a combined endpoint to avoid assembling 4 calls in the client (see BOT-CN-D brief).

```json
GET /api/grid/neighbourhood/{substation_id}?depth=2
{
  "root": { "id": "...", "name": "...", "voltage_kv": 132, "lat": ..., "lon": ... },
  "electrical_neighbours": [
    { "id": "...", "name": "...", "voltage_kv": ..., "lat": ..., "lon": ...,
      "via_line_id": "...", "length_km": 4.2, "direction": "peer" }
  ],
  "feeder_upstream": [
    { "id": "...", "name": "...", "voltage_kv": 275, "lat": ..., "lon": ...,
      "hop": 1, "asset_type": "BulkSupplyPoint" }
  ],
  "downstream_count": 12,       // expansion on click — don't eager-load
  "geo_adjacent": [ ...at most 8 subs within 20 km, with distance_km... ],
  "queue_count": { "accepted": 4, "applied": 14 },
  "depth_resolved": 2,
  "source": "postgres"          // or "neo4j" when Neo4j graph is full
}
```

---

## 6. Bot Briefs — 3 Disjoint Execution Tickets

### 🧩 BOT-CN-D — Data / API

**Owns**: `app/routers/grid.py` (new handler) + `utils/substation_detail.py` additions. MAY create a small `utils/grid_neighbourhood.py` for the traversal. MUST NOT touch Neo4j code.

**Deliverables**:
1. Add `GET /api/grid/substation/{id}/neighbourhood?depth=N` (N ∈ {1,2,3}, default 2).
2. Build the response by a **recursive CTE on `grid_lines`** that starts at `substation_id` and walks `from_sub_id ↔ to_sub_id` up to `depth`, joining `grid_substations` for coordinates / voltage / DNO on each hop. Cap total rows at 500.
3. Mark edges with a `direction` label: `upstream` (voltage of other end strictly higher than root's voltage), `downstream` (strictly lower), `peer` (same).
4. Include `geo_adjacent` by reusing the existing `_section_connections` PostGIS query.
5. Include `queue_count` aggregates — two counts only, not the full list (frontend already has the list via the drawer payload).
6. **Surface `to_id`/`from_id`** in the existing `_section_connections` circuits response (currently dropped — see §2.1). Purely additive.
7. Verify `/grid/cim/circuit`, `downstream`, `path` respond. Document their empty-state behaviour. Do not build on Neo4j until relationship-fill is done elsewhere.

**Does NOT touch**: any frontend file, `graph_topology.py`, or `gridGraphLayers.js`.

---

### 🧩 BOT-CN-M — Map Highlight (deck.gl)

**Owns**: `feasi-frontend/src/components/grid-graph/GridGraphContainer.jsx` click-handler extension + `gridGraphLayers.js` new layer builder(s). New file `useGridNeighbourhood.js` for the hook + cache.

**Deliverables**:
1. `useGridNeighbourhood(substationId, depth)` hook — fetches `/api/grid/substation/{id}/neighbourhood`, returns `{ data, loading, error }`. SessionStorage-backed cache, LRU 50, TTL 10 min.
2. New `buildNeighbourhoodLayers({ neighbourhood, visible, onClick })` in `gridGraphLayers.js` returning:
   - `grid-neighbourhood-edges` — PathLayer. Width 3 px for gold edges; voltage-coloured only if an option is set (default gold).
   - `grid-neighbourhood-nodes-glow` — ScatterplotLayer above base; radius +2 px, alpha 255, filled gold.
   - `grid-neighbourhood-geo-adjacent` — ScatterplotLayer with dashed stroke (deck.gl's `getLineDashArray` via `@deck.gl/extensions.PathStyleExtension`).
3. Modify existing `buildSubstationsLayer` to accept an optional `dimIds: Set<string>` — when present, unlisted ids drop alpha from 200→60. One-line edit.
4. On click, pass the set of related ids into the base layer as `dimIds`; the clicked id gets the glow layer.
5. Clear affordance: Esc key + click on empty map background + click on selected substation.
6. Sidecar rail component: `NeighbourhoodRail.jsx` — 40-px-wide vertical strip between map and drawer, chips per §3 wireframe. Chip hover → pulse node by boosting its radius for 500 ms.
7. Hop-depth slider at top of sidecar. Triggers re-fetch through the hook.

**Does NOT touch**: backend routers, `GridAssetDrawer.jsx`, Neo4j. If the drawer needs a "highlight on map" button, that's a 1-line prop wire — propose it but don't build v1.

---

### 🧩 BOT-CN-G — Graph Sidecar (optional — DEFER)

**Status**: **NOT part of v1**. The chosen UX (Model C leaning A) makes the full react-flow graph redundant because the sidecar rail + map already carry the topology. Ship this AFTER map-highlight is live, driven by user feedback.

**Owns** (when unblocked): `components/grid-graph/NeighbourhoodGraph.jsx` using `reactflow` (not d3-force — the graphs here are small + hierarchical, reactflow is simpler and matches the GridAssetDrawer's expectations). Would render 2-hop abstract diagram (nodes = subs, edges = voltage-coloured lines) as a TOGGLE on top of the map, not alongside.

**Trigger to unblock**: 3+ pilot users say "I can't see the network" even with sidecar + map highlight. Until then, leave scaffold.

---

## 7. Open Questions / Follow-ups

1. **Neo4j fill**: tracked by council-bots task #21 ("DNO ingestion broken"). Until relationships are populated, depth=3 CIM traversals return near-empty. BOT-CN-D consciously ignores Neo4j.
2. **`to_id` / `from_id` in `_section_connections`**: BOT-CN-D is the owner — additive fix.
3. **Voltage-domain peers** (relationship #6) is documented but NOT shipped in v1. A later `/peers` endpoint can live on the same grid router.
4. **GridTwin.jsx (3D view)** has ArcLayer infrastructure reusable for the same highlight — out of scope, spec ready to be re-used by BOT-CN-M when the 3D view needs the same feature.
5. **Shift-click multi-root compare** — designed here, implement in v2.

---

## 8. Confidence per Section

| Section                 | Confidence | Why                                                                                 |
| ----------------------- | ---------- | ----------------------------------------------------------------------------------- |
| §1 Relationships        | High       | Grounded in existing `_section_connections` + domain model.                         |
| §2 Current state audit  | High       | File:line from actual grep; Neo4j health probed live.                               |
| §3 UX model             | Medium-High | Principled rejection of A/B, but needs visual sign-off on 40 px sidecar width.     |
| §4 Interaction model    | Medium     | Keyboard cycling + shift-click are defensible defaults; could change with user test. |
| §5 Data + performance   | High       | Size bounds computed from actual LIMITs in source; Postgres path well-understood.   |
| §6 Bot briefs           | High       | Disjoint file ownership; minimal cross-cutting.                                     |
| §7 Open questions       | High       | Grounded in the other audit docs.                                                   |
