// Cube sticker model, any size n. Every sticker has a cubie position p
// and an outward normal n; a face turn rotates both, which gives each move's
// permutation without hand-written tables. Axes: x right, y up, z toward the
// viewer (front).
export type Face = 'U' | 'R' | 'F' | 'D' | 'L' | 'B'
export type ColorName = 'white' | 'red' | 'green' | 'yellow' | 'orange' | 'blue'
/** 54 chars over URFDLB ('?' = unknown), Kociemba order. */
export type Facelets = string
export type Vec = readonly [number, number, number]

export const FACES: readonly Face[] = ['U', 'R', 'F', 'D', 'L', 'B']
// Standard Western scheme. Faces are identified by their center color.
export const COLOR_OF: Record<Face, ColorName> = {
  U: 'white', R: 'red', F: 'green', D: 'yellow', L: 'orange', B: 'blue',
}
export const COLORS: readonly ColorName[] = FACES.map((f) => COLOR_OF[f])
export const FACE_OF = Object.fromEntries(FACES.map((f) => [COLOR_OF[f], f])) as Record<ColorName, Face>

// The trailing + 0 turns -0 into 0, so toEqual and printed positions never show a negative zero.
const add = (a: Vec, b: Vec): Vec => [a[0] + b[0] + 0, a[1] + b[1] + 0, a[2] + b[2] + 0]
const mul = (a: Vec, k: number): Vec => [a[0] * k, a[1] * k, a[2] * k]
export const dot = (a: Vec, b: Vec) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
export const cross = (a: Vec, b: Vec): Vec => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
]

export const NORMAL: Record<Face, Vec> = {
  U: [0, 1, 0], R: [1, 0, 0], F: [0, 0, 1], D: [0, -1, 0], L: [-1, 0, 0], B: [0, 0, -1],
}
// Screen-right and screen-down of each face in the standard net.
export const RIGHT: Record<Face, Vec> = {
  U: [1, 0, 0], R: [0, 0, -1], F: [1, 0, 0], D: [1, 0, 0], L: [0, 0, 1], B: [-1, 0, 0],
}
export const DOWN: Record<Face, Vec> = {
  U: [0, 0, 1], R: [0, -1, 0], F: [0, -1, 0], D: [0, 0, -1], L: [0, -1, 0], B: [0, -1, 0],
}

export interface Sticker { face: Face; p: Vec; n: Vec }

// Kociemba's piece order. Each name lists a piece's faces clockwise from outside, starting at U or D (corners) or
// at the first-named face (edges), so a name also fixes the order of a piece's sticker triple.
export const CORNER_NAMES: readonly string[] = ['URF', 'UFL', 'ULB', 'UBR', 'DFR', 'DLF', 'DBL', 'DRB']
export const EDGE_NAMES: readonly string[] = ['UR', 'UF', 'UL', 'UB', 'DR', 'DF', 'DL', 'DB', 'FR', 'FL', 'BL', 'BR']

// Clockwise quarter turn as seen from outside face axis a: v → a(a·v) − a×v.
const turn = (a: Vec, v: Vec): Vec => add(mul(a, dot(a, v)), mul(cross(a, v), -1))

// Array#join prints -0 as "0", so keys are stable.
const key = (p: Vec, n: Vec) => `${p.join(',')}|${n.join(',')}`

// SiGN: an optional layer prefix, the face, an optional w (wide), then the turn count.
const MOVE_RE = /^(\d*)([URFDLB])(w?)(2'?|')?$/

/** layers is [from, to], 1-based and inclusive; the size check lives in applyMove so parsing needs no cube. */
export function parseMove(m: string): { face: Face; turns: 1 | 2 | 3; layers: [number, number] } {
  const r = MOVE_RE.exec(m)
  if (!r) throw new Error(`Not a face turn: ${m}`)
  const prefix = r[1] === '' ? null : Number(r[1])
  if (prefix === 0) throw new Error(`Not a face turn: ${m}`)
  const layers: [number, number] = r[3] ? [1, prefix ?? 2] : [prefix ?? 1, prefix ?? 1]
  return { face: r[2] as Face, turns: !r[4] ? 1 : r[4] === "'" ? 3 : 2, layers }
}

