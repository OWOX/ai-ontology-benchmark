// A sticker's corners rounded off, kept as polygon points so the drawing stays a polygon. Pure.
import type { Pt } from './hull'

/**
 * The polygon with each corner swapped for a short curve: it leaves the corner `f` of the way along each edge and bends
 * through the corner as a quadratic Bézier, sampled at `segs` steps. The shape stays inside the original polygon.
 */
export function roundCorners(pts: readonly (readonly number[])[], f = 0.14, segs = 3): Pt[] {
  return pts.flatMap((v, i) => {
    const p = pts[(i + pts.length - 1) % pts.length], n = pts[(i + 1) % pts.length]
    const a: Pt = [v[0] + (p[0] - v[0]) * f, v[1] + (p[1] - v[1]) * f]
    const b: Pt = [v[0] + (n[0] - v[0]) * f, v[1] + (n[1] - v[1]) * f]
    return Array.from({ length: segs + 1 }, (_, k): Pt => {
      const t = k / segs, u = 1 - t
      return [u * u * a[0] + 2 * u * t * v[0] + t * t * b[0], u * u * a[1] + 2 * u * t * v[1] + t * t * b[1]]
    })
  })
}
