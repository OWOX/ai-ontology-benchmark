// Facelets → corner/edge permutation and orientation (Kociemba's facelet
// tables), and the five legality checks from the spec, in order.
import { COLOR_OF, CORNER_NAMES, EDGE_NAMES, FACES, G3, type CubeGeometry, type ColorName, type Face, type Facelets } from './geometry'

export const CORNER_FACELETS = [
  [8, 9, 20], [6, 18, 38], [0, 36, 47], [2, 45, 11], [29, 26, 15], [27, 44, 24], [33, 53, 42], [35, 17, 51],
]
export const EDGE_FACELETS = [
  [5, 10], [7, 19], [3, 37], [1, 46], [32, 16], [28, 25], [30, 43], [34, 52], [23, 12], [21, 41], [50, 39], [48, 14],
]

export interface Cubie { cp: number[]; co: number[]; ep: number[]; eo: number[] }

export type LegalityError =
  | { kind: 'count'; color: ColorName; count: number }
  | { kind: 'fake'; colors: ColorName[]; face: Face }
  | { kind: 'duplicate'; colors: ColorName[]; face: Face }
  | { kind: 'pieces'; colors: ColorName[]; count: number; expected: number }
  | { kind: 'twist' }
  | { kind: 'flip' }
  | { kind: 'parity' }

export const ERROR_RANK: Record<LegalityError['kind'], number> = {
  count: 0, fake: 1, duplicate: 2, pieces: 3, twist: 4, flip: 5, parity: 6,
}

export type Legality = { ok: true; cubie: Cubie } | { ok: false; error: LegalityError }

const colorsOf = (letters: string) => [...letters].map((c) => COLOR_OF[c as Face])
const fail = (error: LegalityError): Legality => ({ ok: false, error })

const parity = (p: number[]) => {
  let inv = 0
  for (let i = 0; i < p.length; i++) for (let j = i + 1; j < p.length; j++) if (p[i] > p[j]) inv++
  return inv % 2
}

/** The real corner a sticker triple (U or D sticker anywhere, clockwise) shows, and where its U or D sticker sits; null when no such piece exists, which includes a mirrored one. */
export function cornerPiece(s: readonly string[]): { piece: number; ori: number } | null {
  const ori = s.findIndex((c) => c === 'U' || c === 'D')
  if (ori < 0) return null
  const piece = CORNER_NAMES.findIndex((n) => n[0] === s[ori] && n[1] === s[(ori + 1) % 3] && n[2] === s[(ori + 2) % 3])
  return piece < 0 ? null : { piece, ori }
}

const HOME = FACES.join('')
/** True when, rotated to home centres, the corner and midge permutations differ in parity; null when no rotation puts the centres home. */
function homeParity(f: Facelets, g: CubeGeometry): boolean | null {
  for (let r = 0; r < g.ROTATIONS; r++) {
    const h = g.rotateCube(f, r)
    if (FACES.map((face) => h[FACES.indexOf(face) * g.perFace + g.centre]).join('') !== HOME) continue
    const cp: number[] = [], ep: number[] = []
    for (const c of g.corners) {
      const found = cornerPiece(c.map((x) => h[x]))
      if (!found) return null
      cp.push(found.piece)
    }
    for (const e of g.edges) {
      const [a, b] = e.map((x) => h[x])
      const i = EDGE_NAMES.findIndex((n) => n === a + b || n === b + a)
      if (i < 0) return null
      ep.push(i)
    }
    return parity(cp) !== parity(ep)
  }
  return null
}

