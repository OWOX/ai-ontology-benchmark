// 3x3 rotation matrices (row-major) for the cube drawing, in right-handed cube space (x right, y up, z toward the
// viewer). The screen flip (y down) is not in any matrix; projectWith in CubeView.tsx applies it last.
// Spec: docs/superpowers/specs/2026-10-11-cube-angle-design.md ("The drawing")
import type { Vec } from '../core/geometry'

export type Mat = readonly [number, number, number, number, number, number, number, number, number]

export const IDENTITY: Mat = [1, 0, 0, 0, 1, 0, 0, 0, 1]

const rad = (d: number) => (d * Math.PI) / 180

export const rotX = (deg: number): Mat => {
  const c = Math.cos(rad(deg)), s = Math.sin(rad(deg))
  return [1, 0, 0, 0, c, -s, 0, s, c]
}

export const rotY = (deg: number): Mat => {
  const c = Math.cos(rad(deg)), s = Math.sin(rad(deg))
  return [c, 0, s, 0, 1, 0, -s, 0, c]
}

/**
 * Positive degrees turn clockwise as seen on screen (viewer at +z, y up), which is the opposite sense of the
 * right-handed rotation about z. That is what project's roll does once the screen flip has been applied.
 */
export const rotZ = (deg: number): Mat => {
  const c = Math.cos(rad(deg)), s = Math.sin(rad(deg))
  return [c, s, 0, -s, c, 0, 0, 0, 1]
}

export const mul = (a: Mat, b: Mat): Mat => {
  const r = new Array<number>(9)
  for (let i = 0; i < 3; i++)
    for (let j = 0; j < 3; j++) r[i * 3 + j] = a[i * 3] * b[j] + a[i * 3 + 1] * b[3 + j] + a[i * 3 + 2] * b[6 + j]
  return r as unknown as Mat
}

export const transpose = (m: Mat): Mat => [m[0], m[3], m[6], m[1], m[4], m[7], m[2], m[5], m[8]]

export const apply = (m: Mat, v: Vec): [number, number, number] => [
  m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
  m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
  m[6] * v[0] + m[7] * v[1] + m[8] * v[2],
]

/** Rodrigues' formula; the axis is normalised here so callers may pass any non-zero vector. */
export const fromAxisAngle = (axis: Vec, deg: number): Mat => {
  const n = Math.hypot(axis[0], axis[1], axis[2]) || 1
  const x = axis[0] / n, y = axis[1] / n, z = axis[2] / n
  const c = Math.cos(rad(deg)), s = Math.sin(rad(deg)), t = 1 - c
  return [t * x * x + c, t * x * y - s * z, t * x * z + s * y, t * x * y + s * z, t * y * y + c, t * y * z - s * x, t * x * z - s * y, t * y * z + s * x, t * z * z + c]
}

/** The axis and the angle in [0, 180] degrees of a rotation matrix; the axis of a zero turn is arbitrary (x). */
export const axisAngle = (m: Mat): { axis: Vec; angle: number } => {
  const cos = Math.max(-1, Math.min(1, (m[0] + m[4] + m[8] - 1) / 2))
  const x0 = m[7] - m[5], y0 = m[2] - m[6], z0 = m[3] - m[1]
  // atan2 rather than acos: acos loses half its digits near 180 degrees, where the cosine flattens out.
  const a = Math.atan2(Math.hypot(x0, y0, z0) / 2, cos)
  if (a < 1e-9) return { axis: [1, 0, 0], angle: 0 }
  const angle = (a * 180) / Math.PI
  const s = Math.sin(a)
  if (s > 1e-6) {
    const x = x0 / (2 * s), y = y0 / (2 * s), z = z0 / (2 * s)
    const n = Math.hypot(x, y, z)
    return { axis: [x / n, y / n, z / n], angle }
  }
  // Half turn: the antisymmetric part vanishes, so read the axis from (m + I) / 2 = a a^T via its largest diagonal.
  const d = [(m[0] + 1) / 2, (m[4] + 1) / 2, (m[8] + 1) / 2]
  const k = d[0] >= d[1] && d[0] >= d[2] ? 0 : d[1] >= d[2] ? 1 : 2
  const v = Math.sqrt(Math.max(d[k], 0))
  const col = [(m[k] + m[k * 3]) / 4, (m[3 + k] + m[k * 3 + 1]) / 4, (m[6 + k] + m[k * 3 + 2]) / 4]
  col[k] = v * v
  const axis = col.map((x) => x / v) as unknown as Vec
  const n = Math.hypot(axis[0], axis[1], axis[2])
  return { axis: [axis[0] / n, axis[1] / n, axis[2] / n], angle }
}
