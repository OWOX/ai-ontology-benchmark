// Where to turn the cube next: the face with the most unread stickers, and which edge of the camera view it
// lies past, given how the cube is held. Spec: docs/superpowers/specs/2026-10-11-cube-steps-design.md ("Guiding the turn")
import { COLORS, DOWN, G3, FACES, FACE_OF, NORMAL, RIGHT, type ColorName, type Face, type CubeGeometry, type Facelets, type Vec } from '../../core/geometry'
import type { Pose } from '../../core/pose'
import { bandsOf, type Tally } from './recognize'
import type { Side } from '../../vision/sample'

export type Direction = 'left' | 'right' | 'up' | 'down' | 'over'

const OPPOSITE: Record<Face, Face> = { U: 'D', D: 'U', F: 'B', B: 'F', L: 'R', R: 'L' }
/** Image side 0 up, 1 right, 2 down, 3 left, as a direction. */
const SIDE_DIRECTION = ['up', 'right', 'down', 'left'] as const
const dot = (a: Vec, b: Vec) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

/** The other face with the most `?` stickers; a tie goes to the earlier face in `FACES`. Null when the rest are complete. */
export function targetFace(assembled: Facelets, current: Face, g: CubeGeometry = G3): Face | null {
  let best: Face | null = null
  let most = 0
  FACES.forEach((f) => {
    if (f === current) return
    const unread = g.faceSlice(assembled, f).filter((ch) => ch === '?').length
    if (unread > most) {
      most = unread
      best = f
    }
  })
  return best
}

/** Net side of a neighbour on the face's net: 0 top, 1 right, 2 bottom, 3 left (the numbering of orient.ts). */
export const netSide = (face: Face, target: Face): Side => {
  const x = dot(NORMAL[target], RIGHT[face])
  const y = dot(NORMAL[target], DOWN[face])
  return (x === 1 ? 1 : x === -1 ? 3 : y === 1 ? 2 : 0) as Side
}

/** The four edge rows of a face in its own tally orientation, each clockwise around that face. */
const EDGE_ROWS = [[0, 1, 2], [2, 5, 8], [8, 7, 6], [6, 3, 0]]

/**
 * The roll of a face's tally against the net, from the neighbour bands: `rotateGrid(tally, r)` is the net, so tally
 * side S lies on net side (S + r) % 4. A counted band names its neighbour by the confirmed row it equals (reversed:
 * clockwise around the face is counterclockwise around the neighbour), and that neighbour sits on one net side.
 * Null when no band matched, a band matched two neighbours (it is dropped), the matched bands disagree, or a single band matched while some neighbour is not fully read.
 */
export function rollOf(t: Tally, face: Face): number | null {
  const bands = bandsOf(t, face)
  const rows = FACES.flatMap((f, k) => {
    if (f === face || f === OPPOSITE[face]) return []
    return EDGE_ROWS.map((row) => row.map((c) => t.confirmed[k * 9 + c])).filter((r) => r.every((c) => c !== null)).map((colors) => ({ f, colors: colors.reverse() }))
  })
  let roll: number | null = null
  let matched = 0
  for (const [s, band] of Object.entries(bands)) {
    const hit = new Set(rows.filter((r) => r.colors.every((c, i) => c === band![i])).map((r) => r.f))
    if (hit.size !== 1) continue
    const r = (netSide(face, [...hit][0]) - Number(s) + 4) % 4
    if (roll !== null && roll !== r) return null
    roll = r
    matched++
  }
  // One band alone could be a chance match with a neighbour not read yet. With all four neighbours complete a chance
  // match would have hit two of them and been dropped above, so one band is then enough.
  const complete = FACES.every((f, k) => f === face || f === OPPOSITE[face] || EDGE_ROWS.every((row) => row.every((c) => t.confirmed[k * 9 + c] !== null)))
  return matched >= 2 || (matched === 1 && complete) ? roll : null
}

/**
 * Which way to turn the cube so `target` comes into view. The target lies on net side n of the drawn face; the
 * drawing is the net rolled counterclockwise by `roll` (the tally's first-seen orientation, 0 once resolved) and
 * the camera shows it turned `pose.turn` clockwise, so the image side is n + turn - roll. 0 is up, 1 right, 2 down, 3 left.
 */
export function directionTo(pose: Pose, target: Face, roll = 0): Direction {
  if (target === OPPOSITE[pose.face]) return 'over'
  return SIDE_DIRECTION[(netSide(pose.face, target) + pose.turn - roll + 8) % 4]
}