export interface CubeGeometry {
  n: number
  count: number
  perFace: number
  /** Index of a face's centre sticker, -1 for even n. */
  centre: number
  SOLVED: Facelets
  blank(): Facelets
  /** p is in integer units of 1.5/n, so the cube spans ±(n−1) on each axis through sticker centres. */
  STICKERS: readonly Sticker[]
  /** Sticker indices grouped by position: corners (3), then edges (2), then centres (1). */
  cubies: readonly number[][]
  /** The 8 corners in CORNER_NAMES order, each triple starting at its U or D sticker, clockwise from outside. */
  corners: readonly number[][]
  /** The 3×3's edges, or the 5×5's midges, in EDGE_NAMES order; empty for other sizes. */
  edges: readonly number[][]
  /** Every 2-sticker cubie that is not in `edges`, as sticker pairs: 24 for n >= 4, none below. */
  wings: readonly number[][]
  /** Which of the 24 wing pieces (numbered by its solved slot in `wings`) sits in `slot` showing letter a on the slot's first sticker and b on its second; null when no reachable cube shows that. Always null below 4. */
  wingPiece(slot: number, a: Face, b: Face): number | null
  /** The outer layer's clockwise quarter turn, equal to quarter(face, 1). */
  QUARTER: Record<Face, number[]>
  /** The clockwise quarter turn of layer k alone, as a destination-index permutation. */
  quarter(face: Face, layer: number): number[]
  /** Whether sticker i is in layers from..to under face (1 is the outer layer). */
  inLayers(i: number, face: Face, from: number, to: number): boolean
  /** Cut depths of a move in cube units: the inner (deeper) cut at `to` first, then the outer one at from - 1 when from > 1. */
  cutPlanes(move: string): number[]
  applyMove(f: Facelets, m: string): Facelets
  applyMoves(f: Facelets, ms: readonly string[]): Facelets
  faceSlice(f: Facelets, face: Face): string[]
  isSolved(f: Facelets): boolean
  inLayer(i: number, face: Face): boolean
  /** How far inside the cube a turn's cut sits, in cube units (the cube is 3 wide). */
  cutDepth: number
  stickerCorners(i: number): Vec[]
  rotateCube(f: Facelets, rot: number): Facelets
  ROTATIONS: number
}

