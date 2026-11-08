// Reads sticker colors from an n×n grid laid over a square of the frame. Each
// cell is read over a central patch, as a per-channel median so glare or a groove
// inside the patch don't move the color. The luma spread of the same patch says
// whether the cell is even. The center cell of an odd grid is read from a square
// ring instead, because the printed logo on a center cap can cover the middle.
import { isSticker, rgbToLab, type RGB } from './colors'
import { labDistance } from '../core/palette'
import { cellCentre, cellSide, isSquare, pointAt, toGrid, axesOf } from './grid'

export interface Frame { data: Uint8ClampedArray; width: number; height: number }
export type Vec2 = [number, number]
/**
 * A located grid. `x`, `y`, `size` are the square centred on the grid with side the mean of its two edge lengths,
 * so a consumer that only wants where and how big (pace, the tilt ring) reads it as before. `u` is the grid's top
 * edge (left to right) and `v` its left edge (top to bottom), both in pixels; absent, they are [size, 0] and [0, size].
 */
export interface Rect { x: number; y: number; size: number; u?: Vec2; v?: Vec2 }

/** Largest luma interquartile range of a cell's patch that still counts as one even sticker color. */
export const MAX_SPREAD = 25
/** Share of a cell's side that a patch covers. */
export const PATCH = 0.3
/** The centre cell of an odd grid is read from a square ring, as shares of the half-cell: inside the groove, outside the printed logo on the cap. */
export const CENTER_RING: readonly [number, number] = [0.5, 0.8]

/** The most pixels a patch or ring reads; a box with more is read on a stride, so a big cell costs no more than a small one. */
export const PATCH_PIXELS = 256

/** Smallest pixel step in x and y that keeps a box of `area` pixels at or under PATCH_PIXELS. */
export const strideFor = (area: number) => Math.max(1, Math.ceil(Math.sqrt(area / PATCH_PIXELS)))

/** Index of the center cell of an n×n grid, or -1 when n is even. */
export const centerIndex = (n: number): number => (n % 2 ? (n * n - 1) / 2 : -1)

/** Value at quantile q of an ascending-sorted array (nearest rank). */
const at = (sorted: ArrayLike<number>, q: number) => sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))]

/** Per-channel median color and luma spread of the given pixels (indices into frame.data), or null when there are none. */
function summarize(frame: Frame, pixels: Iterable<number>): { color: RGB; spread: number } | null {
  const ch: number[][] = [[], [], []]
  const luma: number[] = []
  for (const k of pixels) {
    const R = frame.data[k], G = frame.data[k + 1], B = frame.data[k + 2]
    ch[0].push(R); ch[1].push(G); ch[2].push(B)
    luma.push(0.299 * R + 0.587 * G + 0.114 * B)
  }
  if (!luma.length) return null
  // Typed arrays sort numerically without a comparator, which is much faster than number[].sort((p, q) => p - q).
  const sorted = ch.map((a) => Float64Array.from(a).sort())
  const lumas = Float64Array.from(luma).sort()
  return { color: [at(sorted[0], 0.5), at(sorted[1], 0.5), at(sorted[2], 0.5)], spread: at(lumas, 0.75) - at(lumas, 0.25) }
}

/** Offsets into frame.data of the pixels of the box x0..x1 by y0..y1 that pass `keep`. */
function* boxPixels(frame: Frame, x0: number, y0: number, x1: number, y1: number, keep: (x: number, y: number) => boolean, stride = 1): Generator<number> {
  // Start the grid so the leftover pixels split between the near and far edges.
  const sx = x0 + (((x1 - x0 - 1) % stride) >> 1), sy = y0 + (((y1 - y0 - 1) % stride) >> 1)
  for (let y = sy; y < y1; y += stride)
    for (let x = sx; x < x1; x += stride) if (keep(x, y)) yield (y * frame.width + x) * 4
}

const inFrame = (frame: Frame, x0: number, y0: number, x1: number, y1: number) =>
  x0 >= 0 && y0 >= 0 && x1 <= frame.width && y1 <= frame.height && x1 > x0 && y1 > y0

