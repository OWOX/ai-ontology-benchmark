// State recognition. Each face keeps a tally of votes per cell, in the orientation the face was first seen in; later
// readings are turned to match it (by cells, then by neighbour bands when the cells tie). A sticker's vote goes to
// the nearest palette colour among the colours it can still be, and it is confirmed by vote margin. Because every
// face's tally has an unknown turn against the net, allowed sets come from trying all 4^6 turns of the six faces:
// a turn fits when each confirmed corner and edge is a subset of a real piece, and each piece lets its unconfirmed
// cells be what the real pieces matching it could add. Counts that hold for any turn prune further: nine stickers
// per colour, four per colour on corner cells, four on edge cells. A contradiction unconfirms the least certain
// vote-confirmed sticker that caused it. When all 54 are confirmed the rotation search with bands (scan.ts
// resolve) picks the cube. Spec: docs/superpowers/specs/2026-10-11-cube-recognition-design.md
import { COLORS, COLOR_OF, FACES, FACE_OF, SOLVED, rotateGrid, type ColorName, type Face, type Facelets } from '../../core/geometry'
import { CORNER_FACELETS, EDGE_FACELETS } from '../../core/cubie'
import { labDistance } from '../../core/palette'
import { isSticker, rgbToLab, type Refs, type RGB } from '../../vision/colors'
import { MAX_SPREAD, type Patch, type Side } from '../../vision/sample'
import { MAX_DIST, resolve, type Captured, type Resolution } from './scan'
import type { Bands } from './orient'

/** Votes a sticker's leading colour needs. */
export const VOTES_MIN = 5
/** And how many times the runner-up it must have. */
export const VOTES_RATIO = 2
const CENTER = 4
export const ALL = (1 << COLORS.length) - 1
const bit = (c: ColorName) => 1 << COLORS.indexOf(c)

/** rotateGrid on indices: ROT[r][i] is the tally cell whose colour lands at net cell i after r clockwise turns. */
const ROT = [0, 1, 2, 3].map((r) => rotateGrid([0, 1, 2, 3, 4, 5, 6, 7, 8], r))
/** TALLY[face][r][cell]: tally index of net cell `cell` of face `face` when that face's tally is turned r. */
const TALLY = FACES.map((_, k) => ROT.map((rot) => rot.map((i) => k * 9 + i)))

interface Piece { faces: number[]; cells: number[]; corner: boolean }
/** The 8 corner and 12 edge positions, as (face, net cell) pairs. */
const PIECES: Piece[] = [
  ...CORNER_FACELETS.map((c) => ({ c, corner: true })),
  ...EDGE_FACELETS.map((c) => ({ c, corner: false })),
].map(({ c, corner }) => ({ faces: c.map((j) => Math.floor(j / 9)), cells: c.map((j) => j % 9), corner }))

/** The real pieces of a solved cube as colour masks, and for every colour mask: whether some real piece holds all of it, and the colours those pieces could add. */
const realMasks = (list: number[][]) => list.map((cells) => cells.reduce((m, j) => m | bit(COLOR_OF[SOLVED[j] as Face]), 0))
const table = (real: number[]) => {
  const ok: boolean[] = [], rest: number[] = []
  for (let m = 0; m < 1 << COLORS.length; m++) {
    const fits = real.filter((p) => (p & m) === m)
    ok[m] = fits.length > 0
    rest[m] = fits.reduce((acc, p) => acc | (p & ~m), 0)
  }
  return { ok, rest }
}
const CORNER_T = table(realMasks(CORNER_FACELETS))
const EDGE_T = table(realMasks(EDGE_FACELETS))
const isCornerCell = (i: number) => i % 2 === 0 && i !== CENTER
const isEdgeCell = (i: number) => i % 2 === 1

export interface Tally {
  /** votes[sticker][colour index], in the face's first-seen orientation. */
  votes: number[][]
  /** bandVotes[face index * 12 + side * 3 + k][colour index]. */
  bandVotes: number[][]
  confirmed: (ColorName | null)[]
  painted: boolean[]
  /** Bitmask over COLORS of what each sticker can still be. */
  allowed: number[]
  /** The confirmed set the allowed sets were last computed for. */
  pruned: string
  /** What each sticker could be by the pieces and counts, ignoring its own confirmation: the colours worth reopening for. */
  open: number[]
  /** How a sticker was confirmed without votes: by its piece's one allowed colour, or by a colour's remaining count. */
  inferred: ('piece' | 'count' | null)[]
  /** The vote-confirmed set (see `voteKey`) the current inferences were derived from: while it holds they stand and settle skips the prune and the inference. */
  inferredFrom: string
  /** `allowed` and `open` as they were before the inferences: what the full pass would read, valid while `inferredFrom` holds. */
  baseAllowed: number[]
  baseOpen: number[]
}

