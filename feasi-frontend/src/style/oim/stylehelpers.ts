/**
 * A simple set of helper functions to make writing Maplibre GL styles in JS/TS a bit more pleasant.
 *
 * Sourced from https://github.com/openinframap/openinframap/blob/main/web/src/style/stylehelpers.ts
 * (BSD-3-Clause). Princeps fork strips the `maplibre-gl` type imports — the
 * expressions are syntactically identical between MapLibre GL and Mapbox GL v3.
 */

// Princeps fork: replace maplibre-gl type imports with permissive aliases so
// Mapbox GL v3 can consume the same layer/expression shapes without dragging
// the MapLibre type tree into our build.
type ExpressionSpecification = any
type InterpolationSpecification = any
type ExpressionInputType = any
type ColorSpecification = any

/**
 * Produces continuous, smooth results by interpolating between pairs of input and output
 * values ("stops").
 *
 * @param property any numeric expression
 * @param stops an array of [stop, value] pairs
 * @param base the base of the interpolation (1 if linear)
 */
export function interpolate(
  property: number | ExpressionSpecification,
  stops: [number, number | number[] | ColorSpecification | ExpressionSpecification][],
  base = 1
): ExpressionSpecification {
  let method: InterpolationSpecification = ['linear']
  if (base != 1) {
    method = ['exponential', base]
  }

  return ['interpolate', method, property, ...stops.flat()]
}

/**
 * Produces discrete, stepped results by evaluating a piecewise-constant function defined by pairs
 * of input and output values ("stops").
 *
 * @param property any numeric expression
 * @param defaultValue the value to be returned if the input is less than the first stop value
 * @param stops an array of [stop, value] pairs
 */
export function step(
  property: ExpressionSpecification,
  defaultValue: ExpressionInputType | ExpressionSpecification,
  stops: [number, ExpressionInputType | ExpressionSpecification][]
): ExpressionSpecification {
  return ['step', property, defaultValue, ...stops.flat()]
}

/**
 * Selects the first output whose corresponding test condition evaluates to true, or the fallback value otherwise.
 */
export function case_(
  branches: [boolean | ExpressionSpecification, ExpressionInputType | ExpressionSpecification][],
  fallback: ExpressionInputType | ExpressionSpecification
): ExpressionSpecification {
  // The following contortion is required to satisfy the typechecker.
  const cases_flat = branches.slice(1).flat() as (boolean | ExpressionInputType | ExpressionSpecification)[]
  return ['case', branches[0][0], branches[0][1], ...cases_flat, fallback]
}

/**
 * Helper for a single-branch case statement.
 *
 * @param condition expression to test
 * @param then return value if expression is true
 * @param else_ return value if expression is false
 */
export function if_(
  condition: boolean | ExpressionSpecification,
  then: ExpressionInputType | ExpressionSpecification,
  else_: ExpressionInputType | ExpressionSpecification
): ExpressionSpecification {
  return ['case', condition, then, else_]
}

export function match(
  property: ExpressionInputType | ExpressionSpecification,
  cases: [ExpressionInputType | ExpressionInputType[], ExpressionInputType | ExpressionSpecification][],
  fallback: ExpressionInputType | ExpressionSpecification
): ExpressionSpecification {
  // The following contortion is required to satisfy the typechecker.
  const cases_flat = cases.slice(1).flat() as (
    | ExpressionInputType
    | ExpressionInputType[]
    | ExpressionSpecification
  )[]
  return ['match', property, cases[0][0], cases[0][1], ...cases_flat, fallback]
}

export function literal(value: any): ExpressionSpecification {
  return ['literal', value]
}

export function get(property: string): ExpressionSpecification {
  return ['get', property]
}

export function has(property: string): ExpressionSpecification {
  return ['has', property]
}

export function any(...expressions: (boolean | ExpressionSpecification)[]): ExpressionSpecification {
  return ['any', ...expressions]
}

export function all(...expressions: (boolean | ExpressionSpecification)[]): ExpressionSpecification {
  return ['all', ...expressions]
}

export function not(expression: boolean | ExpressionSpecification): ExpressionSpecification {
  return ['!', expression]
}

export function concat(
  ...expressions: (ExpressionInputType | ExpressionSpecification)[]
): ExpressionSpecification {
  return ['concat', ...expressions]
}

export function coalesce(
  ...expressions: (ExpressionInputType | ExpressionSpecification)[]
): ExpressionSpecification {
  return ['coalesce', ...expressions]
}

export const zoom: ExpressionSpecification = ['zoom']

export function round(field: ExpressionSpecification, places: number): ExpressionSpecification {
  const pow = Math.pow(10, places)
  return ['/', ['round', ['*', field, pow]], pow]
}

export function rgb(
  r: number | ExpressionSpecification,
  g: number | ExpressionSpecification,
  b: number | ExpressionSpecification,
  a: number | ExpressionSpecification | undefined = 1
): ExpressionSpecification {
  if (a !== 1) {
    return ['rgb', r, g, b]
  } else {
    return ['rgba', r, g, b, a]
  }
}
