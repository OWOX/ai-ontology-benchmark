// Captured faces and the rotation search; a tie it cannot break from the stickers comes back with the tilts that would (tiltsOf). A capture is one face's nine colours at the orientation it was read in, plus the neighbour bands that counted; resolve() finds the face rotations that make a legal cube the bands agree with. Spec: the three cube specs.
import { COLOR_OF, COLORS, FACES, FACE_OF, rotateGrid, type ColorName, type Face, type Facelets } from '../../core/geometry'
import { checkLegal, ERROR_RANK, type LegalityError } from '../../core/cubie'
import { bandsAgree, neighbourRow, type Bands } from './orient'
import { nearest, ratio } from '../../core/palette'
import { isSticker, plausibleSticker, rgbToLab, type Refs, type RGB } from '../../vision/colors'
import { MAX_SPREAD, type Patch, type Side } from '../../vision/sample'
import { tieKey } from './aim'

/** Largest Lab distance from a cell to its nearest palette color that still captures. */
export const MAX_DIST = 35
const CENTER = 4

/**
 * How far above the learned white's chroma per lightness (`ratio` in palette.ts) a white cell may be. Chroma alone cannot tell them
 * apart: a white sticker held close under a warm lamp reads chroma 14 to 19 at L 78 to 84 (ratio 0.17 to 0.24), and skin reads chroma
 * 23 to 38 at L 51 to 76 (ratio 0.31 to 0.62). The general white rule (0.5 of L) lets that skin through.
 */
export const WHITE_GATE_RATIO = 0.28

/**
 * The grid-fit gate once a palette exists: a cell must be near a palette colour and also pass that colour's own sticker rule.
 * Distance alone lets skin through when the learned white sits close to the stock one, and the white rule alone is too loose for skin,
 * so white is also held to the learned white's chroma per lightness.
 */
export const paletteCell = (refs: Refs) => (rgb: RGB): boolean => {
  const { color, dist } = nearest(refs, rgb)
  if (dist > MAX_DIST || !plausibleSticker(color, rgb)) return false
  if (color !== 'white') return true
  return ratio(rgbToLab(rgb)) <= ratio(refs.white) + WHITE_GATE_RATIO
}

/** `votes`: this face's band votes, `votes[side * 3 + k][colour index in COLORS]`; they rank a tie, never gate it. */
export interface Captured { colors: (ColorName | null)[]; bands: Bands; votes?: number[][] }

/** `far`: some cell is none of the six. `farCenter`: the centre itself is, so the face is a guess and never captures. */
export function readFace(refs: Refs, cells: RGB[]): { face: Face; colors: (ColorName | null)[]; far: boolean; farCenter: boolean } {
  const reads = cells.map((c) => nearest(refs, c))
  const face = FACE_OF[reads[CENTER].color]
  const colors = reads.map((r, i) => (i === CENTER ? COLOR_OF[face] : r.dist > MAX_DIST ? null : r.color))
  // A far centre is shown as its nearest colour but is flagged far, and the recognisers skip it.
  const farCenter = reads[CENTER].dist > MAX_DIST
  return { face, colors, far: farCenter || colors.some((c) => c === null), farCenter }
}

/** The bands that count: three patches, each a sticker, even, and within MAX_DIST of a palette colour. */
export function readBands(refs: Refs, bands: (Patch | null)[][]): Bands {
  const out: Bands = {}
  bands.forEach((band, s) => {
    const names: ColorName[] = []
    for (const p of band) {
      if (!p || p.spread > MAX_SPREAD || !isSticker(p.color)) return
      const n = nearest(refs, p.color)
      if (n.dist > MAX_DIST) return
      names.push(n.color)
    }
    out[s as Side] = names
  })
  return out
}

