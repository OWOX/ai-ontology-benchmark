// How the cube is held, as the drawing needs it: the face in view and its turn against the drawn face.
// `turn` is the number of clockwise quarter turns that carry the drawn face onto the live reading, so the
// drawing rolls by turn * 90 degrees clockwise to look like what the camera sees.
// `tilt` is the camera's lean on that face, in degrees; the far-side view is the 180-degree turn of the whole
// view about the vertical axis, which keeps yaw and negates pitch and roll (spec "The pose" item 3).
// Spec: docs/superpowers/specs/2026-10-11-cube-recognition-design.md ("Following the cube"), docs/superpowers/specs/2026-10-11-cube-angle-design.md
import { COLOR_OF, rotateGrid, type ColorName, type Face } from './geometry'

export interface Pose {
  face: Face
  /** Clockwise quarter turns, 0..3. */
  turn: number
  /** How the camera sees the face, when it was measured. */
  tilt?: Tilt
}

export interface Tilt {
  yaw: number
  pitch: number
  roll: number
}

/** Degrees by which a tilt must move before the drawing follows, so a steady hand does not stir it. */
export const TILT_EPS = 4

/** True when some angle differs by TILT_EPS or more. */
export const tiltDiffers = (a: Tilt, b: Tilt): boolean =>
  Math.abs(a.yaw - b.yaw) >= TILT_EPS || Math.abs(a.pitch - b.pitch) >= TILT_EPS || Math.abs(a.roll - b.roll) >= TILT_EPS

/**
 * The turn of a live reading against the drawn face: the one of the four `rotateGrid` turns under which the
 * most cells agree. `?` and null cells never agree. A tie keeps `prev`, so a symmetric face does not flicker.
 */
export function turnOf(drawn: readonly string[] | string, read: readonly (ColorName | null)[], prev: number): number {
  const cells = [...drawn].map((ch) => (ch === '?' ? null : COLOR_OF[ch as Face]))
  const score = [0, 1, 2, 3].map((t) => rotateGrid(cells, t).reduce((n, c, i) => n + (c !== null && c === read[i] ? 1 : 0), 0))
  const best = Math.max(...score)
  return score[prev] === best ? prev : score.indexOf(best)
}

const OPPOSITE: Record<Face, Face> = { U: 'D', D: 'U', F: 'B', B: 'F', L: 'R', R: 'L' }

/**
 * The pose as a visitor on the far side of the cube sees it: the opposite face, and the turn negated, since a
 * clockwise roll for the camera is counterclockwise from behind. Side faces keep U on top in both views; U and D
 * swap their top neighbour (B over U, F over D in the net), so those get a half turn as well.
 */
export const fromOpposite = (pose: Pose): Pose => ({
  face: OPPOSITE[pose.face],
  turn: ((pose.face === 'U' || pose.face === 'D' ? 2 : 0) - pose.turn + 4) % 4,
  // 0 - x, not -x: a zero angle maps to +0, not -0, which toEqual tells apart
  ...(pose.tilt && { tilt: { yaw: pose.tilt.yaw, pitch: 0 - pose.tilt.pitch, roll: 0 - pose.tilt.roll } }),
})
