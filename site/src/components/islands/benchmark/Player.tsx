import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { cubeGeometry } from '../cube/core/geometry'
import { CubeView } from '../cube/svg/CubeView'
import { ALL, SOURCE, playable, puzzleSize, resultSign, type ResultSign } from '../../../lib/benchmark'
import type { BenchmarkAttempt } from '../../../lib/types'
import { loadAttempts } from './attempts'
import { corruptionSentence, whyUnsolvable } from './unsolvable'
import { replayFrame, type ReplayFrame } from './replay'
import { CheckCircleIcon, CrossCircleIcon, FlaskIcon, RefreshIcon } from './icons'

/** An attempt as /ai-ontology-benchmark/attempts.json carries it: `inputId` and `depth` are dropped, its experiment's `release` and `experimentId` added. */
export type ReplayAttempt = Omit<BenchmarkAttempt, 'inputId' | 'depth'> & { release?: string; experimentId?: string; branch?: string; prompt?: string; decision?: boolean }

/** The raw results this attempt came from: `results/<experimentId>/raw/<model>.jsonl` on the study repo's branch `branch` (`main` when missing; each experiment keeps one file per model, named after it); the repo itself without an experiment id. */
export function sourceUrl(a: Pick<ReplayAttempt, 'experimentId' | 'model' | 'branch'>): string {
  const branch = (a.branch || 'main').split('/').map(encodeURIComponent).join('/')
  return a.experimentId ? `${SOURCE}/blob/${branch}/results/${encodeURIComponent(a.experimentId)}/raw/${encodeURIComponent(a.model)}.jsonl` : SOURCE
}

const RESULT: Record<ResultSign, string> = {
  solved: 'Solved',
  hallucinated: 'Hallucinated',
  unsolved: 'Not solved',
  mismatch: 'Mismatch detected',
}

