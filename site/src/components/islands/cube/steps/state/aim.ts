// The aimed tilt of a tie, held steady. chooseTilt picks the best tilt on the face in hand, so tipping far enough to make the
// neighbour the face in hand re-aimed the hint back the other way (journey 833375a5: "tip right", "tip left", about 25 switches in
// 90 s). The aim is chosen once for a tie and kept while the tie's candidate set is the same.
import type { Face } from '../../core/geometry'
import type { Resolution, Tilt } from './scan'

/** The tilt to ask for: the best one on the face held when it has one, else the best overall; null when none cuts. */
export function chooseTilt(tilts: readonly Tilt[], prefer?: Face): Tilt | null {
  return tilts.find((t) => t.face === prefer) ?? tilts[0] ?? null
}

/** The aimed tilt and the tie it was chosen for. */
export interface Aim { tie: string; tilt: Tilt }

/** A short stable key of the strings that make up a candidate set (FNV-1a, 32 bits): a tie is the same while its key is. */
export function tieKey(parts: readonly string[]): string {
  let h = 0x811c9dc5
  for (const p of [...parts].sort().join('|')) h = Math.imul(h ^ p.charCodeAt(0), 0x01000193) >>> 0
  return h.toString(16)
}

/** The tie of an ambiguous resolution: its candidate key, or (for one built without) its closest guess and tilt names. */
export const tieOf = (res: Extract<Resolution, { reason: 'ambiguous' }>): string =>
  res.tie ?? `${res.best}|${(res.tilts ?? []).map((t) => t.face + t.side).join()}`

/**
 * The aim for a tie: `prev` kept while it is for the same tie and its tilt still cuts it, else a fresh pick (the best on `prefer`,
 * the face in hand, else the best overall). Null when no tilt cuts.
 */
export function lockAim(prev: Aim | null, tilts: readonly Tilt[], tie: string, prefer?: Face): Aim | null {
  if (prev && prev.tie === tie) {
    const same = tilts.find((t) => t.face === prev.tilt.face && t.side === prev.tilt.side)
    if (same) return same === prev.tilt ? prev : { tie, tilt: same }
  }
  const tilt = chooseTilt(tilts, prefer)
  return tilt ? { tie, tilt } : null
}
