// A sticker model of the Pyraminx, Skewb and Megaminx, built from cubing.js's
// PuzzleGeometry. It is the same geometry the KPuzzle is made from, so each
// sticker's (orbit, ord, ori) label is the KPuzzle's own slot. cubing.js loads
// lazily, so the cube pages pay nothing until a poly puzzle is picked.
import type { KPuzzle } from 'cubing/kpuzzle'

export type PolyId = 'pyraminx' | 'skewb' | 'megaminx'
export type V3 = [number, number, number]

export interface PolyFace {
  index: number
  letter: string
  name: string
  normal: V3
  polygon: V3[]
}

export interface PolySticker {
  face: number
  polygon: V3[]
  normal: V3
  orbit: string
  ord: number
  ori: number
}

export interface PolyMove {
  name: string
  /** next[j] = f[perm[j]] */
  perm: Uint16Array
  /** Stickers that turn with the move, a turning face's centre included. */
  moving: number[]
  /** Points into the moving layer. */
  axis: V3
  /** Degrees, right-hand rule about `axis`. */
  angle: number
  whole: boolean
}

export interface PolyModel {
  id: PolyId
  faces: PolyFace[]
  stickers: PolySticker[]
  perFace: number
  count: number
  SOLVED: string
  blank(): string
  isSolved(f: string): boolean
  move(name: string): PolyMove
  applyMove(f: string, name: string): string
  applyMoves(f: string, names: readonly string[]): string
  SOLVER_MOVES: readonly string[]
  ROTATIONS: readonly Uint16Array[]
  kpuzzle: unknown
}

/** The move families the solvers emit. */
const SOLVER_MOVES: Record<PolyId, readonly string[]> = {
  pyraminx: ['U', 'L', 'R', 'B', 'u', 'l', 'r', 'b'],
  skewb: ['U', 'L', 'R', 'B'],
  megaminx: ['U', 'F', 'L', 'BL', 'BR', 'R', 'FR', 'FL', 'DL', 'B', 'DR', 'D'],
}

/** Whole-puzzle turns that generate the rotation group. The Skewb needs `x`:
 *  `Rv` and `Uv` alone give only its 12-element tetrahedral subgroup. */
const ROTATION_MOVES: Record<PolyId, readonly string[]> = {
  pyraminx: ['Uv', 'Rv'],
  skewb: ['Rv', 'x'],
  megaminx: ['Rv', 'Uv'],
}

/** The order of the orbits inside a face, which the camera templates and the
 *  reader's face keys depend on. Pyraminx: tips (CORNERS2), then the axial
 *  vertices (CORNERS), then edges. */
const ORBIT_ORDER: Record<PolyId, readonly string[]> = {
  pyraminx: ['CORNERS2', 'CORNERS', 'EDGES'],
  skewb: ['CENTERS', 'CORNERS'],
  megaminx: ['CENTERS', 'CORNERS', 'EDGES'],
}

const EPS = 1e-6

const sub = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const add = (a: V3, b: V3): V3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
const scale = (a: V3, s: number): V3 => [a[0] * s, a[1] * s, a[2] * s]
const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
const norm = (a: V3) => Math.hypot(a[0], a[1], a[2])
const unit = (a: V3): V3 => scale(a, 1 / norm(a))
const mean = (ps: V3[]): V3 => scale(ps.reduce(add, [0, 0, 0] as V3), 1 / ps.length)

/** Rodrigues: `v` turned by `th` radians about the unit axis `u`. */
function rotate(v: V3, u: V3, th: number): V3 {
  const c = Math.cos(th)
  const s = Math.sin(th)
  return add(add(scale(v, c), scale(cross(u, v), s)), scale(u, dot(u, v) * (1 - c)))
}

const triples = (c: number[]): V3[] => {
  const r: V3[] = []
  for (let i = 0; i < c.length; i += 3) r.push([c[i], c[i + 1], c[i + 2]])
  return r
}

