// The turn direction drawn on the cube: an arrow along the centre line of the moving layer, across the clearly visible
// adjacent faces, with an arrowhead where the layer is heading. Pure; CubeView renders what it returns.
// Spec: docs/superpowers/specs/2026-10-09-cube-orientation-design.md (item 6)
import { FACES, NORMAL, cross, dot, parseMove, type CubeGeometry, type Vec } from '../core/geometry'
import type { Pt } from './hull'
import type { DrawModel } from './drawModel'
import { turnAngle } from './turn'

/** The arrow starts and ends this far inside the band's end cells, not on the cube's edge. */
const INSET = 0.35
/** A face counts as visible only when it clearly faces the viewer, not edge-on. */
const VISIBLE = 0.25
const HEAD = 0.4

const scale = (a: Vec, k: number): Vec => [a[0] * k, a[1] * k, a[2] * k]
const plus = (a: Vec, b: Vec): Vec => [a[0] + b[0], a[1] + b[1], a[2] + b[2]]

/** One drawn arrow: the stroke's points and the arrowhead's three corners, in screen coordinates. */
export interface Arrow { path: Pt[]; head: Pt[] }

/**
 * One arrow per moving layer, each along its own layer's centre line, so a wide move (`Uw` on a 4x4) shows both layers move.
 * Empty when no adjacent face is clearly visible (a face held square-on).
 * `project` maps cube space to screen x, y (down) and depth toward the viewer.
 */
export function bandArrow(g: CubeGeometry, project: (v: Vec) => readonly number[], move: string): Arrow[] {
  const { face, layers: [from, to] } = parseMove(move)
  const n = NORMAL[face]
  const sign = Math.sign(turnAngle(move))
  const visible = FACES.map((f) => NORMAL[f])
    .filter((a) => dot(a, n) === 0 && project(a)[2] > VISIBLE)
    .map((a) => ({ a, t: scale(cross(n, a), sign) as Vec }))
  if (visible.length === 0) return []
  // Two visible faces are consecutive in the motion: the second is the one the first moves onto.
  if (visible.length === 2 && dot(visible[1].a, visible[0].t) !== 1) visible.reverse()
  const xy = (p: Vec): Pt => { const [x, y] = project(p); return [x, y] }
  const first = visible[0], last = visible[visible.length - 1]

  /** The arrow along the centre line of layer k (1-based from the moving face). */
  const layerArrow = (k: number): Arrow => {
    const h = (k - 0.5) * (3 / g.n)
    const depth = 1.5 - h
    const centre = ({ a }: { a: Vec }): Vec => plus(scale(a, 1.5), scale(n, depth))
    const cFirst = centre(first), cLast = centre(last)
    const points: Vec[] = [plus(cFirst, scale(first.t, -(1.5 - INSET)))]
    if (visible.length === 2) points.push(plus(cFirst, scale(first.t, 1.5)))
    points.push(plus(cLast, scale(last.t, 1.5 - INSET)))
    const path = points.map(xy)
    // The head lies in the last face's plane, so it is foreshortened with the face: tip at the end, base HEAD back along the band, corners either side along the turned face's normal.
    const end = points[points.length - 1]
    const base = plus(end, scale(last.t, -HEAD))
    path[path.length - 1] = xy(base)
    return { path, head: [xy(end), xy(plus(base, scale(n, 0.16))), xy(plus(base, scale(n, -0.16)))] }
  }
  return Array.from({ length: to - from + 1 }, (_, i) => layerArrow(from + i))
}

/** A poly sticker is a band sticker (a side sticker of the moving layer) only when its normal is at least this far off the move's axis: cos 30 degrees, in the dot product. */
const BAND_COS = Math.cos((30 * Math.PI) / 180)
/** The band is the side stickers whose centres lie within this of the nearest one's height along the axis. */
const BAND_TOL = 0.1
/** The path covers at most this share of the ring, so a ring seen whole does not close on itself. */
const RING_SHARE = 2 / 3
/** Half the head's width on the screen, either side of the path. The cube's head is HEAD (0.4) long and 0.32 wide at the default view; this one is 0.4 wide, a little more, because a ring seen at a slant looks thinner. */
const POLY_HEAD_HALF = 0.2

/** Per-puzzle tuning of the band rule. */
export interface PolyBandOptions {
  /** Only stickers whose normal points along the axis (toward the side the viewer is shown) can be in the band. */
  toward?: boolean
}

/** The band rule's options for a puzzle: the Skewb's stickers nearest its cut face away from the corner that turns, so its band is taken from those that face it. */
export const polyBandOptions = (m: { id: string }): PolyBandOptions => (m.id === 'skewb' ? { toward: true } : {})