/** A seen face held square-on and the neighbour it is tilted toward, so that the band of that neighbour bordering it tells the tied cubes apart. */
export interface Tilt {
  face: Face
  /** The neighbour in the drawn cube's frame: where the arrow points. */
  side: Face
  /** The colour of the face to tilt, for the hint (an odd cube's centre; an even cube's majority colour that no other face shares, since its slot letters are only a frame). Null when every colour it could be named by is shared. */
  label: Face | null
  /** The colours on the face, most stickers first (the standard face order breaks a tie): what a face with no colour of its own is called by. */
  colours: Face[]
  /** Whether no other drawn face has exactly that set of colours. */
  setUnique: boolean
  /** Whether every tied cube has `side` at that edge, so its colour can be named. Else only the arrow says which edge. */
  sure: boolean
  /** The band, as face letters in clockwise order, each tied cube shows beyond that edge (at every equivalent turn of the face); the asked-edge gate reads a band against these (askBand.ts). Only the centres reader fills it. */
  reads?: readonly string[]
}

export type Resolution =
  | { ok: true; facelets: Facelets }
  /** The same stickers make a legal cube held more than one way; `face` is the first that differs. */
  /** `states` are the tied states themselves, set only by the poly recogniser when it keeps them (poly/reader.ts TIE_KEEP): a visitor can tap the one that matches. */
  /** `tilts` are the aimed bands, every one that cuts, best first (assemble.ts for the faces search, `tiltsOf` below for the centres reader). */
  | { ok: false; reason: 'ambiguous'; face: Face; best: Facelets; tilts?: readonly Tilt[]; tie?: string; states?: readonly string[] }
  | { ok: false; reason: 'illegal'; error: LegalityError; best: Facelets }

const assemble = (captured: Record<Face, Captured>, rots: number[]): Facelets =>
  FACES.map((face, k) => rotateGrid(captured[face].colors, rots[k]).map((c) => FACE_OF[c!]).join('')).join('')

/** A legal cube with the face rotations that hold it and agree with the counted bands. */
type Candidate = [Facelets, number[][]]

/**
 * The tilts that cut a tie among centres-pinned cubes, best first. A tilt is a face held square-on and the neighbour it is tilted
 * toward; the first candidate is the cube the screen draws, so a net side S of its face F is the physical image side (S - r) % 4
 * of the capture, and each candidate shows the row of net side (that + its own r) % 4 there. A (F, S) whose candidates read two or
 * more different rows cuts; it ranks by the largest class of candidates sharing one reading, smallest first, then by face order.
 * A side already counted splits nothing among the survivors, so it drops out by itself. A face that looks the same turned is scored at each of its equivalent turns (the pose may hold it at any), and a tilt stays only if it cuts at all of them, naming its side only if every candidate at every turn has the one neighbour there. The face is named by its centre colour; the
 * side is named only when every candidate has one neighbour at that edge.
 */
function tiltsOf(cands: readonly Candidate[], captured: Record<Face, Captured>): Tilt[] {
  const pairs = cands.flatMap(([f, sets]) => sets.map((rs) => [f, rs] as const))
  const bestRs = pairs[0][1]
  const found: { tilt: Tilt; worst: number; order: number }[] = []
  FACES.forEach((F, k) => {
    // A face that looks the same turned has several turns the camera may hold it at, and the arrow follows whichever the pose picked,
    // so the tilt must cut, and name its side, at each of them.
    const turns = [0, 1, 2, 3].filter((e) => rotateGrid(captured[F].colors, e).every((c, i) => c === captured[F].colors[i]))
    for (let S = 0; S < 4; S++) {
      let worst = 0, cuts = true
      const named = new Set<number>()
      const shown = new Set<string>()
      for (const e of turns) {
        const image = (S - bestRs[k] + e + 8) % 4
        const reads = new Map<string, number>()
        for (const [f, rs] of pairs) {
          const row = neighbourRow(F, ((image + rs[k]) % 4) as Side)
          const read = row.map((j) => f[j]).join('')
          reads.set(read, (reads.get(read) ?? 0) + 1)
          shown.add(read)
          named.add(Math.floor(row[0] / 9))
        }
        if (reads.size < 2) { cuts = false; break }
        worst = Math.max(worst, ...reads.values())
      }
      if (!cuts) continue
      const side = FACES[Math.floor(neighbourRow(F, S as Side)[0] / 9)]
      found.push({ tilt: { face: F, side, label: F, colours: [F], setUnique: true, sure: named.size === 1, reads: [...shown] }, worst, order: k * 4 + S })
    }
  })
  return found.sort((a, b) => a.worst - b.worst || a.order - b.order).map((x) => x.tilt)
}

