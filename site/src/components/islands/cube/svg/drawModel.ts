// What the 3D drawing needs of a puzzle, met by both the cube's geometry and the poly model: how many stickers,
// each one's polygon and outward normal, a letter's fill, and for a move the stickers it carries, its axis and its
// full angle. The cube keeps its layered turn with cut cells (turn.ts); a poly move just rotates its moving set.
// Spec: docs/superpowers/specs/2026-10-13-cube-polyhedra-design.md ("Drawing")
import { NORMAL, parseMove, type CubeGeometry, type Vec } from '../core/geometry'
import type { PolyId, PolyModel, V3 } from '../poly/model'
import { polyFill, stickerFill } from './sticker'
import { turnAngle } from './turn'

export interface DrawModel {
  count: number
  /** The sticker's polygon, inset so the background shows between stickers. */
  corners(i: number): readonly Vec[]
  normal(i: number): Vec
  /** A CSS fill for a facelet letter. */
  fill(letter: string): string
  /**
   * The cross-section of the puzzle by a poly move's cut plane (normal = the move's axis): one convex polygon, or null when the move
   * has no cut (a whole-puzzle turn) or the model draws none (the cube, which closes its cut with cells).
   */
  cut?(move: string): readonly Vec[] | null
  /** The stickers a move carries, its axis (pointing into the moving layer) and its full angle in degrees, right-hand rule. */
  turn(move: string): { moving: ReadonlySet<number>; axis: Vec; angle: number }
}

export function cubeDrawModel(g: CubeGeometry): DrawModel {
  return {
    count: g.STICKERS.length,
    corners: (i) => g.stickerCorners(i),
    normal: (i) => g.STICKERS[i].n,
    fill: stickerFill,
    turn: (move) => {
      const { face, layers: [from, to] } = parseMove(move)
      const moving = new Set<number>()
      g.STICKERS.forEach((_, i) => { if (g.inLayers(i, face, from, to)) moving.add(i) })
      return { moving, axis: NORMAL[face], angle: turnAngle(move) }
    },
  }
}

/** The farthest a vertex reaches from the middle, in the view box's units; the cube's corners reach 2.6. */
export const POLY_RADIUS = 2.4
/** A sticker's share of its full size; the cube's is 0.9 of its cell. The Pyraminx's triangles meet edge to edge at a slant, so they need more room to keep a light line. */
const INSET: Record<PolyId, number> = { pyraminx: 0.8, skewb: 0.9, megaminx: 0.9 }

const mean = (ps: readonly V3[]): V3 => [
  ps.reduce((a, p) => a + p[0], 0) / ps.length,
  ps.reduce((a, p) => a + p[1], 0) / ps.length,
  ps.reduce((a, p) => a + p[2], 0) / ps.length,
]

export function polyDrawModel(m: PolyModel): DrawModel {
  const reach = Math.max(...m.stickers.flatMap((s) => s.polygon.map((p) => Math.hypot(...p))))
  const k = POLY_RADIUS / reach
  const inset = INSET[m.id]
  const corners = m.stickers.map((s): Vec[] => {
    const c = mean(s.polygon)
    return s.polygon.map((p): Vec => [(c[0] + (p[0] - c[0]) * inset) * k, (c[1] + (p[1] - c[1]) * inset) * k, (c[2] + (p[2] - c[2]) * inset) * k])
  })
  const cuts = new Map<string, Vec[] | null>()
  const cut = (move: string): Vec[] | null => {
    if (cuts.has(move)) return cuts.get(move)!
    const { moving, axis, whole } = m.move(move)
    let result: Vec[] | null = null
    if (!whole && moving.length) {
      const at = (p: V3) => p[0] * axis[0] + p[1] * axis[1] + p[2] * axis[2]
      const inside = new Set(moving)
      let lo = Infinity, hi = -Infinity
      m.stickers.forEach((s, i) => {
        for (const p of s.polygon) {
          if (inside.has(i)) lo = Math.min(lo, at(p))
          else hi = Math.max(hi, at(p))
        }
      })
      // The plane between the moving stickers and the still ones; the puzzle is convex, so its section is the hull of the face edges' crossings.
      const d = (lo + hi) / 2
      const pts: V3[] = []
      for (const f of m.faces) for (let k = 0; k < f.polygon.length; k++) {
        const a = f.polygon[k], b = f.polygon[(k + 1) % f.polygon.length]
        const da = at(a) - d, db = at(b) - d
        if (da * db > 0 || (da === 0 && db === 0)) continue
        const t = da === db ? 0 : da / (da - db)
        const q: V3 = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]
        if (!pts.some((r) => Math.hypot(r[0] - q[0], r[1] - q[1], r[2] - q[2]) < 1e-6)) pts.push(q)
      }
      if (pts.length >= 3) {
        const c = mean(pts)
        const ax = Math.abs(axis[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0]
        const u = [axis[1] * ax[2] - axis[2] * ax[1], axis[2] * ax[0] - axis[0] * ax[2], axis[0] * ax[1] - axis[1] * ax[0]]
        const ul = Math.hypot(u[0], u[1], u[2])
        const e1 = u.map((x) => x / ul)
        const e2 = [axis[1] * e1[2] - axis[2] * e1[1], axis[2] * e1[0] - axis[0] * e1[2], axis[0] * e1[1] - axis[1] * e1[0]]
        const ang = (p: V3) => Math.atan2((p[0] - c[0]) * e2[0] + (p[1] - c[1]) * e2[1] + (p[2] - c[2]) * e2[2], (p[0] - c[0]) * e1[0] + (p[1] - c[1]) * e1[1] + (p[2] - c[2]) * e1[2])
        result = [...pts].sort((a, b) => ang(a) - ang(b)).map((p): Vec => [p[0] * k, p[1] * k, p[2] * k])
      }
    }
    cuts.set(move, result)
    return result
  }
  return {
    cut,
    count: m.count,
    corners: (i) => corners[i],
    normal: (i) => m.stickers[i].normal,
    fill: (letter) => polyFill(m, letter),
    turn: (move) => {
      const { moving, axis, angle } = m.move(move)
      return { moving: new Set(moving), axis, angle }
    },
  }
}