export type Side = 0 | 1 | 2 | 3
export interface Patch { color: RGB; spread: number }
/** Band patches sit this far outside the square's edge, as a share of a cell, and are this wide. */
export const BAND_OUT = 0.3
export const BAND_PATCH = 0.2

/** Even-cube band scan starts this far inside the square's edge, as a share of the square: the located square counts the groove, so the first strips can still be on the adjacent cell. */
export const EDGE_IN = 0.06
/** The scan stops this far outside the edge, as a share of a 3×3 cell (the reach the fixed patch had): further out is not the neighbouring sticker any more. */
export const BAND_REACH = 0.3
/** Depth of one scan strip, as a share of the square (at least 1 px): fine enough that a sliver of a few percent still fills three strips. */
export const BAND_STEP = 0.01
/** Lab distance under which two colours count as the same: the cell's own sticker, its groove and rounded edge are skipped, and one sticker stays one run. */
export const BAND_SAME = 20
/** Consecutive strips that make a band: one stray strip (glare, a seam) is not a sticker. */
export const BAND_RUN = 3

/** Median colour and luma spread of the `side`-px square centred on (cx, cy); null when it leaves the frame. */
function patchAt(frame: Frame, cx: number, cy: number, side: number): Patch | null {
  const x0 = Math.round(cx - side / 2), x1 = Math.round(cx + side / 2)
  const y0 = Math.round(cy - side / 2), y1 = Math.round(cy + side / 2)
  if (!inFrame(frame, x0, y0, x1, y1)) return null
  return summarize(frame, boxPixels(frame, x0, y0, x1, y1, () => true, strideFor((x1 - x0) * (y1 - y0))))
}

/** Median color and luma spread of cell i's central patch, or null when the patch leaves the frame. */
export function samplePatch(frame: Frame, rect: Rect, n: number, i: number, frac: number): Patch | null {
  const [cx, cy] = cellCentre(rect, n, i)
  return patchAt(frame, cx, cy, frac * cellSide(rect, n))
}

/**
 * The neighbouring faces' rows just outside an n×n square: four bands of n patches at the cell centres, sides clockwise
 * from the top (0 top, 1 right, 2 bottom, 3 left), patches clockwise around the square (top left to right,
 * right top to bottom, bottom right to left, left bottom to top). A patch outside the frame is null. `reach` scales the offset (an odd grid only):
 * the asked-edge gate reads the same band 4 times further out to tell a strip from the background (steps/state/askBand.ts).
 */
export function sampleBands(frame: Frame, rect: Rect, n: number, reach = 1): (Patch | null)[][] {
  if (n % 2 === 0) return scanBands(frame, rect, n)
  const cell = rect.size / n
  // Offset and patch side use the 3×3 cell for every n: the sliver of side face a tilted cube shows does not grow with
  // the sticker, and the 3×3 values were tuned on real frames. On a 2×2 the n-cell would put them 1.5 times too far and wide.
  const unit = rect.size / 3
  const out = BAND_OUT * unit * reach
  const along = Array.from({ length: n }, (_, k) => (k + 0.5) * cell)
  const centres: [number, number][][] = isSquare(rect) ? [
    along.map((a) => [rect.x + a, rect.y - out]),
    along.map((a) => [rect.x + rect.size + out, rect.y + a]),
    [...along].reverse().map((a) => [rect.x + a, rect.y + rect.size + out]),
    [...along].reverse().map((a) => [rect.x - out, rect.y + a]),
  ] : (() => {
    // A parallelogram: the edge point at along-share a, moved `out` px away from the grid along the unit edge direction.
    const { u, v } = axesOf(rect)
    const unitOf = ([x, y]: Vec2): Vec2 => { const l = Math.hypot(x, y); return [x / l, y / l] }
    const uu = unitOf(u), vu = unitOf(v)
    const shift = (p: Vec2, d: Vec2, sign: number): Vec2 => [p[0] + sign * out * d[0], p[1] + sign * out * d[1]]
    const fr = Array.from({ length: n }, (_, k) => (k + 0.5) / n)
    return [
      fr.map((a) => shift(pointAt(rect, a, 0), vu, -1)),
      fr.map((a) => shift(pointAt(rect, 1, a), uu, 1)),
      [...fr].reverse().map((a) => shift(pointAt(rect, a, 1), vu, 1)),
      [...fr].reverse().map((a) => shift(pointAt(rect, 0, a), uu, -1)),
    ]
  })()
  return centres.map((band) => band.map(([cx, cy]) => patchAt(frame, cx, cy, BAND_PATCH * unit)))
}