const zeros = (rows: number) => Array.from({ length: rows }, () => Array(COLORS.length).fill(0) as number[])

export function initialTally(): Tally {
  const t: Tally = { votes: zeros(54), bandVotes: zeros(72), confirmed: Array(54).fill(null), painted: Array(54).fill(false), allowed: Array(54).fill(ALL), pruned: '', open: Array(54).fill(ALL), inferred: Array(54).fill(null), inferredFrom: '', baseAllowed: Array(54).fill(ALL), baseOpen: Array(54).fill(ALL) }
  FACES.forEach((f, k) => { t.confirmed[k * 9 + CENTER] = COLOR_OF[f] })
  settle(t)
  return t
}

export const nearestAllowed = (refs: Refs, rgb: RGB, mask: number): { color: ColorName; dist: number } | null => {
  const lab = rgbToLab(rgb)
  let best: { color: ColorName; dist: number } | null = null
  for (const c of COLORS) {
    if (!(mask & bit(c))) continue
    const d = labDistance(lab, refs[c])
    if (!best || d < best.dist) best = { color: c, dist: d }
  }
  return best && best.dist <= MAX_DIST ? best : null
}

/** The colour with the most votes in a row, with its count and the runner-up's; null without votes. */
export function leader(row: number[], mask = ALL): { color: ColorName; top: number; next: number } | null {
  let top = 0, next = 0, ci = -1
  row.forEach((v, i) => {
    if (!(mask & (1 << i))) return
    if (v > top) { next = top; top = v; ci = i } else if (v > next) next = v
  })
  return ci < 0 ? null : { color: COLORS[ci], top, next }
}

/**
 * The quarter turn that lines a reading up with the face's tally: most cells agreeing with the current leaders, then
 * (for faces symmetric under a turn) most band patches agreeing with the band leaders, ties to the lowest turn.
 */
function align(t: Tally, refs: Refs, k: number, reads: (ColorName | null)[], bands: (Patch | null)[][] | null): number {
  let bestK = 0, bestCells = -1, bestBands = -1
  for (let r = 0; r < 4; r++) {
    const rot = rotateGrid(reads, r)
    let cells = 0
    for (let i = 0; i < 9; i++) {
      if (i === CENTER || !rot[i]) continue
      const l = t.confirmed[k * 9 + i] ?? leader(t.votes[k * 9 + i])?.color
      if (l === rot[i]) cells++
    }
    let agree = 0
    bands?.forEach((band, s) => band.forEach((p, c) => {
      if (!p || p.spread > MAX_SPREAD || !isSticker(p.color)) return
      const n = nearestAllowed(refs, p.color, ALL)
      if (n && leader(t.bandVotes[k * 12 + ((s + r) % 4) * 3 + c])?.color === n.color) agree++
    }))
    if (cells > bestCells || (cells === bestCells && agree > bestBands)) { bestCells = cells; bestBands = agree; bestK = r }
  }
  return bestK
}

/** Adds one reading. The centre names the face; a centre far from every colour skips the reading. */
export function vote(t: Tally, refs: Refs, cells: RGB[], bands: (Patch | null)[][] | null): void {
  const centre = nearestAllowed(refs, cells[CENTER], ALL)
  if (!centre) return
  const face = FACE_OF[centre.color]
  const k = FACES.indexOf(face)
  const plain = cells.map((c) => nearestAllowed(refs, c, ALL)?.color ?? null)
  const r = align(t, refs, k, plain, bands)
  const turned = rotateGrid(cells, r)
  for (let i = 0; i < 9; i++) {
    if (i === CENTER) continue
    const j = k * 9 + i
    if (t.painted[j]) continue
    // A vote-confirmed sticker keeps collecting votes over every colour, so a wrong confirmation can be reconsidered.
    const n = nearestAllowed(refs, turned[i], t.confirmed[j] !== null && t.inferred[j] === null ? ALL : t.allowed[j])
    if (n) t.votes[j][COLORS.indexOf(n.color)]++
  }
  if (!bands) return
  bands.forEach((band, s) => {
    const side = (s + r) % 4
    band.forEach((p, c) => {
      if (!p || p.spread > MAX_SPREAD || !isSticker(p.color)) return
      const n = nearestAllowed(refs, p.color, ALL)
      if (n) t.bandVotes[k * 12 + side * 3 + c][COLORS.indexOf(n.color)]++
    })
  })
}

