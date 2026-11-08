// Sticker color space and plausibility. Classification happens against the
// palette sampled from the visitor's cube (core/palette.ts); this module only
// converts to Lab and says whether a sample can be a sticker at all.
import { COLORS, type ColorName } from '../core/geometry'

export type RGB = readonly [number, number, number]
export type Lab = readonly [number, number, number]
export type Refs = Record<ColorName, Lab>

export const DEFAULT_RGB: Record<ColorName, RGB> = {
  white: [235, 235, 235],
  yellow: [230, 220, 40],
  green: [30, 170, 70],
  blue: [30, 90, 200],
  red: [200, 30, 40],
  orange: [240, 120, 30],
}

export function rgbToLab([r, g, b]: RGB): Lab {
  const lin = (c: number) => {
    const v = c / 255
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  }
  const R = lin(r), G = lin(g), B = lin(b)
  const x = (R * 0.4124 + G * 0.3576 + B * 0.1805) / 0.95047
  const y = R * 0.2126 + G * 0.7152 + B * 0.0722
  const z = (R * 0.0193 + G * 0.1192 + B * 0.9505) / 1.08883
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116)
  return [116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))]
}

/** Inverse of rgbToLab: the sRGB colour of a Lab point, clamped to the gamut. Used to paint a swatch of what the camera read. */
export function labToRgb([L, a, b]: Lab): RGB {
  const fy = (L + 16) / 116, fx = fy + a / 500, fz = fy - b / 200
  const finv = (t: number) => (t ** 3 > 0.008856 ? t ** 3 : (t - 16 / 116) / 7.787)
  const x = finv(fx) * 0.95047, y = finv(fy), z = finv(fz) * 1.08883
  const R = x * 3.2406 + y * -1.5372 + z * -0.4986
  const G = x * -0.9689 + y * 1.8758 + z * 0.0415
  const B = x * 0.0557 + y * -0.204 + z * 1.057
  const gamma = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055)
  const byte = (c: number) => Math.max(0, Math.min(255, Math.round(gamma(c) * 255)))
  return [byte(R), byte(G), byte(B)]
}

const HUE_TOLERANCE = 35
/** Least Lab chroma that still reads as a real sticker of this color; a wood desk or skin sits under it. */
const MIN_CHROMA: Record<Exclude<ColorName, 'white'>, number> = { red: 40, orange: 40, yellow: 40, green: 25, blue: 20 }
/** White is the low-chroma color: chroma up to this share of L covers a warm or cool cast, and any exposure. */
const WHITE_CHROMA_PER_L = 0.5
const WHITE_MIN_L = 30

/**
 * Whether a sample can be a sticker of this color. Judged by hue angle
 * in the Lab a/b plane plus a chroma floor, not by distance to the bright
 * default: under-exposure shrinks chroma and a warm cast moves it, but neither
 * turns blue into another hue. Lightness is not compared at all, except for
 * white, whose chroma is judged against it. A wood desk read as orange has
 * orange's hue but not its chroma.
 */
export const plausibleSticker = (color: ColorName, rgb: RGB): boolean => {
  const [L, a, b] = rgbToLab(rgb)
  const chroma = Math.hypot(a, b)
  if (color === 'white') return L >= WHITE_MIN_L && chroma <= WHITE_CHROMA_PER_L * L
  if (chroma < MIN_CHROMA[color]) return false
  const [, ra, rb] = rgbToLab(DEFAULT_RGB[color])
  let d = Math.abs(Math.atan2(b, a) - Math.atan2(rb, ra)) * (180 / Math.PI)
  if (d > 180) d = 360 - d
  return d <= HUE_TOLERANCE
}

/** Whether a sample can be a sticker of any of the six colors. */
export const isSticker = (rgb: RGB): boolean => COLORS.some((c) => plausibleSticker(c, rgb))