/**
 * The cube's band arrow for a poly move: an arrow along the ring of moving side stickers next to the cut, across those that
 * clearly face the viewer (a depth above VISIBLE), heading the way the layer turns. One arrow, or [] when fewer than two band
 * stickers are visible or the move has no cut (a whole-puzzle turn).
 * The ring is the moving stickers whose normal is BAND_COS or less along the axis (not the turning face), within BAND_TOL of
 * the one nearest the cut. They are ordered by angle around the axis in the turn's direction, the longest circular run of
 * visible ones is kept, and their centres are pulled onto the ring's mean radius and height, so the path is smooth.
 */
export function polyBandArrow(model: DrawModel, project: (v: Vec) => readonly number[], move: string, opts: PolyBandOptions = {}): Arrow[] {
  const section = model.cut?.(move)
  const { moving, axis, angle } = model.turn(move)
  if (!section || !moving.size) return []
  const sign = Math.sign(angle) || 1
  const at = (v: Vec) => dot(v, axis)
  const cutAt = at(section[0])
  const side: { c: Vec; h: number; n: Vec }[] = []
  for (const i of moving) {
    const n = model.normal(i)
    if (Math.abs(at(n)) > BAND_COS || (opts.toward && at(n) <= 0)) continue
    const corners = model.corners(i)
    const c: Vec = [0, 1, 2].map((k) => corners.reduce((a, v) => a + v[k], 0) / corners.length) as unknown as Vec
    side.push({ c, h: at(c), n })
  }
  if (!side.length) return []
  const near = Math.min(...side.map((s) => Math.abs(s.h - cutAt)))
  const band = side.filter((s) => Math.abs(s.h - cutAt) <= near + BAND_TOL)
  const h = band.reduce((a, s) => a + s.h, 0) / band.length
  const radial = band.map((s) => plus(s.c, scale(axis, -s.h)))
  const r = radial.reduce((a, v) => a + Math.hypot(...v), 0) / band.length
  // Seen from the axis's tip, the layer turns counterclockwise for a positive angle: the angle about the axis grows with the motion.
  const seed: Vec = Math.abs(axis[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0]
  const e1 = scale(cross(axis, cross(seed, axis)), 1 / Math.hypot(...cross(axis, cross(seed, axis))))
  const e2 = cross(axis, e1)
  const ordered = band
    .map((s, k) => ({ s, u: scale(radial[k], 1 / Math.hypot(...radial[k])), a: sign * Math.atan2(dot(radial[k], e2), dot(radial[k], e1)) }))
    .sort((x, y) => x.a - y.a)
  const seen = ordered.map((o) => project(o.s.n)[2] > VISIBLE)
  // The longest circular run of visible stickers.
  const n = ordered.length
  let best = { start: 0, length: 0 }
  if (seen.every(Boolean)) best = { start: 0, length: n }
  else {
    const gap = seen.indexOf(false)
    for (let k = 0, run = 0; k < n; k++) {
      const i = (gap + 1 + k) % n
      run = seen[i] ? run + 1 : 0
      if (run > best.length) best = { start: (i - run + 1 + n) % n, length: run }
    }
  }
  if (best.length < 2) return []
  // A whole ring in sight would wrap the path round and meet the head with the tail: keep the last RING_SHARE of it, ending in the turn's direction.
  const keep = Math.min(best.length, Math.floor(n * RING_SHARE))
  const run = Array.from({ length: keep }, (_, k) => ordered[(best.start + best.length - keep + k) % n])
  if (run.length < 2) return []
  const onRing = (u: Vec): Vec => plus(scale(axis, h), scale(u, r))
  const points = run.map((o) => onRing(o.u))
  // The head is built on the screen, as the arc's is: its base HEAD back along the projected path from the tip, its corners
  // perpendicular to the projected path, so it keeps its size however the ring is foreshortened or seen along the axis.
  const xy = (p: Vec): Pt => { const [x, y] = project(p); return [x, y] }
  const flat = points.map(xy)
  const tip = flat[flat.length - 1]
  let j = flat.length - 1, left = HEAD
  let q: Pt = flat[0]
  for (; j >= 1; j--) {
    const a = flat[j - 1], b = flat[j]
    const seg = Math.hypot(b[0] - a[0], b[1] - a[1])
    if (seg > left) {
      const t = left / seg
      q = [b[0] + (a[0] - b[0]) * t, b[1] + (a[1] - b[1]) * t]
      break
    }
    left -= seg
  }
  // A path shorter than the head has no room for a stroke.
  if (j < 1) return []
  const d = Math.hypot(tip[0] - q[0], tip[1] - q[1]) || 1
  const ux = (tip[0] - q[0]) / d, uy = (tip[1] - q[1]) / d
  const head: Pt[] = [tip, [q[0] - uy * POLY_HEAD_HALF, q[1] + ux * POLY_HEAD_HALF], [q[0] + uy * POLY_HEAD_HALF, q[1] - ux * POLY_HEAD_HALF]]
  return [{ path: [...flat.slice(0, j), q], head }]
}