/** Runs `each` for every combination of the six face rotations that fits the confirmed stickers; returns whether any fit. With `each` null, stops at the first fit. */
function combos(t: Tally, each: ((rots: number[]) => void) | null): boolean {
  let any = false
  const rots = [0, 0, 0, 0, 0, 0]
  for (let r = 0; r < 4096; r++) {
    for (let k = 0; k < 6; k++) rots[k] = (r >> (2 * k)) & 3
    let ok = true
    for (const p of PIECES) {
      let have = 0
      for (let q = 0; q < p.faces.length; q++) {
        const c = t.confirmed[TALLY[p.faces[q]][rots[p.faces[q]]][p.cells[q]]]
        if (c) { if (have & bit(c)) { have = -1; break } have |= bit(c) }
      }
      if (have < 0 || !(p.corner ? CORNER_T : EDGE_T).ok[have]) { ok = false; break }
    }
    if (!ok) continue
    any = true
    if (!each) return true
    each(rots)
  }
  return any
}

const counts = (t: Tally, keep: (cell: number) => boolean): number[] => {
  const c = Array(COLORS.length).fill(0) as number[]
  t.confirmed.forEach((col, j) => { if (col && keep(j % 9)) c[COLORS.indexOf(col)]++ })
  return c
}
const fullMask = (c: number[], n: number) => c.reduce((m, v, i) => (v >= n ? m | (1 << i) : m), 0)

/** The confirmed stickers that no inference produced: the evidence the inferences stand on. */
const voteKey = (t: Tally): string => t.confirmed.map((c, j) => (t.inferred[j] === null ? c ?? '-' : '-')).join(',')

/** Whether the margin rule or reconsideration would change a confirmation, judged on the pre-inference sets (reads only). */
function wouldMove(t: Tally): boolean {
  for (let j = 0; j < 54; j++) {
    const c = t.confirmed[j]
    if (c !== null && t.inferred[j] === null) {
      if (t.painted[j] || j % 9 === CENTER) continue
      const l = leader(t.votes[j])
      if (l && l.color !== c && l.top > t.votes[j][COLORS.indexOf(c)] && t.baseOpen[j] & bit(l.color)) return true
    } else {
      // Unconfirmed, or inferred and so unconfirmed as far as the full pass is concerned.
      const l = leader(t.votes[j], t.baseAllowed[j])
      if (l && l.top >= VOTES_MIN && l.top >= VOTES_RATIO * l.next) return true
    }
  }
  return false
}

/** Confirms stickers that reached the margin, then prunes the allowed sets whenever the confirmed set changed, then infers. */
export function settle(t: Tally): void {
  // Inferences are derived, never evidence: while the vote-confirmed set is the one they came from, they stand.
  if (t.inferredFrom === voteKey(t) && !wouldMove(t)) return
  if (reopenInferred(t)) pruneUntilStable(t)
  // Reconsider: a vote-confirmed sticker whose votes now favour another colour goes back to the margin rule.
  let reopened = false
  for (let j = 0; j < 54; j++) {
    const c = t.confirmed[j]
    if (c === null || t.painted[j] || j % 9 === CENTER) continue
    const l = leader(t.votes[j])
    if (l && l.color !== c && l.top > t.votes[j][COLORS.indexOf(c)] && t.open[j] & bit(l.color)) { t.confirmed[j] = null; reopened = true }
  }
  // Its allowed set was pinned to the old colour: recompute before the margin rule reads it.
  if (reopened) pruneUntilStable(t)
  for (let j = 0; j < 54; j++) {
    if (t.confirmed[j] !== null) continue
    const l = leader(t.votes[j], t.allowed[j])
    if (l && l.top >= VOTES_MIN && l.top >= VOTES_RATIO * l.next) t.confirmed[j] = l.color
  }
  pruneUntilStable(t)
  t.baseAllowed = t.allowed.slice(); t.baseOpen = t.open.slice()
  infer(t)
  t.inferredFrom = voteKey(t)
}