// A 2x2 has no edges, so its legality is counts, corner identity and twist; edge flip and parity need edges.
export function checkLegal(f: Facelets, g: CubeGeometry = G3): Legality {
  for (const face of FACES) {
    const count = [...f].filter((c) => c === face).length
    if (count !== g.perFace) return fail({ kind: 'count', color: COLOR_OF[face], count })
  }

  const cp: number[] = [], co: number[] = [], ep: number[] = [], eo: number[] = []
  for (let i = 0; i < 8; i++) {
    const s = g.corners[i].map((x) => f[x])
    const found = cornerPiece(s)
    if (!found) return fail({ kind: 'fake', colors: colorsOf(s.join('')), face: CORNER_NAMES[i][1] as Face })
    cp.push(found.piece)
    co.push(found.ori)
  }
  for (let i = 0; i < g.edges.length; i++) {
    const [a, b] = g.edges[i].map((x) => f[x])
    const straight = EDGE_NAMES.indexOf(a + b)
    const flipped = EDGE_NAMES.indexOf(b + a)
    if (straight < 0 && flipped < 0) return fail({ kind: 'fake', colors: colorsOf(a + b), face: EDGE_NAMES[i][1] as Face })
    ep.push(straight >= 0 ? straight : flipped)
    eo.push(straight >= 0 ? 0 : 1)
  }

  const dup = (perm: number[], names: readonly string[], slots: readonly string[]): LegalityError | null => {
    const seen = new Set<number>()
    for (let i = 0; i < perm.length; i++) {
      if (seen.has(perm[i])) return { kind: 'duplicate', colors: colorsOf(names[perm[i]]), face: slots[i][1] as Face }
      seen.add(perm[i])
    }
    return null
  }
  const dupError = dup(cp, CORNER_NAMES, CORNER_NAMES) ?? dup(ep, EDGE_NAMES, EDGE_NAMES)
  if (dupError) return fail(dupError)

  if (g.wings.length) {
    // A wing's slot and the ordered letters it shows name the wing piece (geometry's wingPiece), so one reversed wing is
    // impossible while the reversed pair is the flipped edge. A pair no piece shows is fake; a piece named twice is a duplicate.
    const tally = new Map<string, number>()
    const holder = new Map<number, number>()
    for (let slot = 0; slot < g.wings.length; slot++) {
      const w = g.wings[slot]
      const [a, b] = w.map((x) => f[x])
      const name = EDGE_NAMES.find((e) => e === a + b || e === b + a)
      if (!name) return fail({ kind: 'fake', colors: colorsOf(a + b), face: g.STICKERS[w[1]].face })
      tally.set(name, (tally.get(name) ?? 0) + 1)
    }
    for (const name of EDGE_NAMES) {
      const count = tally.get(name) ?? 0
      if (count !== 2) return fail({ kind: 'pieces', colors: colorsOf(name), count, expected: 2 })
    }
    for (let slot = 0; slot < g.wings.length; slot++) {
      const w = g.wings[slot]
      const [a, b] = w.map((x) => f[x] as Face)
      const piece = g.wingPiece(slot, a, b)
      if (piece === null) return fail({ kind: 'fake', colors: colorsOf(a + b), face: g.STICKERS[w[1]].face })
      const first = holder.get(piece)
      if (first !== undefined) return fail({ kind: 'duplicate', colors: colorsOf(a + b), face: g.STICKERS[w[1]].face })
      holder.set(piece, slot)
    }
  }

  if (co.reduce((a, b) => a + b, 0) % 3 !== 0) return fail({ kind: 'twist' })
  if (g.edges.length === 0) return { ok: true, cubie: { cp, co, ep, eo } }
  if (eo.reduce((a, b) => a + b, 0) % 2 !== 0) return fail({ kind: 'flip' })
  // The 5x5's middle-slice turn (3R) cycles four midges and no corner, so the parities match only with the centres home
  // (a whole-cube turn is an odd midge permutation and an even corner one). Every cube the island produces has its centres
  // home; for a 5x5 whose centres match no rotation, the law is skipped because no home frame exists to measure against.
  if (g.n === 3) {
    if (parity(cp) !== parity(ep)) return fail({ kind: 'parity' })
  } else if (g.n === 5) {
    const home = homeParity(f, g)
    if (home !== null && home) return fail({ kind: 'parity' })
  }
  return { ok: true, cubie: { cp, co, ep, eo } }
}

const pieceWord = (colors: ColorName[]) => (colors.length === 3 ? 'corner' : 'edge')

export function describeError(e: LegalityError, g: CubeGeometry = G3): string {
  switch (e.kind) {
    case 'count':
      return `Found ${e.count} ${e.color} stickers, a cube has ${g.perFace}. Rescan the faces with ${e.color} on them.`
    case 'fake': {
      const a = /^[aeiou]/.test(e.colors[0]) ? 'An' : 'A'
      return `${a} ${e.colors.join('-')} ${pieceWord(e.colors)} can't exist. Rescan the ${COLOR_OF[e.face]} face.`
    }
    case 'duplicate':
      return `Two ${e.colors.join('-')} ${pieceWord(e.colors)}s. Rescan the ${COLOR_OF[e.face]} face.`
    case 'pieces':
      return `Found ${e.count} ${e.colors.join('-')} edge pieces, a ${g.n}×${g.n} has ${e.expected}. Rescan the faces with ${e.colors[0]} or ${e.colors[1]} on them.`
    case 'twist':
      return 'One corner is twisted in place. A sticker was misread, or the cube was put back together wrong.'
    case 'flip':
      return 'One edge is flipped in place. A sticker was misread, or the cube was put back together wrong.'
    case 'parity':
      return 'Two pieces are swapped. A sticker was misread, or the cube was put back together wrong.'
  }
}
