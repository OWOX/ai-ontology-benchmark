import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { cubeGeometry } from '../cube/core/geometry'
import { CubeView } from '../cube/svg/CubeView'
import { SOURCE, playable, puzzleSize, resultSign, type ResultSign } from '../../../lib/benchmark'
import type { BenchmarkAttempt } from '../../../lib/types'
import { loadAttempts } from './attempts'
import { replayFrame, type ReplayFrame } from './replay'
import { CheckCircleIcon, CrossCircleIcon, FlaskIcon, RefreshIcon } from './icons'

/** An attempt as /ai-ontology-benchmark/attempts.json carries it: `inputId` and `depth` are dropped, its experiment's `release` and `experimentId` added. */
export type ReplayAttempt = Omit<BenchmarkAttempt, 'inputId' | 'depth'> & { release?: string; experimentId?: string }

/** The raw results this attempt came from: `results/<experimentId>/raw/<model>.jsonl` on the study repo's `results/<experimentId>` branch (each experiment keeps one file per model, named after it); the repo itself without an experiment id. */
export function sourceUrl(a: Pick<ReplayAttempt, 'experimentId' | 'model'>): string {
  return a.experimentId ? `${SOURCE}/blob/results/${encodeURIComponent(a.experimentId)}/results/${encodeURIComponent(a.experimentId)}/raw/${encodeURIComponent(a.model)}.jsonl` : SOURCE
}

/** The prompt template the model was sent, in the study repo: `releases/<release>/prompts/<setup>/<puzzle>.txt`; null without a release. */
export function promptUrl(a: Pick<ReplayAttempt, 'release' | 'setup' | 'puzzle'>): string | null {
  return a.release ? `${SOURCE}/blob/main/releases/${a.release}/prompts/${a.setup}/${a.puzzle}.txt` : null
}

const RESULT: Record<ResultSign, string> = {
  solved: 'Solved',
  hallucinated: 'Hallucinated',
  unsolved: 'Not solved',
  mismatch: 'Mismatch detected',
}

/** "3x3 cube, solvable" or "3x3 cube, not solvable: twisted corner UFL clockwise" (the reason only when the import recorded it). */
export function stateText(a: Pick<ReplayAttempt, 'puzzle' | 'validity' | 'corruption'>): string {
  const kind = `${a.puzzle} cube`
  if (a.validity === 'valid') return `${kind}, solvable`
  return a.corruption ? `${kind}, not solvable: ${a.corruption}` : `${kind}, not solvable`
}

/** The result's words, named by what was missed: an unsolvable input left unflagged reads "Mismatch not detected"; a solvable one flagged as a mismatch reads "Not solved", since there was nothing to detect. */
export function resultText(sign: ResultSign, a: Pick<ReplayAttempt, 'validity'>): string {
  if (sign === 'unsolved' && a.validity === 'invalid') return 'Mismatch not detected'
  if (sign === 'mismatch' && a.validity === 'valid') return RESULT.unsolved
  return RESULT[sign]
}

/** A case to show: a model picked at random first (each ticked model as likely as any other, however many attempts it has), then one of its attempts; never `current` when there is another. */
export function pickCase(pool: readonly ReplayAttempt[], current: ReplayAttempt | null, random: () => number = Math.random): ReplayAttempt | null {
  const rest = pool.filter((a) => a !== current)
  if (rest.length === 0) return null
  const names = [...new Set(rest.map((a) => a.model))]
  const name = names[Math.floor(random() * names.length)]
  const ofModel = rest.filter((a) => a.model === name)
  return ofModel[Math.floor(random() * ofModel.length)]
}

const reducedMotion = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

interface Props {
  puzzle: string
  models: readonly string[]
  attemptsUrl: string
  /** Each puzzle's move group, as the export took it from the engine's legal_moves(). */
  legalMoves: Readonly<Record<string, readonly string[]>>
}

