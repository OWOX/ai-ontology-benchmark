import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cubeGeometry } from '../cube/core/geometry'
import { resetAttempts } from './attempts'
import { Player, pickCase, promptUrl, resultText, sourceUrl, stateText, type ReplayAttempt } from './Player'

const g = cubeGeometry(3)
const attempt = (o: Partial<ReplayAttempt>): ReplayAttempt => ({
  model: 'm1', puzzle: '3x3', validity: 'valid', setup: 'descriptive', attempt: 1,
  state: g.applyMoves(g.SOLVED, ['R', 'U']), moves: ["U'", "R'"], outcome: 'success', mismatch: false, ...o,
})

const LEGAL = { '3x3': ['U', 'R', 'F', 'D', 'L', 'B'].flatMap((f) => [f, `${f}'`, `${f}2`]) }
const stub = (data: Record<string, ReplayAttempt[]>) => vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => data })))
const SOURCE = 'https://github.com/OWOX/ai-ontology-benchmark'
/** Renders the player and lets its first load (on mount) settle. */
const mount = async () => {
  const r = render(<Player puzzle="3x3" models={['m1']} attemptsUrl="/a.json" legalMoves={LEGAL} />)
  await act(async () => {})
  return r
}
const run = async (name: 'Run' | 'Re-run' = 'Run') => {
  fireEvent.click(screen.getByRole('button', { name }))
  await act(async () => {})
}
const finish = () => act(async () => void vi.advanceTimersByTime(5200))
const result = () => document.querySelector('.facts .result')!
const row = () => result().parentElement!
const fact = (term: string) => screen.getByText(term).nextElementSibling!.textContent

beforeEach(() => (vi.useFakeTimers(), resetAttempts()))
afterEach(() => (vi.useRealTimers(), vi.unstubAllGlobals()))