/** "3x3 cube, solvable" or "3x3 cube, not solvable" (the corruption is in the "not solvable" popover). */
export function stateText(a: Pick<ReplayAttempt, 'puzzle' | 'validity'>): string {
  const kind = `${a.puzzle} cube`
  if (a.validity === 'valid') return `${kind}, solvable`
  return `${kind}, not solvable`
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

type Pop = 'why' | 'prompt'

const reducedMotion = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

interface Props {
  puzzle: string
  models: readonly string[]
  attemptsUrl: string
  /** Each puzzle's move group, as the export took it from the engine's legal_moves(). */
  legalMoves: Readonly<Record<string, readonly string[]>>
}

/** Shows one random attempt of the selected puzzle (any puzzle under "all") and models: its state and model at once, its result only once Run has replayed it (0.5 s a move). The refresh button next to the state picks another attempt. The parent keys it by the filter, so a change resets it. */
export function Player({ puzzle, models, attemptsUrl, legalMoves }: Props) {
  const titleId = useId()
  const alive = useRef(true)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)
  const [pool, setPool] = useState<readonly ReplayAttempt[]>([])
  const [prompts, setPrompts] = useState<Readonly<Record<string, string>>>({})
  const [attempt, setAttempt] = useState<ReplayAttempt | null>(null)
  const [run, setRun] = useState(0) // a new number restarts the replay of the same attempt; 0 = not run yet
  const [frame, setFrame] = useState<ReplayFrame | null>(null)
  // The popover open under the facts (one at a time), and the root that scopes the outside-click and Escape handling.
  const [open, setOpen] = useState<Pop | null>(null)
  const root = useRef<HTMLElement>(null)
  const popId = useId()
  useEffect(() => {
    alive.current = true
    return () => void (alive.current = false)
  }, [])

  // Under "all" the drawing follows the attempt's own puzzle; before one is picked it shows a solved 3x3.
  const shownPuzzle = attempt?.puzzle ?? (puzzle === ALL ? '3x3' : puzzle)
  const g = useMemo(() => cubeGeometry(puzzleSize(shownPuzzle)), [shownPuzzle])
  const plan = useMemo(() => (attempt ? playable(attempt, legalMoves[attempt.puzzle] ?? []) : null), [attempt, legalMoves])
  const moves = plan?.moves ?? []
  const promptText = attempt?.prompt ? prompts[attempt.prompt] : undefined

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

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setOpen(null)
      root.current?.querySelector<HTMLElement>(`[data-pop="${open}"]`)?.focus()
    }
    // A click outside closes the popover on the way past: nothing stops it or prevents its default, so the control under the pointer (Run, the reload icon) still does its job.
    const onClick = (e: Event) => {
      if (!(e.target as Element | null)?.closest?.('.pop-wrap')) setOpen(null)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('click', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('click', onClick)
    }
  }, [open])

  /** Loads the attempts of this puzzle and these models and shows a random one; `loud` reports a failure (a click), a quiet first load does not. */
  const load = async (loud: boolean): Promise<ReplayAttempt | null> => {
    // Only a click's load disables Run; the quiet first load leaves it clickable (a click then waits on the same fetch).
    if (loud) (setFailed(false), setLoading(true))
    try {
      const { attempts: all, prompts: texts } = await loadAttempts(attemptsUrl)
      if (!alive.current) return null
      const wanted = new Set(models)
      const found = (puzzle === ALL ? Object.values(all).flat() : (all[puzzle] ?? [])).filter((a) => wanted.has(a.model))
      if (found.length === 0) throw new Error('no attempts')
      const a = pickCase(found, null)!
      setPool(found)
      setPrompts(texts ?? {})
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
    setOpen(null)
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
    <section className="player" aria-labelledby={titleId} ref={root}>
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
                  <dt>State:</dt>{' '}
                  <dd>
                    {attempt.validity === 'valid' ? stateText(attempt) : (
                      <>
                        {attempt.puzzle} cube,{' '}
                        <span className="pop-wrap">
                          <button type="button" className="pop-btn" data-pop="why" aria-expanded={open === 'why'} aria-controls={`${popId}-why`} onClick={() => setOpen(open === 'why' ? null : 'why')}>not solvable</button>
                        </span>
                      </>
                    )}
                  </dd>{' '}
                  {pool.length > 1 && (
                    <button type="button" className="another square" onClick={another} disabled={playing} aria-label="Show another case" title="Show another case"><RefreshIcon /></button>
                  )}
                  {/* Always in the DOM (hidden while closed), so the button's aria-controls points at an element that exists. */}
                  {attempt.validity === 'invalid' && (
                    <div className="pop pop-wrap" id={`${popId}-why`} role="dialog" aria-label="Why this state is not solvable" hidden={open !== 'why'}>
                      <p>
                        {attempt.corruption && <><strong>{corruptionSentence(attempt.corruption)}</strong>{' '}</>}
                        {whyUnsolvable(attempt.corruption)}
                      </p>
                    </div>
                  )}
                </div>
                <div>
                  <dt>Model:</dt>{' '}
                  <dd>
                    {attempt.model}
                    {promptText && (
                      <>
                        . <span className="pop-wrap"><button type="button" className="pop-btn" data-pop="prompt" aria-expanded={open === 'prompt'} aria-controls={`${popId}-prompt`} onClick={() => setOpen(open === 'prompt' ? null : 'prompt')}>Prompt</button></span>
                      </>
                    )}
                  </dd>
                  {promptText && (
                    <div className="pop pop-wrap" id={`${popId}-prompt`} role="dialog" aria-label="Prompt the model received" hidden={open !== 'prompt'}>
                      <pre className="prompt-text" tabIndex={0}>{promptText}</pre>
                      {attempt.decision && <p className="pop-note">A decision model also received the moves so far and the list of options with each call.</p>}
                    </div>
                  )}
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
          <CubeView geometry={g} facelets={shown} turn={turning} label={`${shownPuzzle} cube replay`} focusable={false} />
        </div>
      </div>
    </section>
  )
}