/** Shows one random attempt of the selected puzzle and models: its state and model at once, its result only once Run has replayed it (0.5 s a move). The refresh button next to the state picks another attempt. The parent keys it by the filter, so a change resets it. */
export function Player({ puzzle, models, attemptsUrl, legalMoves }: Props) {
  const g = useMemo(() => cubeGeometry(puzzleSize(puzzle)), [puzzle])
  const titleId = useId()
  const alive = useRef(true)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)
  const [pool, setPool] = useState<readonly ReplayAttempt[]>([])
  const [attempt, setAttempt] = useState<ReplayAttempt | null>(null)
  const [run, setRun] = useState(0) // a new number restarts the replay of the same attempt; 0 = not run yet
  const [frame, setFrame] = useState<ReplayFrame | null>(null)
  useEffect(() => {
    alive.current = true
    return () => void (alive.current = false)
  }, [])

  const plan = useMemo(() => (attempt ? playable(attempt, legalMoves[attempt.puzzle] ?? []) : null), [attempt, legalMoves])
  const moves = plan?.moves ?? []

  useEffect(() => {
    if (!attempt || run === 0) return
    const reduced = reducedMotion()
    let t0: number | null = null
    let id = 0
    const tick = (now: number) => {
      if (t0 === null) t0 = now
      const f = replayFrame(now - t0, moves.length, reduced)
      setFrame(f)
      if (!f.done) id = requestAnimationFrame(tick)
    }
    setFrame({ index: 0, progress: reduced ? null : 0, done: false })
    id = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(id)
  }, [run])

  /** Loads the attempts of this puzzle and these models and shows a random one; `loud` reports a failure (a click), a quiet first load does not. */
  const load = async (loud: boolean): Promise<ReplayAttempt | null> => {
    // Only a click's load disables Run; the quiet first load leaves it clickable (a click then waits on the same fetch).
    if (loud) (setFailed(false), setLoading(true))
    try {
      const all = await loadAttempts(attemptsUrl)
      if (!alive.current) return null
      const wanted = new Set(models)
      const found = (all[puzzle] ?? []).filter((a) => wanted.has(a.model))
      if (found.length === 0) throw new Error('no attempts')
      const a = pickCase(found, null)!
      setPool(found)
      setAttempt(a)
      return a
    } catch {
      if (alive.current && loud) setFailed(true)
      return null
    } finally {
      if (alive.current && loud) setLoading(false)
    }
  }

  // The case shows before Run, so load it as soon as there are models to pick from. Once only: the parent re-keys the Player when the puzzle or models change.
  useEffect(() => {
    if (models.length > 0) void load(false)
  }, [])

  const start = async () => {
    if (attempt || (await load(true))) setRun((r) => r + 1)
  }

  /** Another case from the same pool (model first, never the one shown), back to its unplayed state. */
  const another = () => {
    const next = pickCase(pool, attempt)
    if (!next) return
    setAttempt(next)
    setRun(0)
    setFrame(null)
  }

  const playing = loading || (frame !== null && !frame.done && run > 0)
  const done = run > 0 && frame?.done === true
  const index = frame?.index ?? 0
  const shown = useMemo(() => (attempt ? g.applyMoves(attempt.state, moves.slice(0, done ? moves.length : index)) : g.SOLVED), [g, attempt, plan, index, done])
  const turning = run > 0 && !done && frame?.progress != null && index < moves.length ? { move: moves[index], progress: frame.progress } : null
  const result = attempt && done ? resultSign(attempt) : null
  // The share of the playable moves turned so far, counting the turning move's progress.
  const donePct = moves.length === 0 ? 0 : Math.min(100, Math.round(((index + (frame?.progress ?? 0)) / moves.length) * 100))
  // A hallucination ends on its first illegal move: the cube shakes for a second there (not under reduced motion).
  const shake = done && plan?.stoppedAt != null && !reducedMotion()
  // Green with a tick when the outcome is success (Solved, or Mismatch on an unsolvable input), red with a cross otherwise.
  const verdict = attempt?.outcome === 'success' ? 'correct' : 'wrong'

  return (
    <section className="player" aria-labelledby={titleId}>
      {/* The case being replayed, as one more step in the filter's look (`.steps > .current > .title (.num + .label)`, then `.body`). */}
      <div className="steps experiment">
        <div className="current">
          <div className="title">
            <span className="num" aria-hidden="true"><FlaskIcon /></span>
            <span className="label" id={titleId}>Experiment Example</span>
          </div>
          <div className="body">
            {attempt && (
              <dl className="facts">
                <div>
                  <dt>State:</dt> <dd>{stateText(attempt)}</dd>{' '}
                  {pool.length > 1 && (
                    <button type="button" className="another square" onClick={another} disabled={playing} aria-label="Show another case" title="Show another case"><RefreshIcon /></button>
                  )}
                </div>
                <div>
                  <dt>Model:</dt>{' '}
                  <dd>{attempt.model}{promptUrl(attempt) && <>. <a className="prompt" href={promptUrl(attempt)!} target="_blank" rel="noopener noreferrer">Prompt<span className="sr-only"> (opens in a new tab)</span></a></>}</dd>
                </div>
                {/* Always laid out (two lines on a narrow screen, where ". Source" wraps), so Run never moves the button down; visibility: hidden (which also keeps it from screen readers) until Run. */}
                <div className="one-line" data-verdict={result ? verdict : undefined} style={run > 0 ? undefined : { visibility: 'hidden' }}>
                  <dt>Result:</dt>{' '}
                  <dd className="result">
                    {result ? <span className="value">{verdict === 'correct' ? <CheckCircleIcon /> : <CrossCircleIcon />}{resultText(result, attempt!)}</span> : run > 0 ? <span className="muted">running… {donePct}%</span> : '\u00a0'}
                    {result && <span className="after-result">. <a className="source" href={sourceUrl(attempt!)} target="_blank" rel="noopener noreferrer">Source<span className="sr-only"> (opens in a new tab)</span></a></span>}
                  </dd>
                </div>
              </dl>
            )}
            {/* Announces the result once, when the run ends; the row's running percentage is not read out. */}
            <p className="sr-only" aria-live="polite">{attempt && result ? `Result: ${resultText(result, attempt)}` : ''}</p>
            <div className="actions">
              <button type="button" className="primary play" onClick={start} disabled={playing || models.length === 0}>{run > 0 ? 'Re-run' : 'Run'}</button>
            </div>
            {failed && <p role="alert">Could not load an attempt to run.</p>}
          </div>
        </div>
      </div>
      {/* The same markup as /cube's solution player (SolveStage): .cube-stage > .views > the drawing; the rules are in src/styles/cube-stage.css. */}
      <div className={`cube-stage${shake ? ' shake' : ''}`}>
        <div className="views">
          <CubeView geometry={g} facelets={shown} turn={turning} label={`${puzzle} cube replay`} focusable={false} />
        </div>
      </div>
    </section>
  )
}