export function cubeGeometry(n: number): CubeGeometry {
  const perFace = n * n
  const count = 6 * perFace
  const STICKERS: Sticker[] = FACES.flatMap((face) =>
    Array.from({ length: perFace }, (_, i) => ({
      face,
      n: NORMAL[face],
      p: add(
        add(mul(NORMAL[face], n - 1), mul(RIGHT[face], 2 * (i % n) - n + 1)),
        mul(DOWN[face], 2 * Math.floor(i / n) - n + 1),
      ),
    })),
  )
  const INDEX = new Map(STICKERS.map((s, i) => [key(s.p, s.n), i]))

  const permutation = (move: (v: Vec) => Vec) =>
    STICKERS.map((s) => INDEX.get(key(move(s.p), move(s.n)))!)

  // Layer k holds the stickers with p · N = n - 1 - 2(k - 1); cached lazily since big cubes have many layers.
  const quarterCache = new Map<string, number[]>()
  const quarter = (face: Face, layer: number): number[] => {
    const id = `${face}${layer}`
    let to = quarterCache.get(id)
    if (!to) {
      const a = NORMAL[face]
      const depth = n - 1 - 2 * (layer - 1)
      to = STICKERS.map((s, i) => (dot(s.p, a) === depth ? INDEX.get(key(turn(a, s.p), turn(a, s.n)))! : i))
      quarterCache.set(id, to)
    }
    return to
  }
  const QUARTER = Object.fromEntries(FACES.map((face) => [face, quarter(face, 1)])) as Record<Face, number[]>

  const groups = new Map<string, number[]>()
  STICKERS.forEach((s, i) => {
    const k = s.p.join(',')
    groups.set(k, [...(groups.get(k) ?? []), i])
  })
  // Array#sort is stable, so each size keeps the order of its first sticker (FACES order).
  const cubies = [...groups.values()].sort((a, b) => b.length - a.length)

  // A piece's name lists its faces in the order the tables expect, so the triple follows the name.
  const isMidge = (c: number[]) => c.length === 2 && STICKERS[c[0]].p.some((x) => x === 0)
  const piecesOf = (size: number, names: readonly string[], only: (c: number[]) => boolean = () => true) =>
    names.map((name) => {
      const group = cubies.find(
        (c) => c.length === size && only(c) && [...name].every((f) => c.some((i) => STICKERS[i].face === f)),
      )!
      return [...name].map((f) => group.find((i) => STICKERS[i].face === f)!)
    })
  const corners = piecesOf(3, CORNER_NAMES)
  const edges = n === 3 || n === 5 ? piecesOf(2, EDGE_NAMES, isMidge) : []
  const wings = n >= 4 ? cubies.filter((c) => c.length === 2 && !isMidge(c)).map((c) => [c[0], c[1]]) : []

  // Wing identity, by tracking: each wing piece is a pair of stickers carrying its two home letters. Closing its position under
  // every quarter turn of every layer gives the (slot, orientation) states it can reach; each such state shows an ordered letter
  // pair in a slot, and a build-time conflict (two pieces at one key) would mean the letters do not name the piece.
  const slotOf = new Map<number, number>()
  wings.forEach((w, s) => w.forEach((i) => slotOf.set(i, s)))
  const wingTable = new Map<string, number>()
  if (wings.length) {
    const turns: number[][] = []
    for (const face of FACES) for (let layer = 1; layer < n; layer++) turns.push(quarter(face, layer))
    wings.forEach((home, piece) => {
      const letters = [STICKERS[home[0]].face, STICKERS[home[1]].face]
      const visited = new Set<string>()
      const work: [number, number][] = [[home[0], home[1]]]
      while (work.length) {
        const [x, y] = work.pop()!
        const id = `${x},${y}`
        if (visited.has(id)) continue
        visited.add(id)
        const slot = slotOf.get(x)!
        const first = wings[slot][0] === x
        const k = `${slot}|${first ? letters[0] + letters[1] : letters[1] + letters[0]}`
        const had = wingTable.get(k)
        if (had !== undefined && had !== piece) throw new Error(`Wings ${had} and ${piece} both show ${k}`)
        wingTable.set(k, piece)
        for (const t of turns) work.push([t[x], t[y]])
      }
    })
  }

  // Layers are disjoint, so one combined permutation per move.
  const rangePermutation = (face: Face, from: number, to: number): number[] => {
    if (from > to || to > n - 1) throw new Error(`Not a move on a ${n}×${n}: layers ${from}..${to}`)
    const perm = STICKERS.map((_, i) => i)
    for (let k = from; k <= to; k++) quarter(face, k).forEach((dest, i) => {
      if (dest !== i) perm[i] = dest
    })
    return perm
  }
  const applyMove = (f: Facelets, m: string): Facelets => {
    const { face, turns, layers } = parseMove(m)
    const perm = rangePermutation(face, layers[0], layers[1])
    let cur = f.split('')
    for (let t = 0; t < turns; t++) {
      const next = cur.slice()
      perm.forEach((to, from) => {
        next[to] = cur[from]
      })
      cur = next
    }
    return cur.join('')
  }
  const layerOf = (i: number, face: Face) => (n - 1 - dot(STICKERS[i].p, NORMAL[face])) / 2 + 1
  const faceSlice = (f: Facelets, face: Face): string[] => {
    const start = FACES.indexOf(face) * perFace
    return f.slice(start, start + perFace).split('')
  }

  // The 24 whole-cube rotations: a BFS over turns about the three axes, so 0 is the identity and the order is fixed.
  const generators = (['U', 'R', 'F'] as Face[]).map((f) => permutation((v) => turn(NORMAL[f], v)))
  const identity = STICKERS.map((_, i) => i)
  const rotations: number[][] = [identity]
  const seen = new Set([identity.join(',')])
  for (let k = 0; k < rotations.length; k++) {
    for (const g of generators) {
      const next = rotations[k].map((i) => g[i])
      if (!seen.has(next.join(','))) {
        seen.add(next.join(','))
        rotations.push(next)
      }
    }
  }

  const u = 1.5 / n
  const centre = n % 2 ? (perFace - 1) / 2 : -1
  return {
    n, count, perFace, centre,
    SOLVED: FACES.map((f) => f.repeat(perFace)).join(''),
    // An odd cube's face centre never moves, so it names the face before anything is read; an even cube has none.
    blank: () => FACES.map((f) => Array.from({ length: perFace }, (_, i) => (i === centre ? f : '?')).join('')).join(''),
    STICKERS, cubies, corners, edges, wings, QUARTER,
    wingPiece: (slot, a, b) => wingTable.get(`${slot}|${a}${b}`) ?? null,
    quarter,
    applyMove,
    applyMoves: (f, ms) => ms.reduce((acc, m) => applyMove(acc, m), f),
    faceSlice,
    isSolved: (f) => FACES.every((face) => new Set(faceSlice(f, face)).size === 1),
    inLayer: (i, face) => dot(STICKERS[i].p, NORMAL[face]) === n - 1,
    inLayers: (i, face, from, to) => {
      const l = layerOf(i, face)
      return l >= from && l <= to
    },
    cutPlanes: (move) => {
      const [from, to] = parseMove(move).layers
      const plane = (k: number) => (n - 2 * k) * u
      return from > 1 ? [plane(to), plane(from - 1)] : [plane(to)]
    },
    cutDepth: (n - 2) * u,
    stickerCorners: (i) => {
      const s = STICKERS[i]
      const c = mul(add(s.p, s.n), u)
      const r = RIGHT[s.face], d = DOWN[s.face], h = 0.45 * 3 / n
      const corner = (a: number, b: number): Vec => add(c, add(mul(r, a * h), mul(d, b * h)))
      return [corner(-1, -1), corner(1, -1), corner(1, 1), corner(-1, 1)]
    },
    rotateCube: (f, rot) => {
      const out = f.split('')
      rotations[rot].forEach((to, from) => {
        out[to] = f[from]
      })
      return out.join('')
    },
    ROTATIONS: rotations.length,
  }
}

export const G3 = cubeGeometry(3)

// Every size, the 3x3 included, reads sticker positions from its geometry's STICKERS (integer units).
export const SOLVED: Facelets = G3.SOLVED
export const applyMove = G3.applyMove
export const applyMoves = G3.applyMoves
export const faceSlice = G3.faceSlice
export const isSolved = G3.isSolved

export function invertMove(m: string): string {
  const { turns } = parseMove(m)
  // The prefix and the w stay; only the turn suffix changes.
  const head = m.replace(/(2'?|')$/, '')
  return turns === 2 ? `${head}2` : turns === 1 ? `${head}'` : head
}

export function rotateGrid<T>(cells: readonly T[], k: number): T[] {
  const n = Math.round(Math.sqrt(cells.length))
  let out = cells.slice()
  for (let t = 0; t < ((k % 4) + 4) % 4; t++) {
    const prev = out
    out = prev.map((_, i) => prev[(n - 1 - (i % n)) * n + Math.floor(i / n)])
  }
  return out
}
