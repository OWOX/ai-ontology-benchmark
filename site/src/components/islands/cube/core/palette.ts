// Colour tests shared by the recognisers: whether two Labs are different colours (`differs`), the nearest reference to a Lab
// (`nearestLab`, with the red/orange hue rule), and the hue helpers. The six references themselves come from the memory of
// captures (memory.ts, centres.ts); nothing here is classified against built-in colors.
import { COLORS, type ColorName } from './geometry'
import { DEFAULT_RGB, rgbToLab, type Lab, type RGB, type Refs } from '../vision/colors'

/** A sample whose chroma per lightness is below this is achromatic (white, or white under a cast); hue means nothing there. */
export const ACHROMATIC = 0.6
/** Two chromatic samples whose hues differ by at least this many degrees are different colors. Noise and glare move a chromatic hue by up to 8 degrees; red and orange differ by at least 10.6 even under tungsten light. */
export const HUE_NEW = 9
/** An achromatic sample and a chromatic one differ when their chroma-per-lightness ratios differ by at least this much: white against yellow under a warm cast. */
export const RATIO_NEW = 0.3
/**
 * An achromatic sample and a chromatic one also differ when their hues are at least this far apart.
 * An achromatic sample's hue is noise, but not 60 degrees of noise against a real color: a cast moves
 * white's hue toward the cast, and two views of the same cast white sit within a few degrees of each
 * other. This catches white against blue under tungsten light, where the cast pushes white's ratio up
 * and blue's down until they sit less than RATIO_NEW apart. A warm white seen once at ratio 0.55 and
 * once at 0.63 is a mixed pair, but both hues follow the cast, so this term stays quiet.
 */
export const HUE_FAR = 60

/** A poly puzzle's chromatic group whose hue is further than this many degrees from the hue of the slot it would take stays unnamed: a glare-split light blue is not green (poly/colours.ts). */
export const HUE_CAP = 50
const CHROMATIC: readonly ColorName[] = ['yellow', 'green', 'blue', 'red', 'orange']

export const labDistance = (a: Lab, b: Lab): number => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])

export const hue = ([, a, b]: Lab): number => (Math.atan2(b, a) * 180) / Math.PI
export const hueGap = (x: number, y: number): number => {
  const d = Math.abs(x - y) % 360
  return d > 180 ? 360 - d : d
}

export const ratio = ([L, a, b]: Lab): number => Math.hypot(a, b) / Math.max(L, 1)

/** The hue of each chromatic colour's default, the target of the hue fit. */
export const DEFAULT_HUE = Object.fromEntries(CHROMATIC.map((c) => [c, hue(rgbToLab(DEFAULT_RGB[c]))])) as Record<ColorName, number>

/** Whether two samples are different colours: by hue if both are chromatic; if only one is, by chroma per lightness or by a wide hue gap; two achromatic samples never differ. */
export const differs = (held: Lab, lab: Lab): boolean => {
  const a = ratio(held) >= ACHROMATIC
  const b = ratio(lab) >= ACHROMATIC
  if (a && b) return hueGap(hue(held), hue(lab)) >= HUE_NEW
  if (!a && !b) return false
  return Math.abs(ratio(held) - ratio(lab)) >= RATIO_NEW || hueGap(hue(held), hue(lab)) >= HUE_FAR
}

/** A center is new when every held sample differs from it. */
export const isNew = (samples: RGB[], rgb: RGB): boolean => {
  const lab = rgbToLab(rgb)
  return samples.every((s) => differs(rgbToLab(s), lab))
}

/** Degrees from `from` to `to`, in (-180, 180]: the wrap at 180 never cuts a pair of neighbouring hues. */
export const turnFrom = (from: number, to: number): number => ((((to - from) % 360) + 540) % 360) - 180

/** Red and orange references closer in hue than this many degrees have no usable midpoint: the full Lab distance decides. */
export const RO_SPAN_MIN = 8
/** Closer than this many degrees in hue and further than RO_LIGHT apart in lightness, the pair differs mostly by lightness (a dark red against a bright orange): full Lab decides. */
export const RO_SPAN_NEAR = 15
export const RO_LIGHT = 20

/**
 * The reference nearest a Lab by full Lab distance, except between red and orange: when those are the two nearest, the sample's
 * hue against the midpoint of the two references' hues picks the name. Glare and shadow move lightness and chroma far more than
 * hue, so a deep red read against a dull learned red, or a pale one in glare, stays red. The hue rule steps aside (full Lab names
 * it) when the references' hues are within RO_SPAN_MIN degrees, or within RO_SPAN_NEAR while their lightness differs by more than
 * RO_LIGHT. `dist` is always the full-Lab distance to the nearest reference, so the readability gate (MAX_DIST) never moves: the
 * hue rule picks the name only. Spec: docs/superpowers/specs/2026-10-12-cube-palette-refit-design.md ("Red against orange by hue", the one part still in force)
 */
export function nearestLab(refs: Refs, lab: Lab): { color: ColorName; dist: number } {
  let color: ColorName = COLORS[0]
  let dist = Infinity
  let second: ColorName | null = null
  let secondDist = Infinity
  for (const c of COLORS) {
    const d = labDistance(lab, refs[c])
    if (d < dist) { second = color; secondDist = dist; dist = d; color = c }
    else if (d < secondDist) { second = c; secondDist = d }
  }
  if (second !== null && ((color === 'red' && second === 'orange') || (color === 'orange' && second === 'red'))) {
    const span = turnFrom(hue(refs.red), hue(refs.orange))
    const gap = Math.abs(span)
    if (gap >= RO_SPAN_MIN && (gap >= RO_SPAN_NEAR || Math.abs(refs.red[0] - refs.orange[0]) <= RO_LIGHT)) {
      // Orange lies `span` degrees on from red; past the half-way mark is orange, short of it red.
      const named: ColorName = turnFrom(hue(refs.red), hue(lab)) * Math.sign(span) > gap / 2 ? 'orange' : 'red'
      return { color: named, dist }
    }
  }
  return { color, dist }
}

export const nearest = (refs: Refs, rgb: RGB): { color: ColorName; dist: number } => nearestLab(refs, rgbToLab(rgb))
