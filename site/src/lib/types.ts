// One attempt of a model on a puzzle input, as stored on a benchmark experiment
// (src/site/export.py writes this shape).
export interface BenchmarkAttempt {
  model: string
  puzzle: string
  inputId: string
  validity: 'valid' | 'invalid'
  setup: string
  attempt: number
  depth: number
  state: string
  /** Why an invalid input can't be solved, e.g. `twisted corner UFL clockwise`; null for a valid input. Absent on experiments imported before it was recorded. */
  corruption?: string | null
  moves: string[]
  outcome: string
  mismatch: boolean
}

export interface BenchmarkModel {
  name: string
  provider: string
  kind: string
}

export interface BenchmarkExperiment {
  experimentId: string
  release?: string | null
  puzzles?: string[] | null
  models?: BenchmarkModel[] | null
  setups?: string[] | null
  attemptsPerInput?: number | null
  attemptCount?: number | null
  firstAt?: string | null
  lastAt?: string | null
  attempts?: BenchmarkAttempt[] | null
}
