// Princeps fork — replaces the `import type { LayerSpecification } from 'maplibre-gl'`
// from upstream OpenInfraMap (BSD-3-Clause). Mapbox GL v3 has its own
// LayerSpecification but the field names overlap, so we widen to `any` here
// rather than pin one library's types into the other's tree.
export type LayerSpecificationWithZIndex = any