/** Pixel box of the strip `along` ± `half` px along `side` of the square (along measured from the square's corner), from `d0` to `d1` px outside its edge. */
function stripBox(rect: Rect, side: Side, along: number, half: number, d0: number, d1: number): [number, number, number, number] {
  const r = Math.round
  const a0 = along - half, a1 = along + half
  if (side === 0) return [r(rect.x + a0), r(rect.y - d1), r(rect.x + a1), r(rect.y - d0)]
  if (side === 1) return [r(rect.x + rect.size + d0), r(rect.y + a0), r(rect.x + rect.size + d1), r(rect.y + a1)]
  if (side === 2) return [r(rect.x + a0), r(rect.y + rect.size + d0), r(rect.x + a1), r(rect.y + rect.size + d1)]
  return [r(rect.x - d1), r(rect.y + a0), r(rect.x - d0), r(rect.y + a1)]
}

/**
 * `stripBox` for a parallelogram: the axis-aligned bounding box of the strip `along` ± `half` px (share `a` of the side,
 * across the edge direction) from `d0` to `d1` px outside the edge along its outward normal-ish edge vector. The strip
 * stays as thin as the square path's, so a sliver of a few percent is not smeared; the box only widens by what the tilt
 * adds, and at zero tilt it is exactly `stripBox`. The samplers read pixel boxes, so the rotated strip is bounded, not traced.
 */
function tiltedStrip(rect: Rect, side: Side, a: number, half: number, d0: number, d1: number): [number, number, number, number] {
  const { u, v } = axesOf(rect)
  const [p, dir, edge]: [Vec2, Vec2, Vec2] = side === 0 ? [pointAt(rect, a, 0), [-v[0], -v[1]], u]
    : side === 1 ? [pointAt(rect, 1, a), u, v]
    : side === 2 ? [pointAt(rect, a, 1), v, u]
    : [pointAt(rect, 0, a), [-u[0], -u[1]], v]
  const dl = Math.hypot(dir[0], dir[1]), el = Math.hypot(edge[0], edge[1])
  const xs: number[] = [], ys: number[] = []
  for (const t of [-half, half]) for (const d of [d0, d1]) {
    xs.push(p[0] + (t * edge[0]) / el + (d * dir[0]) / dl)
    ys.push(p[1] + (t * edge[1]) / el + (d * dir[1]) / dl)
  }
  return [Math.round(Math.min(...xs)), Math.round(Math.min(...ys)), Math.round(Math.max(...xs)), Math.round(Math.max(...ys))]
}

/**
 * Bands of an even grid. Held nearly square-on, the neighbouring side shows as a sliver of a few percent right against
 * the edge, which a patch at a fixed offset misses. So each position scans outward from just inside the edge for the
 * first short stable run of a sticker colour other than the adjacent cell's: the sticker across the edge belongs to the
 * same corner piece, so it is never the cell's colour, and the scan skips the cell's own edge and the groove.
 */
