# Princeps Unified Canvas (L1)

Additive, isolated scaffold for the next-gen canvas. Lives at
`/canvas/:projectId` and leaves every existing component untouched.

## Stack (L1)

- **Base map:** MapLibre GL + Protomaps PMTiles (demo URL by default)
- **Overlays:** deck.gl `MapboxOverlay` in interleaved mode
- **Drawing:** `@deck.gl-community/editable-layers`
  (`DrawPolygonMode` | `ViewMode` | `ModifyMode`)
- **Layout:** `react-resizable-panels`
- **Command palette:** `cmdk`
- **Chat:** Vercel AI SDK (`@ai-sdk/react` v3 / `ai` v6)

## PMTiles

Development uses the public demo PMTiles bundle:
`https://build.protomaps.com/20240101.pmtiles`.

**Production must host its own PMTiles** — the demo is best-effort and can
disappear without notice. Override by setting `VITE_MAPLIBRE_STYLE` to a
fully-formed MapLibre style URL.

Recommended flow:
1. Download the latest Protomaps planet build
2. Host on S3/R2/etc.
3. Serve a style JSON derived from `protomaps-themes-base` pointed at that
   PMTiles URL
4. Set `VITE_MAPLIBRE_STYLE=https://…/style.json`

## Capability registry

`capabilities.js` is the single source of truth for right-rail cards.
Register new cards by importing the component and appending an entry:

```js
capabilities.push({
  id: "grid-verdict",
  label: "Grid Verdict",
  component: GridVerdictCard,
  relevantFor: ["solar", "wind", "bess", "hybrid"],
  priority: 10,
  group: "verdict",
});
```

Cards receive `{ polygon, projectId, assetClass }` as props.

## Chat endpoint

`ChatRail` POSTs to `/api/canvas/chat` with
`{ projectId, assetClass, polygon }`. If the endpoint 404s on OPTIONS probe,
the rail enters offline mode with a friendly banner but keeps the input
active so the UI does not break before the backend agent is wired up.
