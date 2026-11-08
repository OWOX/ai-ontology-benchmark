// Spec: docs/specs/site.md
import { loadSiteData } from '../lib/site-data'
import type { ReplayAttempt } from '../components/islands/benchmark/Player'

// Replay data for the island's Run button: the attempts of every shown experiment,
// keyed by puzzle, without the fields the replay never reads (inputId, depth), each with its experiment's release and id (for the links to its prompt and its raw results).
// Order is the stored order inside an experiment, experiments by experimentId.
export async function GET() {
  const { experiments } = loadSiteData()
  const byPuzzle: Record<string, ReplayAttempt[]> = {}
  for (const e of experiments) {
    for (const { inputId: _inputId, depth: _depth, ...attempt } of e.attempts ?? []) {
      ;(byPuzzle[attempt.puzzle] ??= []).push({ ...attempt, release: e.release ?? '', experimentId: e.experimentId })
    }
  }
  return new Response(JSON.stringify(byPuzzle), { headers: { 'Content-Type': 'application/json' } })
}
