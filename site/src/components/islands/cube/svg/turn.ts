// A face turn drawn mid-way: the layer's stickers rotated about the face normal, and the cut closed by dark cells.
// Spec: docs/superpowers/specs/2026-10-11-cube-redo-design.md ("The turn animates")
import { DOWN, NORMAL, cross, dot, RIGHT, parseMove, type CubeGeometry, type Face, type Vec } from '../core/geometry'

/** One quarter turn takes this long; a double turn is two of them with the player's pause between, as between two moves. */
export const TURN_MS = 500

/** Rodrigues: v about unit n by deg. A clockwise quarter turn seen from outside is -90 degrees, as geometry's move table has it. */
export function rotateAbout(v: Vec, n: Vec, deg: number): Vec {
  const a = (deg * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a), k = dot(n, v) * (1 - c)
  const x = cross(n, v)
  return [v[0] * c + x[0] * s + n[0] * k, v[1] * c + x[1] * s + n[1] * k, v[2] * c + x[2] * s + n[2] * k]
}
export const turnAngle = (move: string): number => {
  const t = parseMove(move).turns
  return t === 1 ? -90 : t === 2 ? -180 : 90
}
/** Ease in and out, so a turn starts and stops softly instead of snapping. */
export const ease = (p: number): number => 0.5 - Math.cos(Math.PI * Math.min(1, Math.max(0, p))) / 2

/** How long the whole move takes to animate; `gapMs` is the hold between the two quarters of a double turn. */
export const turnDuration = (move: string, gapMs: number): number => (parseMove(move).turns === 2 ? 2 * TURN_MS + gapMs : TURN_MS)

/**
 * The share (0 to 1) of the move's full angle to draw `elapsedMs` into it, easing included. A double turn eases
 * to half the angle, holds there for `gapMs`, then eases through the rest.
 */
export function turnFraction(move: string, elapsedMs: number, gapMs: number): number {
  if (parseMove(move).turns !== 2) return ease(elapsedMs / TURN_MS)
  if (elapsedMs < TURN_MS) return ease(elapsedMs / TURN_MS) / 2
  if (elapsedMs < TURN_MS + gapMs) return 0.5
  return 0.5 + ease((elapsedMs - TURN_MS - gapMs) / TURN_MS) / 2
}

/**
 * The cut as an n x n grid of cells in the plane `depth` inside the layer, each one a sticker's size and on a sticker's pitch,
 * so the gaps between stickers stay light mid-turn instead of showing one solid square behind them. Wound like
 * stickerCorners (clockwise seen from outside) for +1, reversed for -1.
 */
const cells = (n: number, face: Face, depth: number, sign: 1 | -1): Vec[][] => {
  const nr = NORMAL[face], r = RIGHT[face], d = DOWN[face], pitch = 3 / n, h = 0.45 * pitch
  const at = (a: number, b: number): Vec => [
    nr[0] * depth + r[0] * a + d[0] * b,
    nr[1] * depth + r[1] * a + d[1] * b,
    nr[2] * depth + r[2] * a + d[2] * b,
  ]
  const out: Vec[][] = []
  for (let row = 0; row < n; row++) for (let col = 0; col < n; col++) {
    const cx = -1.5 + (col + 0.5) * pitch, cy = -1.5 + (row + 0.5) * pitch
    const ring = [at(cx - h, cy - h), at(cx + h, cy - h), at(cx + h, cy + h), at(cx - h, cy + h)]
    out.push(sign === 1 ? ring : ring.reverse())
  }
  return out
}

/**
 * Which block of the cube a polygon belongs to along the turned axis: 0 the far block beyond the inner cut,
 * 1 the moving layers, 2 the near block outside the outer cut (only when the move starts below layer 1).
 * CubeView paints the parts whole, far to near, because mid-turn they interleave in centroid depth.
 */
export type Part = 0 | 1 | 2

// On a 2x2 the cut is the cube's middle plane, so the two grids coincide and the viewer's side culls one by its normal.
// Every cut is a still grid of cells (closing its block) and a rotating one (closing the moving layers); the inner cut comes first.
/** `fraction` is the share of the move's full angle already drawn (turnFraction's output, eased), 0 to 1. */
export function layerPolygons(g: CubeGeometry, move: string, fraction: number) {
  const { face, layers: [from, to] } = parseMove(move)
  const n = NORMAL[face], deg = turnAngle(move) * fraction
  const back: Vec = [-n[0], -n[1], -n[2]]
  const stickers = new Map<number, { corners: Vec[]; normal: Vec; part: Part }>()
  g.STICKERS.forEach((s, i) => {
    if (g.inLayers(i, face, from, to)) stickers.set(i, { corners: g.stickerCorners(i).map((c) => rotateAbout(c, n, deg)), normal: rotateAbout(s.n, n, deg), part: 1 })
  })
  const [inner, outer] = g.cutPlanes(move)
  type Cut = { corners: Vec[]; normal: Vec; part: Part }
  const grid = (depth: number, sign: 1 | -1, normal: Vec, part: Part, rotated: boolean): Cut[] =>
    cells(g.n, face, depth, sign).map((corners) => ({ corners: rotated ? corners.map((c) => rotateAbout(c, n, deg)) : corners, normal, part }))
  const cuts: Cut[] = [
    ...grid(inner, 1, n, 0, false),
    ...grid(inner, -1, back, 1, true),
  ]
  // The outer cut mirrors the inner one: the still cells face inward at the near block, the turning ones outward.
  if (outer !== undefined) cuts.push(
    ...grid(outer, -1, back, 2, false),
    ...grid(outer, 1, n, 1, true),
  )
  return { stickers, cuts }
}