/**
 * Confirms stickers the pieces leave one colour, and the last stickers a colour's count can still take. A round the
 * pieces or counts contradict undoes every round of this call and nothing is dropped: the evidence is judged without inferences.
 */
function infer(t: Tally): void {
  for (let guard = 0; guard < 108; guard++) {
    const fresh: number[] = []
    for (let j = 0; j < 54; j++) {
      if (t.confirmed[j] !== null || t.allowed[j] === 0) continue
      const one = COLORS.filter((c) => t.allowed[j] & bit(c))
      if (one.length === 1) { t.confirmed[j] = one[0]; t.inferred[j] = 'piece'; fresh.push(j) }
    }
    if (!fresh.length) {
      const have = counts(t, () => true)
      for (const c of COLORS) {
        const left = 9 - have[COLORS.indexOf(c)]
        if (left <= 0) continue
        const open = [...Array(54).keys()].filter((j) => t.confirmed[j] === null && t.allowed[j] & bit(c))
        if (open.length !== left) continue
        for (const j of open) { t.confirmed[j] = c; t.inferred[j] = 'count'; fresh.push(j) }
        break
      }
    }
    if (!fresh.length) return
    const guarded = { hit: false }
    pruneUntilStable(t, guarded)
    if (guarded.hit) {
      reopenInferred(t)
      t.allowed = t.baseAllowed.slice(); t.open = t.baseOpen.slice()
      t.pruned = t.confirmed.map((c) => c ?? '-').join(',')
      return
    }
  }
}

/** Reopens every inferred sticker. Returns whether any was. */
function reopenInferred(t: Tally): boolean {
  let any = false
  for (let j = 0; j < 54; j++) if (t.inferred[j] !== null) { t.confirmed[j] = null; t.inferred[j] = null; any = true }
  return any
}

function pruneUntilStable(t: Tally, guard?: { hit: boolean }): void {
  for (let pass = 0; pass < 54; pass++) {
    const key = t.confirmed.map((c) => c ?? '-').join(',')
    if (key === t.pruned) return
    t.pruned = key
    if (!prune(t, guard)) return
  }
}

/**
 * One pass over the 4^6 face turns. `union` collects, for every sticker, what the pieces allow in the turns where
 * every confirmed piece fits. `open` is the same for confirmed stickers ignoring their own colour, and also counts
 * the turns whose only failing piece fits without that sticker: that is how a wrong early confirmation can be
 * reopened. `fits` is whether some turn had no failing piece.
 */
function survey(t: Tally): { union: number[]; open: number[]; fits: boolean } {
  const union = Array(54).fill(0) as number[]
  const open = Array(54).fill(0) as number[]
  let fits = false
  const rots = [0, 0, 0, 0, 0, 0]
  const have = Array(PIECES.length).fill(0) as number[]
  const idxs = Array(PIECES.length) as number[][]
  for (let r = 0; r < 4096; r++) {
    for (let k = 0; k < 6; k++) rots[k] = (r >> (2 * k)) & 3
    let failing = -1, failures = 0
    for (let n = 0; n < PIECES.length && failures < 2; n++) {
      const p = PIECES[n]
      const idx = p.faces.map((f, q) => TALLY[f][rots[f]][p.cells[q]])
      idxs[n] = idx
      let h = 0
      for (const j of idx) {
        const c = t.confirmed[j]
        if (c) { if (h & bit(c)) { h = -1; break } h |= bit(c) }
      }
      have[n] = h
      if (h < 0 || !(p.corner ? CORNER_T : EDGE_T).ok[h]) { failures++; failing = n }
    }
    if (failures > 1) continue
    if (failures === 1) {
      // Only piece `failing` objects: a confirmed sticker on it may be the culprit if the piece fits without it.
      const p = PIECES[failing], idx = idxs[failing], table = p.corner ? CORNER_T : EDGE_T
      for (const j of idx) {
        const c = t.confirmed[j]
        if (!c || t.painted[j] || j % 9 === CENTER) continue
        let h = 0, dup = false
        for (const i of idx) if (i !== j && t.confirmed[i]) { if (h & bit(t.confirmed[i]!)) dup = true; h |= bit(t.confirmed[i]!) }
        if (!dup && table.ok[h]) open[j] |= table.rest[h]
      }
      continue
    }
    fits = true
    for (let n = 0; n < PIECES.length; n++) {
      const table = PIECES[n].corner ? CORNER_T : EDGE_T
      for (const j of idxs[n]) {
        const c = t.confirmed[j]
        // A confirmed cell is judged by its partners alone: what it could be if it were open.
        const m = table.rest[c ? have[n] & ~bit(c) : have[n]] | (c ? bit(c) : 0)
        union[j] |= m
        open[j] |= m
      }
    }
  }
  return { union, open, fits }
}

