# Twin Layer Registry — Interface Contract

**Status:** binding for all swarm bots shipping Digital Twin 100x layers.
**Read with:** `digital_twin_100x_spec.md`.

## JS module shape — one file per layer

Path: `feasi-frontend/src/components/twin/layers/<bot>_<feature>.jsx`.
Exports `default` object matching this TypeScript type:

```ts
export type TwinLayerModule = {
  id: string;                             // unique; prefix with bot id
  menuLabel: string;                      // shown in left-rail toggle
  category: "infrastructure" | "ownership" | "planning" | "environment" | "ops" | "context";
  defaultVisible: boolean;
  renderer: "deckgl" | "mapbox";
  minZoom?: number;                       // default 0
  maxZoom?: number;                       // default 22
  requiresSite?: boolean;                 // true => only mounts in Assess embed
  attribution: string;                    // "HMLR INSPIRE · OGL v3"

  // React hook — called with current twin context.
  dataHook: (ctx: {
    bbox: [number,number,number,number];  // [minLon,minLat,maxLon,maxLat]
    siteId?: string;                      // set in embed mode
    scenario: string;                     // "baseline" | FES pathway id
    year: number;                         // 2024-2050
    zoom: number;
  }) => { data: unknown; loading: boolean; error?: Error };

  // Pure — given data + rendering ctx, return the layer instance(s).
  layerFactory: (
    data: unknown,
    ctx: { animPhase: number; theme: "dark"|"light" }
  ) => DeckLayer | DeckLayer[] | MapboxLayerSpec | MapboxLayerSpec[];

  // Optional — right-drawer section renderer when a feature is clicked.
  inspector?: (feature: unknown) => React.ReactNode;

  // Optional — structured KPIs pushed into the agentic rail (see spec §5).
  kpis?: (data: unknown) => KPI[];
};
```

## Auto-discovery (BOT-LL owns, ships once)

`feasi-frontend/src/components/twin/layers/index.js`:
```js
const modules = import.meta.glob("./*.jsx", { eager: true });
export default Object.values(modules).map(m => m.default).filter(Boolean);
```

`GridTwin.jsx` / `TwinEmbed.jsx` import from this file only — **they never reference individual layer files**. Adding a layer is literally dropping a file.

## Python KPI side — `/api/twin/project-kpis/{project_id}`

Owner: **BOT-GG**. Path: `app/routers/twin.py` **[PROPOSED — NEW FILE]**.

```python
class KPI(BaseModel):
    id: str
    label: str
    value: float | str
    unit: str | None = None
    verdict: Literal["green", "amber", "red"]
    source_endpoint: str
    explanation: str                      # <= 140 chars
    last_updated: datetime
    confidence: float | None = None

class ProjectKPIs(BaseModel):
    project_id: str
    kpis: list[KPI]
    rollup_verdict: Literal["GO", "CAUTION", "NO-GO"]

@router.get("/api/twin/project-kpis/{project_id}", response_model=ProjectKPIs)
async def project_kpis(project_id: str, bbox: str | None = None,
                        pool: asyncpg.Pool = Depends(get_pool)) -> ProjectKPIs:
    # Fan-out to existing endpoints listed in spec §5 Minimum Set.
    # Run concurrently via asyncio.gather; never block on a slow one (5s timeout).
    ...
```

Rollup rule (match `app/workflows.py:101`): any red → red → NO-GO; any amber → amber → CAUTION; else green → GO.

## Provenance

Every KPI and parcel-drawer section MUST carry:
```
{ source: str, source_url: str, fetched_at: ISO8601, licence: "OGL v3"|"ODbL"|"CC-BY 4.0"|"commercial" }
```

## Non-goals

- Layer modules MUST NOT mutate global state, fetch on every render, or touch Mapbox map instance directly (use `renderer: "mapbox"` for style-layer specs).
- No bot may import from another bot's module. Shared utilities live in `feasi-frontend/src/components/twin/lib/`.
- No bot edits `GridTwin.jsx` or `GridTwinCesium.jsx`.

**Word count: ~310**
