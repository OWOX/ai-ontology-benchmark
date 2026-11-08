// Which stickers a neighbour band shows. A face captured from the camera and assembled with rotation r
// (rotateGrid, clockwise quarter turns) has its image side s on net side (s + r) mod 4. Net sides are
// numbered clockwise: 0 top (-DOWN), 1 right (RIGHT), 2 bottom (DOWN), 3 left (-RIGHT), in the face's net
// axes. Band patches are listed clockwise around the square, which the rotation preserves.
// Spec: docs/superpowers/specs/2026-10-09-cube-orientation-design.md
import { DOWN, FACES, FACE_OF, NORMAL, RIGHT, G3, type ColorName, type CubeGeometry, type Face, type Facelets, type Vec } from '../../core/geometry'
import type { Side } from '../../vision/sample'

export type Bands = Partial<Record<Side, ColorName[]>>

const neg = (v: Vec): Vec => [-v[0], -v[1], -v[2]]
const dot = (a: Vec, b: Vec) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
/** Outward direction of a net side, and the clockwise tangent along it. */
const outward = (f: Face, s: Side): Vec => [neg(DOWN[f]), RIGHT[f], DOWN[f], neg(RIGHT[f])][s]
const along = (f: Face, s: Side): Vec => [RIGHT[f], DOWN[f], neg(RIGHT[f]), neg(DOWN[f])][s]

/** Facelet indices of the neighbouring face's row that touches `face` on `side`, in clockwise band order. */
export function neighbourRow(face: Face, side: Side, g: CubeGeometry = G3): number[] {
  const o = outward(face, side), a = along(face, side), n = NORMAL[face]
  const nb = FACES.find((f) => dot(NORMAL[f], o) === 1)!
  return g.STICKERS.map((s, i) => ({ s, i }))
    .filter(({ s }) => s.face === nb && dot(s.p, n) === g.n - 1)
    .sort((p, q) => dot(p.s.p, a) - dot(q.s.p, a))
    .map(({ i }) => i)
}

/** True when every band of the face, read on image side s, matches the candidate's neighbour row on net side (s + r) mod 4. */
export function bandsAgree(facelets: Facelets, face: Face, r: number, bands: Bands, g: CubeGeometry = G3): boolean {
  for (const [s, colors] of Object.entries(bands)) {
    const side = ((Number(s) + r) % 4) as Side
    const row = neighbourRow(face, side, g)
    if (!row.every((j, k) => facelets[j] === FACE_OF[colors![k]])) return false
  }
  return true
}
