// Metrics and replay helpers for /ai-ontology-benchmark. Pure; definitions follow the study's
// docs/definitions.md "Metrics".
import type { BenchmarkAttempt, BenchmarkExperiment } from './types'

export type Rate = { value: number | null; n: number }
export type Rates = { success: Rate; hallucination: Rate; detection: Rate }
export type ResultSign = 'solved' | 'mismatch' | 'hallucinated' | 'unsolved'

export const PROVIDERS = [
  { id: 'anthropic', label: 'Anthropic' },
  { id: 'openai', label: 'OpenAI' },
  { id: 'google', label: 'Google' },
] as const

/** The study's repo: the Experiment block's Source link. */
export const SOURCE = 'https://github.com/OWOX/ai-ontology-benchmark'

const rate = (hits: number, n: number): Rate => ({ value: n === 0 ? null : hits / n, n })

/** Success: all attempts. Hallucination: attempts with at least one parsed move. Detection: invalid inputs. */
export function rates(attempts: readonly BenchmarkAttempt[]): Rates {
  let success = 0
  let withMoves = 0
  let hallucinated = 0
  let invalid = 0
  let detected = 0
  for (const a of attempts) {
    if (a.outcome === 'success') success++
    if (a.moves.length > 0) {
      withMoves++
      if (a.outcome === 'hallucination') hallucinated++
    }
    if (a.validity === 'invalid') {
      invalid++
      if (a.mismatch) detected++
    }
  }
  return {
    success: rate(success, attempts.length),
    hallucination: rate(hallucinated, withMoves),
    detection: rate(detected, invalid),
  }
}

export type ModelMetrics = Rates & { puzzle: string; model: string; provider: string }

const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0)

/** One row per (puzzle, model), pooling the attempts of every given experiment. */
export function metricsByModel(experiments: readonly BenchmarkExperiment[]): ModelMetrics[] {
  const groups = new Map<string, { puzzle: string; model: string; attempts: BenchmarkAttempt[] }>()
  const provider = new Map<string, string>()
  for (const e of experiments) {
    for (const m of e.models ?? []) if (!provider.has(m.name) || provider.get(m.name) === 'unknown') provider.set(m.name, m.provider)
    for (const a of e.attempts ?? []) {
      const key = `${a.puzzle}\u0000${a.model}`
      let g = groups.get(key)
      if (!g) groups.set(key, (g = { puzzle: a.puzzle, model: a.model, attempts: [] }))
      g.attempts.push(a)
    }
  }
  return [...groups.values()]
    .sort((a, b) => cmp(a.puzzle, b.puzzle) || cmp(a.model, b.model))
    .map((g) => ({ puzzle: g.puzzle, model: g.model, provider: provider.get(g.model) ?? 'unknown', ...rates(g.attempts) }))
}

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
