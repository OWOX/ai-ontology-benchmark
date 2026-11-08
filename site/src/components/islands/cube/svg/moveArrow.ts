// The turn direction beside the cube: an arc around the moving face's plane, drawn only where it clears the cube's
// drawing, with an arrowhead at the end the layer turns toward. Pure; CubeView renders what it returns.
// Spec: docs/superpowers/specs/2026-10-09-cube-orientation-design.md (item 6)
import { NORMAL, parseMove, type Vec } from '../core/geometry'
import { convexHull, distanceToHull, outsideHull, type Pt } from './hull'
import { rotateAbout, turnAngle } from './turn'
import type { DrawModel } from './drawModel'

/** Past the face's half-diagonal (2.12), so the whole circle clears the face itself. */
export const ARROW_R = 2.3
const STEP = 5
const MIN_DEG = 60
const MAX_DEG = 150
const HEAD = 0.35
/** A sample is clear only this far from the silhouette: the stroke's half-width 0.045 (width 0.09) plus the sticker outline 0.03 and a visible gap; it also covers a segment cutting a hull corner between samples. */
export const ARROW_MARGIN = 0.14
/** The head's corners must keep at least the stroke's half-width from the silhouette. */
const HEAD_MARGIN = 0.05

const CORNERS: Vec[] = [-1.5, 1.5].flatMap((x) => [-1.5, 1.5].flatMap((y) => [-1.5, 1.5].map((z): Vec => [x, y, z])))

/**
 * The arc and its arrowhead in screen coordinates, or null when less than MIN_DEG of the circle is clear of the cube.
 * `project` maps cube space to screen x, y. The cube's drawing is the hull of its projected corners, so a point outside the hull is in front of nothing.
 */
export function moveArrow(project: (v: Vec) => readonly number[], move: string): { path: Pt[]; head: Pt[] } | null {
  const n = NORMAL[parseMove(move).face]
  return arcArrow(project, CORNERS, [n[0] * 1.5, n[1] * 1.5, n[2] * 1.5], n, Math.sign(turnAngle(move)), ARROW_R)
}

/**
 * The same arc for any shape: a circle of `radius` about the axis `n` through `centre`, kept where it clears the hull of
 * `outline` (the shape's vertices) once projected, turning toward `sign` (+1 right-hand about `n`, -1 the other way).
 */
