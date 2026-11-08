// The Megaminx player turns its drawing so the face a move turns is shown at a clear oblique angle. Pure; CubeView eases to what it returns.
// Spec: docs/superpowers/plans/2026-11-02-cube-megaminx-player-view.md (Task 1)
import type { Vec } from '../core/geometry'
import { apply, fromAxisAngle, mul, type Mat } from './rotation'

/** The depth toward the viewer the turning face is brought to: cos 40 degrees, a face seen at a clear slant, neither flat nor edge-on. */
export const FACE_TARGET = Math.cos((40 * Math.PI) / 180)
/** A face deeper than this is nearly square-on (the puzzle looks flat): cos about 18 degrees. The view is re-aimed. */
export const FACE_SQUARE = 0.95
/** A face shallower than this is too edge-on: cos about 57 degrees. The view is re-aimed. */
export const FACE_EDGE = 0.55

/** The Megaminx holds still this long after a move finishes before its drawing turns to the next move's face. */
export const ROTATE_DELAY_MS = 600
/** About the longest that turn takes: CubeView's ease (EASE_MS 120) closes the widest turn facingView asks for (about 140 degrees) to within EASE_EPS in roughly 790 ms at a steady frame rate, a little more with a throttled rAF. */
export const ROTATE_MS = 900

/**
 * The view after the smallest turn that brings `axis` (the move's axis in puzzle space) to a depth of FACE_TARGET, when its depth is
 * above FACE_SQUARE or below FACE_EDGE. In between the view is returned as it is, so consecutive moves on faces in sight do not make
 * the drawing swim. The turn is about the line across both the axis's viewer-space direction and the viewing direction, by just the
 * angle needed, so it never spins the picture about the viewing direction (no roll).
 */
export function facingView(view: Mat, axis: Vec): Mat {
  const d = apply(view, axis)
  const len = Math.hypot(d[0], d[1], d[2]) || 1
  const z = d[2] / len
  if (z <= FACE_SQUARE && z >= FACE_EDGE) return view
  // d x z-hat: turning about it by a positive angle swings d toward the viewer. Straight on or away has no such line; any one across the view will do.
  let about: Vec = [d[1] / len, -d[0] / len, 0]
  if (Math.hypot(about[0], about[1]) < 1e-9) about = [1, 0, 0]
  const deg = ((Math.acos(Math.max(-1, Math.min(1, z))) - Math.acos(FACE_TARGET)) * 180) / Math.PI
  return mul(fromAxisAngle(about, deg), view)
}