/** Recomputes the allowed sets. Returns true when a contradiction made it unconfirm a sticker, so settle prunes again. */
function prune(t: Tally, guard?: { hit: boolean }): boolean {
  const { union, open, fits } = survey(t)
  if (!fits) return fitContradiction(t, guard)
  // Counts hold whatever the rotations: nine of each colour, four on corner cells, four on edge cells.
  const nine = counts(t, () => true), four = counts(t, isCornerCell), edge4 = counts(t, isEdgeCell)
  if (nine.some((v) => v > 9) || four.some((v) => v > 4) || edge4.some((v) => v > 4)) {
    if (countContradiction(t, union, guard)) return true
  }
  const all = fullMask(nine, 9), corners = fullMask(four, 4), edges = fullMask(edge4, 4)
  const allowed = union.slice()
  let empty = false
  for (let j = 0; j < 54; j++) {
    if (t.confirmed[j] !== null) { allowed[j] = bit(t.confirmed[j]!); continue }
    allowed[j] &= ~all & ~(isCornerCell(j % 9) ? corners : isEdgeCell(j % 9) ? edges : 0)
    if (allowed[j] === 0 && union[j] !== 0) empty = true
  }
  t.allowed = allowed
  t.open = open.map((m, j) => (t.confirmed[j] === null ? allowed[j] : (m & ~(isCornerCell(j % 9) ? corners : isEdgeCell(j % 9) ? edges : 0) & ~all) | bit(t.confirmed[j]!)))
  return empty ? countContradiction(t, union, guard) : false
}

const marginOf = (t: Tally, j: number): number => {
  const l = leader(t.votes[j])
  return l ? l.top - l.next : 0
}

/** Unconfirms sticker j and starts its votes over. */
const drop = (t: Tally, j: number): true => { t.confirmed[j] = null; t.votes[j].fill(0); return true }

/**
 * The confirmed stickers fit no turn of the faces: drop the least certain vote-confirmed sticker whose removal
 * restores a fit. When none does, the state is left for resolve to report and a paint to fix.
 */
function fitContradiction(t: Tally, guard?: { hit: boolean }): boolean {
  if (guard) { guard.hit = true; return false }
  let best: { j: number; margin: number } | null = null
  for (let j = 0; j < 54; j++) {
    const c = t.confirmed[j]
    if (c === null || t.painted[j] || j % 9 === CENTER) continue
    t.confirmed[j] = null
    const fits = combos(t, null)
    t.confirmed[j] = c
    if (!fits) continue
    const margin = marginOf(t, j)
    if (!best || margin < best.margin) best = { j, margin }
  }
  return best ? drop(t, best.j) : false
}

/**
 * A count rule contradicts the pieces: a colour is over its limit (9 overall, 4 on corner cells, 4 on edge cells), or an
 * unconfirmed cell that the pieces allow (union) was emptied by those limits. Drops the least certain vote-confirmed
 * sticker of an offending colour in the offending class. When there is none, the state is left for resolve and paint.
 */
function countContradiction(t: Tally, union: number[], guard?: { hit: boolean }): boolean {
  if (guard) { guard.hit = true; return false }
  const classes = [
    { any: true, corner: false, limit: 9, of: counts(t, () => true) },
    { any: false, corner: true, limit: 4, of: counts(t, isCornerCell) },
    { any: false, corner: false, limit: 4, of: counts(t, isEdgeCell) },
  ]
  const inClass = (cl: (typeof classes)[number], cell: number) => cl.any || (cl.corner ? isCornerCell(cell) : isEdgeCell(cell))
  // offending[class] is a colour mask.
  let offending = classes.map((cl) => cl.of.reduce((m, v, i) => (v > cl.limit ? m | (1 << i) : m), 0))
  if (offending.every((m) => m === 0)) {
    for (let j = 0; j < 54; j++) {
      if (t.confirmed[j] !== null || union[j] === 0 || t.allowed[j] !== 0) continue
      offending = classes.map((cl, n) => (inClass(cl, j % 9) ? union[j] & fullMask(cl.of, cl.limit) : offending[n]))
      break
    }
  }
  let best: { j: number; margin: number } | null = null
  for (let j = 0; j < 54; j++) {
    const c = t.confirmed[j]
    if (c === null || t.painted[j] || j % 9 === CENTER) continue
    if (!classes.some((cl, n) => inClass(cl, j % 9) && offending[n] & bit(c))) continue
    const margin = marginOf(t, j)
    if (!best || margin < best.margin) best = { j, margin }
  }
  return best ? drop(t, best.j) : false
}

