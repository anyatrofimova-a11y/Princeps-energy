/**
 * OIM common style fragments — text paint, lifecycle helpers, oimSymbol factory.
 *
 * Sourced from https://github.com/openinframap/openinframap/blob/main/web/src/style/common.ts
 * (BSD-3-Clause). Princeps fork strips:
 *   - the `maplibre-gl` type imports (Mapbox GL v3 accepts the same expression shapes)
 *   - the `i18next` `t(...)` calls (replaced with the upstream English fallback strings)
 *   - the `local_name_tags()` i18n helper (replaced with a fixed [name:en, name] coalesce)
 */
import { LayerSpecificationWithZIndex } from './types.ts'
import { step, interpolate, get, has, all, any, concat, case_, coalesce } from './stylehelpers.ts'

// Princeps fork: replace maplibre-gl types with permissive aliases.
type ExpressionSpecification = any
type DataDrivenPropertyValueSpecification<T> = any
type FilterSpecification = any

// Princeps fork: hardcoded English-first name fallback in place of the
// upstream i18next-driven `local_name_tags()`. Mapbox/MapLibre handle
// undefined fields gracefully so a small list is fine.
export function get_local_name(): ExpressionSpecification {
  return ['coalesce', get('name:en'), get('name'), '']
}

export const text_paint = {
  'text-color': 'hsl(0, 0%, 10%)',
  'text-halo-width': 6,
  'text-halo-blur': 3,
  'text-halo-color': 'hsla(0, 0%, 98%, 0.9)'
}

export const operator_text: ExpressionSpecification = step(['zoom'], get('name'), [
  [
    14,
    case_(
      [
        [all(has('operator'), has('name')), concat(get('name'), '\n(', get('operator'), ')')],
        [has('operator'), get('operator')]
      ],
      get('name')
    )
  ]
])

export const underground_p: ExpressionSpecification = any(
  ['==', get('location'), 'underground'],
  ['==', get('location'), 'underwater'],
  ['==', get('tunnel'), true],
  all(
    // Power cables are underground by default
    ['==', get('type'), 'cable'],
    ['==', get('location'), '']
  )
)

// Princeps fork: hardcode the Mapbox-default font stack — the upstream OIM
// build ships Noto Sans glyphs via its own glyph endpoint; Mapbox's default
// style does not.
export const font = ['DIN Pro Regular', 'Arial Unicode MS Regular']

export type OIMSymbolOptions = {
  id: string
  zorder: number
  source: string
  sourceLayer: string
  filter?: FilterSpecification
  minZoom: number
  textField: ExpressionSpecification
  textSize?: number
  textMinZoom: number
  textOffset?: number
  iconImage: ExpressionSpecification | string
  iconScale?: ExpressionSpecification | number // Icon scale at max icon zoom
  iconMinScale?: ExpressionSpecification | number // Icon scale at initial icon zoom
  iconMaxZoom?: number
  iconAnchor?: DataDrivenPropertyValueSpecification<
    'bottom' | 'center' | 'left' | 'right' | 'top' | 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'
  >
}

/**
 * Generate a text+icon symbol style with the following properties:
 *
 * - The icon appears at minZoom and disappears at iconMaxZoom.
 * - The text appears at textMinZoom.
 * - Icon scaling, text scaling, and text offsets are managed automatically.
 */
export function oimSymbol(options: OIMSymbolOptions): LayerSpecificationWithZIndex {
  const iconScale = options.iconScale || 1
  const textSize = options.textSize || 12
  const textOffset = options.textOffset || 1.4
  const iconMaxZoom = options.iconMaxZoom || 21
  const iconAnchor = options.iconAnchor || 'center'
  return {
    id: options.id,
    zorder: options.zorder,
    type: 'symbol',
    source: options.source,
    'source-layer': options.sourceLayer,
    filter: options.filter || ['literal', true],
    minzoom: options.minZoom,
    paint: {
      ...text_paint,
      'text-opacity': step(['zoom'], 0, [[options.textMinZoom, 1]])
    },
    layout: {
      'icon-image': step(['zoom'], options.iconImage, [
        [iconMaxZoom, ['case', get('is_node'), options.iconImage, '']]
      ]),
      'icon-size': interpolate(
        ['zoom'],
        [
          [options.minZoom, options.iconMinScale || ['*', iconScale, 0.8]],
          [iconMaxZoom, iconScale]
        ]
      ),
      'icon-anchor': iconAnchor,
      'text-field': options.textField,
      'text-font': font,
      'text-size': interpolate(
        ['zoom'],
        [
          [options.textMinZoom, textSize * 0.7],
          [18, textSize]
        ]
      ),
      'text-variable-anchor': iconAnchor == 'center' ? ['top', 'bottom'] : ['center'],
      'text-radial-offset': interpolate(
        ['zoom'],
        [
          [options.textMinZoom, textOffset * 0.8],
          [iconMaxZoom, textOffset],
          [iconMaxZoom + 2, ['case', get('is_node'), textOffset, 0]]
        ]
      ),
      'text-optional': true,
      'icon-allow-overlap': true
    }
  }
}

export const substance: ExpressionSpecification = coalesce(get('substance'), get('type'), '')
export const construction_p: ExpressionSpecification = coalesce(get('construction'), false)
export const disused_p: ExpressionSpecification = coalesce(get('disused'), false)

export function lifecycle_label(): ExpressionSpecification {
  return case_(
    [
      [construction_p, ' (under construction) '],
      [disused_p, ' (disused) ']
    ],
    ''
  )
}