export function scanBands(frame: Frame, rect: Rect, n: number, only?: Side): (Patch | null)[][] {
  const sq = isSquare(rect)
  const cell = rect.size / n, unit = rect.size / 3
  const half = (BAND_PATCH * unit) / 2
  const step = Math.max(1, Math.round(BAND_STEP * rect.size))
  const start = -Math.round(EDGE_IN * rect.size), reach = BAND_REACH * unit
  const scan = (side: Side, k: number): Patch | null => {
    const i = [k, k * n + n - 1, (n - 1) * n + n - 1 - k, (n - 1 - k) * n][side]
    const own = samplePatch(frame, rect, n, i, PATCH)
    if (!own) return null
    const ownLab = rgbToLab(own.color)
    const along = (side < 2 ? k + 0.5 : n - k - 0.5) * cell
    let first: ReturnType<typeof rgbToLab> | null = null
    let runStart = 0, runEnd = 0, count = 0
    for (let d = start; d <= reach; d += step) {
      const [x0, y0, x1, y1] = sq ? stripBox(rect, side, along, half, d, d + step) : tiltedStrip(rect, side, along / rect.size, half, d, d + step)
      // Leaving the frame ends the scan but keeps a run already found: a sliver can reach the border.
      if (!inFrame(frame, x0, y0, x1, y1)) break
      const s = summarize(frame, boxPixels(frame, x0, y0, x1, y1, () => true, strideFor((x1 - x0) * (y1 - y0))))!
      const lab = rgbToLab(s.color)
      const passes = isSticker(s.color) && labDistance(lab, ownLab) > BAND_SAME
      const same = passes && first !== null && labDistance(lab, first) <= BAND_SAME
      // A run that reached BAND_RUN ends at the first strip that does not continue it; a shorter one is dropped.
      if (count >= BAND_RUN && !same) break
      if (same) count++
      else if (passes) { first = lab; runStart = d; count = 1 }
      else { first = null; count = 0 }
      runEnd = d + step
    }
    if (count < BAND_RUN) return null
    const [x0, y0, x1, y1] = sq ? stripBox(rect, side, along, half, runStart, runEnd) : tiltedStrip(rect, side, along / rect.size, half, runStart, runEnd)
    return summarize(frame, boxPixels(frame, x0, y0, x1, y1, () => true, strideFor((x1 - x0) * (y1 - y0))))
  }
  // `only` reads one side and leaves the others null (the asked-edge gate, steps/state/askBand.ts).
  return ([0, 1, 2, 3] as Side[]).map((side) => Array.from({ length: n }, (_, k) => (only === undefined || side === only ? scan(side, k) : null)))
}

/**
 * Median color and luma spread of the square ring of cell i: pixels whose Chebyshev distance from the cell
 * centre, as a share of the half-cell, lies in [inner, outer). Null when the outer square leaves the frame
 * or no pixel qualifies.
 */
export function sampleRing(frame: Frame, rect: Rect, n: number, i: number, inner: number, outer: number): Patch | null {
  const c = i % n, r = Math.floor(i / n)
  const [cx, cy] = cellCentre(rect, n, i)
  let x0: number, x1: number, y0: number, y1: number
  let keep: (x: number, y: number) => boolean
  if (isSquare(rect)) {
    const half = rect.size / n / 2
    x0 = Math.round(cx - outer * half); x1 = Math.round(cx + outer * half)
    y0 = Math.round(cy - outer * half); y1 = Math.round(cy + outer * half)
    keep = (x, y) => {
      const d = Math.max(Math.abs(x + 0.5 - cx), Math.abs(y + 0.5 - cy)) / half
      return d >= inner && d < outer
    }
  } else {
    // The ring's outer square, carried through the cell's axes, is a parallelogram; read its bounding box and keep by cell-local distance.
    const { u, v } = axesOf(rect)
    const ex = (outer * (Math.abs(u[0]) + Math.abs(v[0]))) / (2 * n), ey = (outer * (Math.abs(u[1]) + Math.abs(v[1]))) / (2 * n)
    x0 = Math.round(cx - ex); x1 = Math.round(cx + ex)
    y0 = Math.round(cy - ey); y1 = Math.round(cy + ey)
    keep = (x, y) => {
      const [gs, gt] = toGrid(rect, x + 0.5, y + 0.5)
      const d = 2 * Math.max(Math.abs(gs * n - c - 0.5), Math.abs(gt * n - r - 0.5))
      return d >= inner && d < outer
    }
  }
  if (!inFrame(frame, x0, y0, x1, y1)) return null
  return summarize(frame, boxPixels(frame, x0, y0, x1, y1, keep, strideFor((x1 - x0) * (y1 - y0))))
}
