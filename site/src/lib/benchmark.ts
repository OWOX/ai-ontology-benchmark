// Replay helpers and the metric row type for /ai-ontology-benchmark. Pure. The metrics themselves are computed in
// Python (src/site/metrics.py) and arrive in site.json.
import type { BenchmarkAttempt } from './types'

/** One metric cell of site.json's `metrics`: the value (null for n/a) and the number of attempts behind it. */
export type Rate = { value: number | null; n: number }
export type ModelMetrics = {
  puzzle: string
  model: string
  provider: string
  /** Every scored attempt of the group, infrastructure failures included, and its input, output, retry input, and retry output tokens. */
  attempts: number
  tokens: number
  precision: Rate
  hallucination: Rate
  critical: Rate
}
/** One metric row of site.json's `setupMetrics`: a model's three metrics under one setup, on one puzzle or pooled (`all`). */
export type SetupMetrics = {
  puzzle: string
  model: string
  setup: string
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

/** The setups in the order the study defines them (docs/definitions.md, Setups; the ids are the raw records' `setup`). */
export const SETUPS = [
  { id: 'no_model', label: 'No model' },
  { id: 'descriptive', label: 'Descriptive model' },
  { id: 'prescriptive', label: 'Prescriptive model' },
] as const

/** One bar of the setup chart: the setup's mean over the ticked models that have a value, and how many they are. */
export type SetupBar = { setup: string; label: string; rate: Rate; models: number }

/** The unweighted mean of each setup's value for the given puzzle over the given models, in setup order. A model with no row for the setup, or an n/a value (hallucination of a decision model), is skipped, so each model that has a value counts once whatever its attempt count; the Rate's `n` is the number of models behind the mean, and its value null when none has one. */
export function setupBars(rows: readonly SetupMetrics[], puzzle: string, models: readonly string[], pick: (r: SetupMetrics) => Rate): SetupBar[] {
  const chosen = new Set(models)
  const here = rows.filter((r) => r.puzzle === puzzle && chosen.has(r.model))
  const known = new Set<string>(SETUPS.map((s) => s.id))
  const extra = [...new Set(here.map((r) => r.setup))].filter((id) => !known.has(id)).sort()
  const all = [...SETUPS.map((s) => ({ id: s.id as string, label: s.label as string })), ...extra.map((id) => ({ id, label: id }))]
  return all.map(({ id, label }) => {
    const values = here.filter((r) => r.setup === id).map((r) => pick(r).value).filter((v): v is number => v !== null)
    const value = values.length === 0 ? null : values.reduce((a, b) => a + b, 0) / values.length
    return { setup: id, label, rate: { value, n: values.length }, models: values.length }
  })
}

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