/** The visitor names a sticker: confirmed for good, votes cleared. Centres are ignored. */
export function paint(t: Tally, index: number, color: ColorName): void {
  if (index % 9 === CENTER || index < 0 || index > 53) return
  t.confirmed[index] = color
  t.inferred[index] = null
  t.painted[index] = true
  t.votes[index].fill(0)
  settle(t)
}

export const allowedColors = (t: Tally, index: number): ColorName[] => COLORS.filter((c) => t.allowed[index] & bit(c))

/** The counted band sides of a face: all three cells led by VOTES_MIN votes at the margin. */
export function bandsOf(t: Tally, face: Face): Bands {
  const k = FACES.indexOf(face)
  const out: Bands = {}
  for (let s = 0; s < 4; s++) {
    const names: ColorName[] = []
    for (let c = 0; c < 3; c++) {
      const l = leader(t.bandVotes[k * 12 + s * 3 + c])
      if (!l || l.top < VOTES_MIN || l.top < VOTES_RATIO * l.next) break
      names.push(l.color)
    }
    if (names.length === 3) out[s as Side] = names
  }
  return out
}

/** Changes exactly when a band side is added or changes: the key to re-run resolve on. */
export const bandKey = (t: Tally): string => FACES.map((f) => JSON.stringify(bandsOf(t, f))).join('|')

/** Every face as a capture at its tally orientation, once all 54 stickers are confirmed; else null. */
export function captureOf(t: Tally): Record<Face, Captured> | null {
  if (t.confirmed.some((c) => c === null)) return null
  return Object.fromEntries(FACES.map((f, k) => [f, { colors: t.confirmed.slice(k * 9, k * 9 + 9) as ColorName[], bands: bandsOf(t, f), votes: t.bandVotes.slice(k * 12, k * 12 + 12) }])) as Record<Face, Captured>
}

export interface Recognized {
  /** Confirmed stickers at tally orientation, '?' elsewhere. */
  assembled: Facelets
  /** Confirmed stickers, centres included: progress out of 54. */
  confirmed: number
  /** Unconfirmed stickers with at least one vote. */
  pending: number[]
  /** The rotation search, once every sticker is confirmed. */
  resolution: Resolution | null
}

export function recognize(t: Tally, withResolution = true): Recognized {
  const assembled = t.confirmed.map((c) => (c ? FACE_OF[c] : '?')).join('')
  const pending = t.votes.flatMap((row, j) => (t.confirmed[j] === null && row.some((v) => v > 0) ? [j] : []))
  const cap = withResolution ? captureOf(t) : null
  return { assembled, confirmed: t.confirmed.filter((c) => c !== null).length, pending, resolution: cap ? resolve(cap) : null }
}

/** A copy of the tally with every unconfirmed sticker set to its leading allowed colour when it has a vote; `unseen` is the face with the most voteless stickers (null when none). */
export function confirmTally(t: Tally): { tally: Tally; unseen: { face: Face; count: number } | null } {
  const tally: Tally = { ...t, votes: t.votes.map((r) => r.slice()), bandVotes: t.bandVotes.map((r) => r.slice()), confirmed: t.confirmed.slice(), painted: t.painted.slice(), allowed: t.allowed.slice(), open: t.open.slice(), inferred: t.inferred.slice(), baseAllowed: t.baseAllowed.slice(), baseOpen: t.baseOpen.slice() }
  const missing = FACES.map(() => 0)
  for (let j = 0; j < 54; j++) {
    if (tally.confirmed[j] !== null) continue
    const l = leader(t.votes[j], t.allowed[j]) ?? leader(t.votes[j])
    if (l && l.top >= 1) tally.confirmed[j] = l.color
    else missing[Math.floor(j / 9)]++
  }
  const worst = missing.indexOf(Math.max(...missing))
  return { tally, unseen: missing[worst] > 0 ? { face: FACES[worst], count: missing[worst] } : null }
}
