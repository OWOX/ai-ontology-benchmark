// Replay helpers and the metric row type for /ai-ontology-benchmark. Pure. The metrics themselves are computed in
// Python (src/site/metrics.py) and arrive in site.json.
import type { BenchmarkAttempt } from './types'

/** One metric cell of site.json's `metrics`: the value (null for n/a) and the number of attempts behind it. */
export type Rate = { value: number | null; n: number }
export type ModelMetrics = {
  puzzle: string
  model: string
  provider: string
  precision: Rate
  hallucination: Rate
  critical: Rate
}
export type ResultSign = 'solved' | 'mismatch' | 'hallucinated' | 'unsolved'

export const PROVIDERS = [
  { id: 'anthropic', label: 'Anthropic' },
  { id: 'openai', label: 'OpenAI' },
  { id: 'google', label: 'Google' },
] as const

/** The study's repo: the Experiment block's Source link. */
export const SOURCE = 'https://github.com/OWOX/ai-ontology-benchmark'

/** The puzzle value of the `metrics` rows pooled over every puzzle, and of the filter's "All" option. */
export const ALL = 'all'

/** '3x3' -> 3 */
export const puzzleSize = (puzzle: string): number => Number.parseInt(puzzle, 10)

export function resultSign(a: Pick<BenchmarkAttempt, 'outcome' | 'validity' | 'mismatch'>): ResultSign {
  if (a.outcome === 'success' && a.validity === 'valid') return 'solved'
  if (a.mismatch) return 'mismatch'
  if (a.outcome === 'hallucination') return 'hallucinated'
  return 'unsolved'
}

/** Moves up to the first illegal one; `stoppedAt` is that move's index, or null when all are legal. `legalMoves` is the puzzle's move group, from the engine's legal_moves() via the export. */
export function playable(a: Pick<BenchmarkAttempt, 'moves'>, legalMoves: readonly string[]): { moves: string[]; stoppedAt: number | null } {
  const legal = new Set(legalMoves)
  const stop = a.moves.findIndex((m) => !legal.has(m))
  return stop === -1 ? { moves: a.moves, stoppedAt: null } : { moves: a.moves.slice(0, stop), stoppedAt: stop }
}
