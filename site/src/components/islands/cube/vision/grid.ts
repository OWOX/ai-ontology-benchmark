// Maps a located grid to pixels. A fit is a square, or while tracking a tipped face a parallelogram
// given by its top edge `u` and left edge `v`. Every sampler asks this module where a cell or a seam
// point sits, so the square and the parallelogram share one code path for placement.
import type { Rect, Vec2 } from './sample'

/** The grid's top edge (left to right) and left edge (top to bottom); a rect without them is the square of its size. */
export function axesOf(rect: Rect): { u: Vec2; v: Vec2 } {
  return { u: rect.u ?? [rect.size, 0], v: rect.v ?? [0, rect.size] }
}

/**
 * True for a plain axis-aligned square, which every sampler reads on its original path so results stay bit-identical.
 * Axes spelled out as the defaults count too, so a rect gives the same numbers whether or not it carries them.
 */
export const isSquare = (rect: Rect): boolean =>
  (!rect.u || (rect.u[0] === rect.size && rect.u[1] === 0)) && (!rect.v || (rect.v[0] === 0 && rect.v[1] === rect.size))

export const centreOf = (rect: Rect): Vec2 => [rect.x + rect.size / 2, rect.y + rect.size / 2]

/** Pixel position of grid coordinates (s, t), each 0..1 from the top-left corner. */
export function pointAt(rect: Rect, s: number, t: number): Vec2 {
  // The square keeps today's arithmetic: going through the centre would change the last bits.
  if (isSquare(rect)) return [rect.x + s * rect.size, rect.y + t * rect.size]
  const { u, v } = axesOf(rect), [cx, cy] = centreOf(rect)
  return [cx + (s - 0.5) * u[0] + (t - 0.5) * v[0], cy + (s - 0.5) * u[1] + (t - 0.5) * v[1]]
}

/** Centre of cell i of an n×n grid. */
export function cellCentre(rect: Rect, n: number, i: number): Vec2 {
  const col = i % n, row = Math.floor(i / n)
  if (isSquare(rect)) {
    const cell = rect.size / n
    return [rect.x + (col + 0.5) * cell, rect.y + (row + 0.5) * cell]
  }
  return pointAt(rect, (col + 0.5) / n, (row + 0.5) / n)
}

/** Grid coordinates of a pixel: the inverse of pointAt, solving [u v] · [s - 0.5, t - 0.5] = p - centre. */
export function toGrid(rect: Rect, x: number, y: number): Vec2 {
  const { u, v } = axesOf(rect), [cx, cy] = centreOf(rect)
  const det = u[0] * v[1] - u[1] * v[0]
  const dx = x - cx, dy = y - cy
  return [0.5 + (dx * v[1] - dy * v[0]) / det, 0.5 + (u[0] * dy - u[1] * dx) / det]
}

/** Corners of the grid: top left, top right, bottom right, bottom left. */
export function cornersOf(rect: Rect): [Vec2, Vec2, Vec2, Vec2] {
  return [pointAt(rect, 0, 0), pointAt(rect, 1, 0), pointAt(rect, 1, 1), pointAt(rect, 0, 1)]
}

/** A rect centred on (cx, cy) with edges u and v. Not rounded: a tracker moves it by fractions of a pixel. */
export function affineRect(cx: number, cy: number, u: Vec2, v: Vec2): Rect {
  const size = (Math.hypot(u[0], u[1]) + Math.hypot(v[0], v[1])) / 2
  return { x: cx - size / 2, y: cy - size / 2, size, u, v }
}

/** Side of one cell in pixels, taken from the shorter edge so a patch of a share of it stays inside the cell. */
export function cellSide(rect: Rect, n: number): number {
  if (isSquare(rect)) return rect.size / n
  const { u, v } = axesOf(rect)
  return Math.min(Math.hypot(u[0], u[1]), Math.hypot(v[0], v[1])) / n
}
