// Spec: docs/specs/site.md
import { loadSiteData } from '../lib/site-data'
import type { ReplayAttempt } from '../components/islands/benchmark/Player'

// Replay data for the island's Run button, loaded lazily so the page itself stays small:
// `attempts` are the attempts of every shown experiment, keyed by puzzle, without the fields the replay never reads (inputId, depth),
// each with its experiment's release, id, and branch (for the link to its raw results) and `prompt`, the key of its prompt in `prompts`
// (release/setup/input id). `prompts` holds each exact prompt once; an attempt whose prompt the export could not build has no `prompt`.
// Order is the stored order inside an experiment, experiments by experimentId.
export async function GET() {
  const { experiments, prompts = {} } = loadSiteData()
  const attempts: Record<string, ReplayAttempt[]> = {}
  const used: Record<string, string> = {}
  for (const e of experiments) {
    for (const { inputId, depth: _depth, ...attempt } of e.attempts ?? []) {
      const key = `${e.release ?? ''}/${attempt.setup}/${inputId}`
      const out: ReplayAttempt = { ...attempt, release: e.release ?? '', experimentId: e.experimentId, branch: e.branch ?? 'main' }
      if (key in prompts) {
        out.prompt = key
        used[key] = prompts[key]
      }
      ;(attempts[attempt.puzzle] ??= []).push(out)
    }
  }
  return new Response(JSON.stringify({ attempts, prompts: used }), { headers: { 'Content-Type': 'application/json' } })
}