export function arcArrow(project: (v: Vec) => readonly number[], outline: readonly Vec[], centre: Vec, n: Vec, sign: number, radius: number): { path: Pt[]; head: Pt[] } | null {
  // Any unit vector in the face's plane starts the sweep.
  const seed: Vec = Math.abs(n[1]) < 0.5 ? [0, 1, 0] : [1, 0, 0]
  const along = n[0] * seed[0] + n[1] * seed[1] + n[2] * seed[2]
  const spoke: Vec = [seed[0] - n[0] * along, seed[1] - n[1] * along, seed[2] - n[2] * along]
  const len = Math.hypot(...spoke)
  const count = 360 / STEP
  const hull = convexHull(outline.map((c): Pt => { const [x, y] = project(c); return [x, y] }))
  const samples = Array.from({ length: count }, (_, k) => {
    const r = rotateAbout(spoke, n, sign * k * STEP)
    const [x, y] = project([centre[0] + (r[0] / len) * radius, centre[1] + (r[1] / len) * radius, centre[2] + (r[2] / len) * radius])
    return [x, y] as Pt
  })
  const clear = samples.map((p) => outsideHull(hull, p) && distanceToHull(hull, p) >= ARROW_MARGIN)
  // The longest circular run of clear samples.
  let best = { start: 0, length: 0 }
  if (clear.every(Boolean)) best = { start: 0, length: count }
  else {
    const first = clear.findIndex((c) => !c)
    for (let k = 0, run = 0; k < count; k++) {
      const i = (first + 1 + k) % count
      run = clear[i] ? run + 1 : 0
      if (run > best.length) best = { start: (i - run + 1 + count) % count, length: run }
    }
  }
  if ((best.length - 1) * STEP < MIN_DEG) return null
  let keep = Math.min(best.length, MAX_DEG / STEP + 1)
  const from = best.start + best.length - keep
  const all = Array.from({ length: keep }, (_, k) => samples[(from + k) % count])
  // The head's corners reach sideways past its tip, toward the cube, so the arc is shortened from its end until they clear it too.
  // The view's edge is not checked: mid-drag the arc can pass it, and the svg lets it spill (overflow: visible in _cube.astro) rather than lose the arrow.
  // The head's base sits HEAD of path length back from the tip and the head aims along tip - base, so it follows the arc's last stretch
  // instead of the last 5 degree chord (which leans off a sharply curved projection). The stroke stops at the base midpoint: ending it at the
  // tip would let its round cap run under the head and poke out past it as a nub.
  for (; keep >= 2; keep--) {
    const tip = all[keep - 1]
    let j = keep - 1, left = HEAD
    let q: Pt = all[0]
    for (; j >= 1; j--) {
      const a = all[j - 1], b = all[j]
      const seg = Math.hypot(b[0] - a[0], b[1] - a[1])
      // Strict: when the segment ends exactly at q, the next iteration lands on it, so the path never repeats its last point.
      if (seg > left) {
        const t = seg ? left / seg : 0
        q = [b[0] + (a[0] - b[0]) * t, b[1] + (a[1] - b[1]) * t]
        break
      }
      left -= seg
    }
    // j is the segment [all[j - 1], all[j]] holding q; if the whole path is shorter than HEAD, q stays the first point and j is 0.
    const d = Math.hypot(tip[0] - q[0], tip[1] - q[1]) || 1
    const ux = (tip[0] - q[0]) / d, uy = (tip[1] - q[1]) / d
    const head: Pt[] = [tip, [q[0] - uy * HEAD / 2, q[1] + ux * HEAD / 2], [q[0] + uy * HEAD / 2, q[1] - ux * HEAD / 2]]
    if (head.every((h) => outsideHull(hull, h) && distanceToHull(hull, h) >= HEAD_MARGIN)) return (keep - 1) * STEP < MIN_DEG ? null : { path: [...all.slice(0, j), q], head }
  }
  return null
}

/** Beyond the moving stickers' reach, to clear them; and how much farther to try when the circle is hidden behind the puzzle. */
const POLY_GAP = 0.3
const POLY_GROW = 0.25
const POLY_TRIES = 5

/**
 * The turn arrow of a poly move: an arc around the move's axis where it leaves the puzzle, in the plane of the moving
 * layer's outermost point. The circle starts just wider than the moving stickers and widens until some stretch of it clears
 * the puzzle's silhouette, or null when none does.
 */
export function polyMoveArrow(project: (v: Vec) => readonly number[], model: DrawModel, move: string): { path: Pt[]; head: Pt[] } | null {
  const { moving, axis, angle } = model.turn(move)
  if (!moving.size) return null
  const outline: Vec[] = []
  let height = -Infinity, reach = 0
  for (let i = 0; i < model.count; i++) for (const v of model.corners(i)) {
    outline.push(v)
    if (!moving.has(i)) continue
    const h = v[0] * axis[0] + v[1] * axis[1] + v[2] * axis[2]
    height = Math.max(height, h)
    reach = Math.max(reach, Math.hypot(v[0] - axis[0] * h, v[1] - axis[1] * h, v[2] - axis[2] * h))
  }
  const centre: Vec = [axis[0] * height, axis[1] * height, axis[2] * height]
  for (let t = 0; t < POLY_TRIES; t++) {
    const a = arcArrow(project, outline, centre, axis, Math.sign(angle), reach + POLY_GAP + t * POLY_GROW)
    if (a) return a
  }
  return null
}
