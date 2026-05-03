import {useMemo} from 'react';

/**
 * Pattern (g) — Cumulative Work Visualisation.
 *
 * Returns a deck.gl IconLayer config that renders one icon per
 * geographic cluster (e.g. asset / area), sized by log(count) and
 * coloured by severity. Caller composes this layer alongside whatever
 * basemap/3D layers it already has; the hook itself does no rendering.
 *
 * Work-order shape:
 *   {id, position: [lng, lat] | [x, y, z], count, severity ('ok'|'warn'|'alarm'),
 *    label?}
 *
 * Usage:
 *   const wo = useCumulativeWorkLayer(workOrders, {onClick: handleClick});
 *   const layers = [...baseLayers, wo];
 *
 * Produces a deck.gl ScatterplotLayer config (no asset bundling required).
 * Swap the layer type for IconLayer if you ship sprite assets.
 */
export function useCumulativeWorkLayer(workOrders = [], {onClick, idPrefix = 'cw'} = {}) {
  return useMemo(() => {
    const data = workOrders.map((w) => ({
      ...w,
      _radius: Math.max(20, 10 * Math.log2(1 + (w.count ?? 1))),
      _color: severityColour(w.severity),
    }));
    return {
      // deck.gl ScatterplotLayer config — instantiate at the call site:
      //   import {ScatterplotLayer} from '@deck.gl/layers';
      //   const layer = new ScatterplotLayer(useCumulativeWorkLayer(...));
      id: `${idPrefix}-${data.length}`,
      data,
      pickable: true,
      stroked: true,
      filled: true,
      radiusUnits: 'pixels',
      lineWidthMinPixels: 1,
      getPosition: (d) => d.position,
      getRadius: (d) => d._radius,
      getFillColor: (d) => d._color,
      getLineColor: [255, 255, 255, 200],
      onClick: (info) => {
        if (info.object && onClick) onClick(info.object, info);
      },
      // Useful for the parent's tooltip layer:
      _meta: {
        getTooltip: (d) => `${d.label ?? d.id}: ${d.count} work orders`,
      },
    };
  }, [workOrders, onClick, idPrefix]);
}

function severityColour(severity) {
  switch (severity) {
    case 'alarm': return [220, 38, 38, 220];   // red-600
    case 'warn':  return [212, 160, 24, 220];  // gold (Princeps brand)
    case 'ok':    return [34, 197, 94, 220];   // green-500
    default:      return [148, 163, 184, 220]; // slate-400
  }
}