/** Convex hull of coplanar points, counterclockwise about the normal `n`. */
function hull(points: V3[], n: V3): V3[] {
  const uniq: V3[] = []
  for (const p of points) if (!uniq.some((q) => norm(sub(p, q)) < EPS)) uniq.push(p)
  const c = mean(uniq)
  const ax = unit(sub(uniq[0], c))
  const ay = cross(n, ax)
  const ang = (p: V3) => Math.atan2(dot(sub(p, c), ay), dot(sub(p, c), ax))
  const sorted = [...uniq].sort((a, b) => ang(a) - ang(b))
  // the merged pieces share edges; drop vertices that lie on a straight run
  return sorted.filter((p, i) => {
    const a = sorted[(i - 1 + sorted.length) % sorted.length]
    const b = sorted[(i + 1) % sorted.length]
    return norm(cross(sub(p, a), sub(b, p))) > EPS
  })
}

const samePolygon = (a: V3[], b: V3[]) => a.length === b.length && a.every((p) => b.some((q) => norm(sub(p, q)) < EPS))

interface Loader {
  pg(): Promise<any> // PuzzleGeometry, which cubing.js exports no usable type for
  kpuzzle(): Promise<KPuzzle>
}

/** Builds the model, uncached. `loadPolyModel` is the entry point. */
export async function buildPolyModel(id: PolyId): Promise<PolyModel> {
  // `puzzles[id].pg()` and `.kpuzzle()` give the solvers' own geometry. The
  // default `getPuzzleGeometryByName` gives different pieces (the Skewb's
  // above all), whose labels do not match the solvers' KPuzzle slots.
  const { puzzles } = await import('cubing/puzzles')
  const loader = puzzles[id] as unknown as Loader
  const pg = await loader.pg()
  const kpuzzle = await loader.kpuzzle()
  const g = pg.get3d()

  const faces: PolyFace[] = g.faces.map((f: { coords: number[]; name: string }, index: number) => {
    const polygon = triples(f.coords)
    const n = unit(cross(sub(polygon[1], polygon[0]), sub(polygon[2], polygon[1])))
    return {
      index,
      letter: String.fromCharCode(97 + index),
      name: f.name,
      normal: dot(n, mean(polygon)) < 0 ? scale(n, -1) : n,
      polygon,
    }
  })

  // `orientCenters` splits a Skewb or Megaminx centre into 4 or 5 polygons that
  // share one piece (same ord). Merge them back into one sticker.
  type Raw = { face: number; polygon: V3[]; orbit: string; ord: number; ori: number }
  const raw: Raw[] = []
  const centres = new Map<number, Raw>()
  for (const s of g.stickers as { coords: number[]; orbit: string; ord: number; ori: number; face: number }[]) {
    const polygon = triples(s.coords)
    if (s.orbit === 'CENTERS') {
      const c = centres.get(s.ord)
      if (c) c.polygon.push(...polygon)
      else {
        const r = { face: s.face, polygon, orbit: s.orbit, ord: s.ord, ori: 0 }
        centres.set(s.ord, r)
        raw.push(r)
      }
    } else raw.push({ face: s.face, polygon, orbit: s.orbit, ord: s.ord, ori: s.ori })
  }
  for (const r of centres.values()) r.polygon = hull(r.polygon, faces[r.face].normal)

  // Order inside a face: groups by (orbit, distance from the centre), each
  // group counterclockwise seen from outside, starting at the face polygon's
  // first vertex. A face turn by one step then shifts each group by one, which
  // the camera reader relies on (a mirrored read matches nothing).
  const stickers: PolySticker[] = []
  for (const f of faces) {
    const c = mean(f.polygon)
    const ax = unit(sub(f.polygon[0], c))
    const ay = cross(f.normal, ax)
    const ang = (p: V3) => {
      const a = Math.atan2(dot(sub(p, c), ay), dot(sub(p, c), ax))
      return a < -EPS ? a + 2 * Math.PI : a
    }
    const groups = new Map<string, { r: Raw; at: V3 }[]>()
    for (const r of raw) {
      if (r.face !== f.index) continue
      const at = mean(r.polygon)
      const key = `${r.orbit}:${norm(sub(at, c)).toFixed(4)}`
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key)!.push({ r, at })
    }
    const rank = (key: string) => ORBIT_ORDER[id].indexOf(key.split(':')[0])
    const ordered = [...groups.entries()].sort(([a], [b]) => rank(a) - rank(b) || (a < b ? -1 : 1))
    for (const [, group] of ordered) {
      group.sort((a, b) => ang(a.at) - ang(b.at))
      for (const { r } of group) {
        stickers.push({ face: f.index, polygon: r.polygon, normal: f.normal, orbit: r.orbit, ord: r.ord, ori: r.ori })
      }
    }
  }
  const count = stickers.length
  const perFace = count / faces.length
  const SOLVED = stickers.map((s) => faces[s.face].letter).join('')

  const orbits = kpuzzle.definition.orbits
  const slot = new Map<string, number>()
  stickers.forEach((s, i) => slot.set(`${s.orbit}:${s.ord}:${s.ori}`, i))

  // Stickers per piece. A merged centre is one sticker, although the KPuzzle
  // gives its orbit 4 or 5 orientations.
  const width = new Map<string, number>()
  for (const s of stickers) width.set(s.orbit, Math.max(width.get(s.orbit) ?? 0, s.ori + 1))

  /** A KPuzzle transformation as a sticker permutation. The orientation sign
   *  is -1 on all three puzzles: sticker k of a piece with twist o shows
   *  solved sticker k - o. cubing.js does not document it; it is the sign that
   *  turns every solver move into a rigid rotation. The rigid-fit test is what
   *  locks it: the KPuzzle-agreement test uses this same sign, so it cannot
   *  catch a wrong one. */
  const permOf = (t: { transformationData: Record<string, { permutation: number[]; orientationDelta: number[] }> }) => {
    const perm = new Uint16Array(count)
    for (const o of orbits) {
      const d = t.transformationData[o.orbitName]
      for (let i = 0; i < o.numPieces; i++) {
        const n = width.get(o.orbitName)!
        for (let k = 0; k < n; k++) {
          const from = (((k - d.orientationDelta[i]) % n) + n) % n
          perm[slot.get(`${o.orbitName}:${i}:${k}`)!] = slot.get(`${o.orbitName}:${d.permutation[i]}:${from}`)!
        }
      }
    }
    return perm
  }

  // PuzzleGeometry's rotation axes (with their orders) are the only ones a
  // move can turn about.
  const axes: { u: V3; order: number }[] = g.axis.map((a: { coordinates: number[]; order: number }) => ({
    u: unit(a.coordinates as V3),
    order: a.order,
  }))

  /** The axis and angle (radians) of the rotation that carries every moved
   *  sticker's polygon onto its target: sticker perm[j] lands on position j. */
  const fit = (perm: Uint16Array) => {
    const moved: number[] = []
    for (let j = 0; j < count; j++) if (perm[j] !== j) moved.push(j)
    for (const { u, order } of axes) {
      for (let k = 1; k < order; k++) {
        const th = (2 * Math.PI * k) / order
        if (moved.every((j) => samePolygon(stickers[perm[j]].polygon.map((p) => rotate(p, u, th)), stickers[j].polygon))) {
          return { u, th }
        }
      }
    }
    return null
  }

  const centreOf = stickers.map((s) => mean(s.polygon))

  /** A Skewb turns about 8 corners but the solver names 4. The other four are
   *  the named four carried over by a whole-puzzle turn, written with an `o`
   *  ("opposite") after the family: `Uo` turns the corner opposite `U`, the
   *  same way. A visitor holding the puzzle another way needs them; the solver
   *  never emits them. */
  const permOfName = (name: string): Uint16Array => {
    if (id !== 'skewb' || !/^[ULRB]o'?$/.test(name)) {
      try {
        return permOf(kpuzzle.moveToTransformation(name) as never)
      } catch {
        throw new Error(`${id}: unknown move ${name}`)
      }
    }
    const base = move(name.replace('o', ''))
    for (const r of ROTATIONS) {
      const q = new Uint16Array(count)
      for (let j = 0; j < count; j++) q[r[j]] = r[base.perm[j]]
      const moved = Array.from(q, (v, j) => j).filter((j) => q[j] !== j)
      if (dot(unit(mean(moved.map((j) => centreOf[j]))), base.axis) < -0.5) return q
    }
    throw new Error(`${id}: no corner opposite ${name}`)
  }
  const moves = new Map<string, PolyMove>()
  const move = (name: string): PolyMove => {
    let m = moves.get(name)
    if (m) return m
    const perm = permOfName(name)
    const r = fit(perm)
    if (!r) throw new Error(`${id}: move ${name} is not a rigid rotation of its stickers`)
    let { u, th } = r
    const spins = (i: number) => samePolygon(stickers[i].polygon.map((p) => rotate(p, u, th)), stickers[i].polygon)
    const whole = stickers.every((_, i) => perm[i] !== i || spins(i))
    const moved = stickers.map((_, i) => i).filter((i) => perm[i] !== i)
    // the axis points into the moving layer; flipping it negates the angle
    if (!whole && dot(u, mean(moved.map((i) => centreOf[i]))) < 0) {
      u = scale(u, -1)
      th = -th
    }
    // a sticker on the axis (a turning face's centre) stays put but turns with the layer
    const moving = stickers
      .map((_, i) => i)
      .filter((i) => perm[i] !== i || ((whole || dot(centreOf[i], u) > 0) && spins(i)))
    if (th > Math.PI + 1e-9) th -= 2 * Math.PI
    if (th < -Math.PI - 1e-9) th += 2 * Math.PI
    m = { name, perm, moving, axis: u, angle: (th * 180) / Math.PI, whole }
    moves.set(name, m)
    return m
  }

  const applyMove = (f: string, name: string) => {
    const p = move(name).perm
    let out = ''
    for (let j = 0; j < count; j++) out += f[p[j]]
    return out
  }

  // PuzzleGeometry names the Megaminx faces U F L BL BR R C A I BF E D; the
  // solver calls five of them FR FL DL B DR. Name every face after the solver
  // move whose axis it sits on.
  if (id === 'megaminx') {
    for (const name of SOLVER_MOVES.megaminx) {
      const axis = move(name).axis
      const face = faces.reduce((b, f) => (dot(f.normal, axis) > dot(b.normal, axis) ? f : b))
      face.name = name
    }
  }

  // The rotation group as sticker permutations, by closure over the generators.
  const identity = Uint16Array.from({ length: count }, (_, i) => i)
  const ROTATIONS: Uint16Array[] = [identity]
  const seen = new Set([identity.join(',')])
  for (let i = 0; i < ROTATIONS.length; i++) {
    for (const r of ROTATION_MOVES[id]) {
      const gen = move(r).perm
      const q = new Uint16Array(count)
      for (let j = 0; j < count; j++) q[j] = ROTATIONS[i][gen[j]] // apply the member, then the generator
      const key = q.join(',')
      if (!seen.has(key)) {
        seen.add(key)
        ROTATIONS.push(q)
      }
    }
  }

  return {
    id,
    faces,
    stickers,
    perFace,
    count,
    SOLVED,
    blank: () => '?'.repeat(count),
    // a blank or partly read state ('?') is never solved
    isSolved: (f) => {
      if (f.includes('?')) return false
      for (let s = 0; s < count; s += perFace) for (let k = 1; k < perFace; k++) if (f[s + k] !== f[s]) return false
      return true
    },
    move,
    applyMove,
    applyMoves: (f, names) => names.reduce(applyMove, f),
    SOLVER_MOVES: SOLVER_MOVES[id],
    ROTATIONS,
    kpuzzle,
  }
}

const cache = new Map<PolyId, Promise<PolyModel>>()

/** The model for a poly puzzle, built on first use and cached. */
export function loadPolyModel(id: PolyId): Promise<PolyModel> {
  let p = cache.get(id)
  if (!p) {
    p = buildPolyModel(id)
    // A failed load (the chunk did not arrive) must not stick: the next ask tries again.
    p.catch(() => cache.delete(id))
    cache.set(id, p)
  }
  return p
}
