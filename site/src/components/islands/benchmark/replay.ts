import { TURN_MS, ease } from '../cube/svg/turn'

/** Each move takes this long, so the replay lasts moves x MOVE_MS. */
export const MOVE_MS = 500
/** An attempt with no playable move still holds this long before its result shows. */
export const EMPTY_BEAT_MS = 600

export interface ReplayFrame {
  /** Moves already applied; during a turn, the index of the move being turned. */
  index: number
  /** The eased share of the turning move's angle, or null between turns, at the end and under reduced motion. */
  progress: number | null
  done: boolean
}

/** Where the replay is `elapsedMs` in. Each move owns a MOVE_MS slice; its turn takes the slice's start, at most TURN_MS. */
export function replayFrame(elapsedMs: number, moves: number, reduced: boolean): ReplayFrame {
  if (moves === 0) return { index: 0, progress: null, done: elapsedMs >= EMPTY_BEAT_MS }
  const per = MOVE_MS
  if (elapsedMs >= moves * per) return { index: moves, progress: null, done: true }
  const index = Math.min(moves - 1, Math.floor(elapsedMs / per))
  if (reduced) return { index, progress: null, done: false }
  const t = elapsedMs - index * per
  return { index, progress: ease(t / Math.min(per, TURN_MS)), done: false }
}