describe('Player', () => {
  it('calls an unflagged unsolvable input "Mismatch not detected" and a flagged solvable one "Not solved"', () => {
    expect(resultText('unsolved', { validity: 'invalid' })).toBe('Mismatch not detected')
    expect(resultText('unsolved', { validity: 'valid' })).toBe('Not solved')
    expect(resultText('mismatch', { validity: 'invalid' })).toBe('Mismatch detected')
    expect(resultText('mismatch', { validity: 'valid' })).toBe('Not solved')
  })

  it('links the prompt template of the case in the study repo, only when the release is known', () => {
    expect(promptUrl({ release: '1.3.1', setup: 'descriptive', puzzle: '2x2' })).toBe(`${SOURCE}/blob/main/releases/1.3.1/prompts/descriptive/2x2.txt`)
    expect(promptUrl({ release: '', setup: 'descriptive', puzzle: '2x2' })).toBeNull()
  })

  it('shows the model with a link to its prompt, opening in a new window', async () => {
    stub({ '3x3': [attempt({ release: '1.3.1' })] })
    await mount()
    expect(fact('Model:')).toBe('m1. Prompt (opens in a new tab)')
    expect(screen.getByRole('link', { name: /^Prompt ?\(opens in a new tab\)$/ })).toHaveAttribute('href', `${SOURCE}/blob/main/releases/1.3.1/prompts/descriptive/3x3.txt`)
    expect(screen.getByRole('link', { name: /^Prompt ?\(opens in a new tab\)$/ })).toHaveAttribute('target', '_blank')
  })

  it('picks the model first, so a model with few attempts is as likely as one with many', () => {
    const many = Array.from({ length: 9 }, (_, i) => attempt({ model: 'big', attempt: i }))
    const few = attempt({ model: 'small' })
    // The first draw picks the model (< 0.5 the first name in the pool, >= 0.5 the second), the second draw its attempt.
    const seq = (...xs: number[]) => () => xs.shift()!
    expect(pickCase([...many, few], null, seq(0.75, 0))).toBe(few)
    expect(pickCase([...many, few], null, seq(0.25, 0.99))).toBe(many[8])
    expect(pickCase([few], few)).toBeNull()
    // The current attempt is its model's only one, so that model drops out of the draw.
    expect(pickCase([few, many[0], many[1]], few, seq(0.99, 0.5))).toBe(many[1])
  })

  it('links Source to the raw results of the case, or to the repo without an experiment id', () => {
    expect(sourceUrl({ experimentId: 'exp-1', model: 'gpt-6.1-sol' })).toBe(`${SOURCE}/blob/results/exp-1/results/exp-1/raw/gpt-6.1-sol.jsonl`)
    expect(sourceUrl({ model: 'm1' })).toBe(SOURCE)
  })

  it('shows ". Source" after the result, linking to its raw results in a new tab', async () => {
    stub({ '3x3': [attempt({ experimentId: 'exp-1' })] })
    await mount()
    await run()
    expect(screen.queryByRole('link', { name: /^Source/ })).toBeNull()
    await finish()
    const link = screen.getByRole('link', { name: /^Source/ })
    expect(link).toHaveAttribute('href', `${SOURCE}/blob/results/exp-1/results/exp-1/raw/m1.jsonl`)
    expect(link).toHaveAttribute('target', '_blank')
    expect(row().textContent).toMatch(/Solved\. Source/)
  })

  it('announces the result once the run ends, not while it runs', async () => {
    stub({ '3x3': [attempt({})] })
    await mount()
    const live = document.querySelector('[aria-live="polite"]')!
    expect(live).toHaveTextContent(/^$/)
    await run()
    expect(live).toHaveTextContent(/^$/)
    await finish()
    expect(live).toHaveTextContent('Result: Solved')
  })

  it('shakes again on Re-run, and never under reduced motion', async () => {
    stub({ '3x3': [attempt({ outcome: 'hallucination', moves: ['Q'] })] })
    const first = await mount()
    await run()
    await finish()
    expect(document.querySelector('.cube-stage.shake')).not.toBeNull()
    await run('Re-run')
    expect(document.querySelector('.cube-stage.shake')).toBeNull()
    await finish()
    expect(document.querySelector('.cube-stage.shake')).not.toBeNull()
    first.unmount()
    resetAttempts()
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {} }))
    stub({ '3x3': [attempt({ outcome: 'hallucination', moves: ['Q'] })] })
    await mount()
    await run()
    await finish()
    expect(document.querySelector('.cube-stage.shake')).toBeNull()
  })

  it('shakes the cube when a run ends on an illegal move, not when it ends on a legal one', async () => {
    stub({ '3x3': [attempt({ outcome: 'hallucination', moves: ['U', 'Q'] })] })
    const first = await mount()
    await run()
    expect(document.querySelector('.cube-stage.shake')).toBeNull()
    await finish()
    expect(document.querySelector('.cube-stage.shake')).not.toBeNull()
    first.unmount()
    resetAttempts()
    stub({ '3x3': [attempt({})] })
    await mount()
    await run()
    await finish()
    expect(document.querySelector('.cube-stage.shake')).toBeNull()
  })

  it('names an unsolvable state without a reason when the import did not record one', () => {
    expect(stateText({ puzzle: '2x2', validity: 'invalid', corruption: null })).toBe('2x2 cube, not solvable')
    expect(stateText({ puzzle: '2x2', validity: 'invalid' })).toBe('2x2 cube, not solvable')
  })

  it('shows the case before Run: state, model, the Result line laid out but hidden, Run, no Source link yet', async () => {
    stub({ '3x3': [attempt({ validity: 'invalid', corruption: 'twisted corner UFL clockwise', outcome: 'success', mismatch: true })] })
    await mount()
    expect(screen.getByText('Experiment Example')).toBeInTheDocument()
    expect(fact('State:')).toBe('3x3 cube, not solvable: twisted corner UFL clockwise')
    expect(fact('Model:')).toBe('m1')
    expect(screen.queryByText(/Expected Result/)).toBeNull()
    expect(screen.getByText('Result:').parentElement).toHaveStyle({ visibility: 'hidden' })
    const runButton = screen.getByRole('button', { name: 'Run' })
    expect(runButton).toBeEnabled()
    expect(screen.queryByRole('link', { name: /^Source/ })).toBeNull()
  })

  it('says a valid input is solvable and leaves out an unknown reason', async () => {
    stub({ '3x3': [attempt({})] })
    await mount()
    expect(fact('State:')).toBe('3x3 cube, solvable')
  })

  it('shows only Run while nothing is loaded', () => {
    stub({ '3x3': [] })
    render(<Player puzzle="3x3" models={['m1']} attemptsUrl="/a.json" legalMoves={LEGAL} />)
    expect(document.querySelector('.facts')).toBeNull()
    expect(screen.getByRole('button', { name: 'Run' })).toBeInTheDocument()
  })

  it('ends a hallucinated attempt on its result with a cross, never lists the moves, and offers Re-run', async () => {
    stub({ '3x3': [attempt({ outcome: 'hallucination', moves: ['U', 'Q', 'R'] })] })
    await mount()
    await run()
    expect(screen.getByRole('button', { name: 'Re-run' })).toBeDisabled()
    expect(result()).toHaveTextContent('running… 0%')
    await finish()
    expect(result()).toHaveTextContent('Hallucinated')
    expect(row()).toHaveAttribute('data-verdict', 'wrong')
    expect(row().querySelector('dd .verdict-icon')).not.toBeNull()
    expect(screen.getByRole('button', { name: 'Re-run' })).toBeEnabled()
    expect(screen.queryByText(/\bQ\b/)).toBeNull()
  })

  it('plays one move per 0.5 s and shows the share of moves done while it runs', async () => {
    stub({ '3x3': [attempt({ moves: ['U', 'R', "R'", "U'"] })] })
    await mount()
    await run()
    expect(result()).toHaveTextContent('running… 0%')
    await act(async () => void vi.advanceTimersByTime(1000)) // two moves of four
    expect(result()).toHaveTextContent(/running… (4\d|50)%/)
    await act(async () => void vi.advanceTimersByTime(1100))
    expect(result()).toHaveTextContent('Solved')
  })

  it('shows the result after a short beat when no move is playable', async () => {
    stub({ '3x3': [attempt({ outcome: 'hallucination', moves: ['Q'] })] })
    await mount()
    await run()
    await act(async () => void vi.advanceTimersByTime(1000))
    expect(result()).toHaveTextContent('Hallucinated')
  })

  it('replays a solved attempt to solved with a tick, and colours a mismatch by its outcome', async () => {
    stub({ '3x3': [attempt({})] })
    const first = await mount()
    await run()
    await finish()
    expect(result()).toHaveTextContent('Solved')
    expect(row()).toHaveAttribute('data-verdict', 'correct')
    first.unmount()
    resetAttempts()
    stub({ '3x3': [attempt({ outcome: 'failure', mismatch: true })] })
    const second = await mount()
    await run()
    await finish()
    expect(result()).toHaveTextContent('Not solved')
    expect(row()).toHaveAttribute('data-verdict', 'wrong')
    second.unmount()
    resetAttempts()
    stub({ '3x3': [attempt({ validity: 'invalid', outcome: 'success', mismatch: true })] })
    await mount()
    await run()
    await finish()
    expect(result()).toHaveTextContent('Mismatch detected')
    expect(row()).toHaveAttribute('data-verdict', 'correct')
  })

  it('fetches once and re-runs the same attempt', async () => {
    stub({ '3x3': [attempt({})] })
    await mount()
    await run()
    await finish()
    await run('Re-run')
    expect(row()).not.toHaveAttribute('data-verdict')
    await finish()
    expect(result()).toHaveTextContent('Solved')
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('the refresh button shows another case, back before Run; it is hidden when there is no other', async () => {
    stub({ '3x3': [attempt({ validity: 'valid' }), attempt({ validity: 'invalid', outcome: 'success', mismatch: true })] })
    await mount()
    const before = fact('State:')
    await run()
    await finish()
    fireEvent.click(screen.getByRole('button', { name: 'Show another case' }))
    expect(fact('State:')).not.toBe(before)
    expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled()
    expect(screen.getByText('Result:').parentElement).toHaveStyle({ visibility: 'hidden' })
    cleanup()
    resetAttempts()
    stub({ '3x3': [attempt({})] })
    await mount()
    expect(screen.queryByRole('button', { name: 'Show another case' })).toBeNull()
  })

  it('only shows attempts of the selected models', async () => {
    stub({ '3x3': [attempt({ model: 'other', outcome: 'hallucination' }), attempt({})] })
    await mount()
    expect(fact('Model:')).toBe('m1')
  })

  it('a failed first load stays quiet; Run retries and reports a failure', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false })))
    await mount()
    expect(screen.queryByRole('alert')).toBeNull()
    await run()
    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled()
    expect(fetch).toHaveBeenCalledTimes(2)
  })
})