/** How many band votes show the colours this cube has beside each face's four sides, at the best of the turns that give the cube. */
function support(cand: Candidate, captured: Record<Face, Captured>): number {
  const [f, sets] = cand
  return Math.max(...sets.map((rs) => FACES.reduce((sum, F, k) => {
    const votes = captured[F].votes
    if (!votes) return sum
    for (let side = 0; side < 4; side++) {
      const row = neighbourRow(F, ((side + rs[k]) % 4) as Side)
      for (let c = 0; c < 3; c++) sum += votes[side * 3 + c]?.[COLORS.indexOf(COLOR_OF[f[row[c]] as Face])] ?? 0
    }
    return sum
  }, 0)))
}

/** Several legal cubes remain: name the first face whose 9 facelets differ between them, and the tilts that would tell them apart. */
function ambiguous(cands: Candidate[], captured: Record<Face, Captured>): Resolution {
  const cubes = cands.map(([f]) => f)
  const k = FACES.findIndex((_, i) => cubes.some((c) => c.slice(i * 9, i * 9 + 9) !== cubes[0].slice(i * 9, i * 9 + 9)))
  const tie = tieKey(cands.map(([f, sets]) => f + sets.map((r) => r.join('')).join(',')))
  return { ok: false, reason: 'ambiguous', face: FACES[k], best: cands.map((c) => [c, support(c, captured)] as const).reduce((a, b) => (b[1] > a[1] ? b : a))[0][0], tilts: tiltsOf(cands, captured), tie }
}

export function resolve(captured: Record<Face, Captured>): Resolution {
  // A face with a symmetric pattern gives the same cube at several rotations, so keep them all per cube.
  const legal = new Map<Facelets, number[][]>()
  // The illegal guess that got furthest toward legal, by ERROR_RANK.
  let closest: { error: LegalityError; facelets: Facelets } | null = null
  for (let r = 0; r < 4096; r++) {
    const rots = FACES.map((_, k) => (r >> (2 * k)) & 3)
    const f = assemble(captured, rots)
    const res = checkLegal(f)
    if (res.ok) legal.set(f, [...(legal.get(f) ?? []), rots])
    else if (!closest || ERROR_RANK[res.error.kind] > ERROR_RANK[closest.error.kind]) closest = { error: res.error, facelets: f }
    // Color counts don't depend on rotation: skip the other 4095.
    if (!res.ok && res.error.kind === 'count') break
  }
  if (legal.size === 0) return { ok: false, reason: 'illegal', error: closest!.error, best: closest!.facelets }
  // The bands say how each face was turned; keep only the candidates they agree with.
  const agreeing = (use: (face: Face) => boolean): Candidate[] =>
    [...legal].flatMap(([f, rotSets]) => {
      const rs = rotSets.filter((r) => FACES.every((face, k) => !use(face) || bandsAgree(f, face, r[k], captured[face].bands)))
      return rs.length ? [[f, rs] as Candidate] : []
    })
  let agreed = agreeing(() => true)
  if (agreed.length === 0) {
    // A band was misread. Drop the faces whose bands fit no candidate at all, and try the rest.
    const bad = new Set(FACES.filter((face) => !agreeing((x) => x === face).length))
    agreed = agreeing((face) => !bad.has(face))
    // Still nothing: drop every band and let the stickers decide.
    if (agreed.length === 0) agreed = [...legal]
  }
  return agreed.length === 1 ? { ok: true, facelets: agreed[0][0] } : ambiguous(agreed, captured)
}
