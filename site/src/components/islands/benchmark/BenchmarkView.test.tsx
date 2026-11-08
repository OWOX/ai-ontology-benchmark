import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ModelMetrics } from '../../../lib/benchmark'
import { resetAttempts } from './attempts'
import BenchmarkView from './BenchmarkView'

const rate = (value: number | null, n: number) => ({ value, n })
const row = (puzzle: string, model: string, provider: string, o: Partial<ModelMetrics> = {}): ModelMetrics => ({
  puzzle, model, provider, success: rate(0.5, 10), hallucination: rate(0.25, 8), detection: rate(null, 0), ...o,
})
const metrics = [
  row('3x3', 'claude-a', 'anthropic'),
  row('3x3', 'gpt-a', 'openai', { success: rate(1, 4), hallucination: rate(0.5, 8) }),
  row('4x4', 'claude-a', 'anthropic'),
]
const view = () => render(<BenchmarkView metrics={metrics} attemptsUrl="/a.json" />)

const on = (name: string | RegExp) => screen.getByRole('checkbox', { name, checked: true })
const off = (name: string | RegExp) => screen.getByRole('checkbox', { name, checked: false })

beforeEach(() => history.replaceState(null, '', '/'))

describe('BenchmarkView', () => {
  it('opens on the first puzzle with data, every provider ticked as a checkbox, every model on, and no hash', () => {
    view()
    expect(screen.getByRole('radio', { name: '3x3 cube' })).toBeChecked()
    expect(on('Anthropic')).toBeInTheDocument()
    expect(on('OpenAI')).toBeInTheDocument()
    expect(within(screen.getByRole('group', { name: 'Model' })).getAllByRole('checkbox').map((b) => b.parentElement!.textContent)).toEqual(['claude-a', 'gpt-a'])
    expect(location.hash).toBe('')
    expect(screen.getByRole('img', { name: /^Success rate/ })).toHaveAccessibleName('Success rate: claude-a 50% (worst), gpt-a 100% (best)')
  })

  it('shows the filter as three steps with an icon each, the Model step only while a provider is ticked, and a drawing on each puzzle option', () => {
    const { container } = view()
    const titles = () => [...container.querySelectorAll('ol.steps > li > .title')].map((t) => t.textContent)
    expect(titles()).toEqual(['Puzzle', 'AI provider', 'Model'])
    for (const n of container.querySelectorAll('ol.steps .num')) {
      expect(n.textContent).toBe('')
      const svg = n.querySelector('svg')!
      expect(svg).toHaveAttribute('aria-hidden', 'true')
      // A disc in the current colour with the icon's strokes masked out of it.
      expect(svg.querySelector('circle')).toHaveAttribute('fill', 'currentColor')
      expect(svg.querySelector('circle')!.getAttribute('mask')).toMatch(/^url\(#icon-/)
      expect(svg.querySelector('mask g')).toHaveAttribute('stroke', '#000')
    }
    expect(container.querySelector('ol.steps > li > .body [role="radiogroup"]')).not.toBeNull()
    for (const r of screen.getAllByRole('radio')) expect(r.querySelector('svg.cube-view')).not.toBeNull()
    fireEvent.click(on('OpenAI'))
    fireEvent.click(on('Anthropic'))
    expect(titles()).toEqual(['Puzzle', 'AI provider'])
  })

  it('lists only puzzles with data and only providers with a model for the puzzle', () => {
    view()
    expect(screen.queryByRole('radio', { name: /2x2/ })).toBeNull()
    expect(screen.queryByRole('radio', { name: /5x5/ })).toBeNull()
    expect(screen.queryByText(/no data yet/)).toBeNull()
    fireEvent.click(screen.getByRole('radio', { name: '4x4 cube' }))
    expect(screen.queryByRole('checkbox', { name: 'OpenAI' })).toBeNull()
  })

  it('lists the ticked providers\' models, all on, and charts only those', () => {
    view()
    fireEvent.click(on('Anthropic'))
    expect(off('Anthropic')).toBeInTheDocument()
    const models = screen.getByRole('group', { name: 'Model' })
    expect(within(models).getAllByRole('checkbox').map((b) => b.parentElement!.textContent)).toEqual(['gpt-a'])
    expect(on('gpt-a')).toBeInTheDocument()
    const success = screen.getByRole('img', { name: /^Success rate/ })
    expect(success).toHaveAccessibleName('Success rate: gpt-a 100%')
    fireEvent.click(on('gpt-a'))
    expect(screen.getByText('No model selected.')).toBeInTheDocument()
  })

  it('with no provider ticked: no Model step, no chart or experiment line, a hint, Run disabled, an empty providers= in the hash', () => {
    view()
    fireEvent.click(on('OpenAI'))
    fireEvent.click(on('Anthropic'))
    expect(screen.queryByRole('group', { name: 'Model' })).toBeNull()
    expect(screen.queryByRole('img', { name: /^Success rate/ })).toBeNull()
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Pick an AI provider to see results.')
    expect(screen.getByRole('button', { name: 'Run' })).toBeDisabled()
    expect(location.hash).toBe('#providers=')
    fireEvent.click(off('OpenAI'))
    expect(screen.getByRole('img', { name: /^Success rate/ })).toHaveAccessibleName('Success rate: gpt-a 100%')
    expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled()
  })

  it('falls back to every provider of the puzzle when only absent providers are ticked', () => {
    history.replaceState(null, '', '/#puzzle=4x4&providers=openai')
    view()
    expect(on('Anthropic')).toBeInTheDocument()
    expect(on('claude-a')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /^Success rate/ })).toHaveAccessibleName('Success rate: claude-a 50%')
    expect(location.hash).toBe('#puzzle=4x4')
    cleanup()
    history.replaceState(null, '', '/')
    view()
    fireEvent.click(on('Anthropic')) // only OpenAI ticked, which 4x4 lacks
    fireEvent.click(screen.getByRole('radio', { name: '4x4 cube' }))
    expect(on('Anthropic')).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Model' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled()
  })

  it('a toggle that leaves none of the puzzle\'s providers ticked means none: hint, no fallback, providers= in the hash', () => {
    view()
    fireEvent.click(screen.getByRole('radio', { name: '4x4 cube' })) // only Anthropic here
    fireEvent.click(on('Anthropic'))
    expect(off('Anthropic')).toBeInTheDocument()
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Pick an AI provider to see results.')
    expect(screen.queryByRole('group', { name: 'Model' })).toBeNull()
    expect(location.hash).toBe('#puzzle=4x4&providers=')
  })

  it('keeps providers the current puzzle lacks ticked while toggling, across puzzle switches', () => {
    const three = [row('3x3', 'claude-a', 'anthropic'), row('3x3', 'gpt-a', 'openai'), row('4x4', 'claude-a', 'anthropic'), row('4x4', 'gem-a', 'google')]
    render(<BenchmarkView metrics={three} attemptsUrl="/a.json" />)
    fireEvent.click(screen.getByRole('radio', { name: '4x4 cube' }))
    fireEvent.click(on('Google')) // 4x4 has no OpenAI: it stays ticked underneath
    expect(off('Google')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: '3x3 cube' }))
    expect(on('OpenAI')).toBeInTheDocument()
    expect(on('Anthropic')).toBeInTheDocument()
  })

  it('lays the models out one column per provider', () => {
    const { container } = view()
    const cols = [...container.querySelectorAll('.checks.columns .column')].map((c) => [...c.querySelectorAll('label')].map((l) => l.textContent))
    expect(cols).toEqual([['claude-a'], ['gpt-a']])
  })

  it('resets the model choice on a puzzle change', () => {
    view()
    fireEvent.click(on('claude-a'))
    expect(off('claude-a')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: '4x4 cube' }))
    expect(on('claude-a')).toBeInTheDocument()
  })

  it('shows one chart at a time through the metric tabs, Success rate first', () => {
    const { container } = view()
    expect(screen.getByRole('tab', { name: 'Success rate' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(['Success rate', 'Hallucination rate', 'Critical thinking'])
    expect(container.querySelectorAll('figure.chart').length).toBe(1)
    expect(screen.getByRole('tabpanel')).toHaveAccessibleName('Success rate')
    fireEvent.click(screen.getByRole('tab', { name: 'Hallucination rate' }))
    expect(screen.getByRole('img', { name: /^Hallucination rate/ })).toHaveAccessibleName('Hallucination rate: claude-a 25% (best), gpt-a 50% (worst)')
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Hallucination rate' }), { key: 'ArrowRight' })
    expect(screen.getByRole('tab', { name: 'Critical thinking' })).toHaveAttribute('aria-selected', 'true')
  })

  it('marks the best and worst bars by the metric\'s direction', () => {
    const { container } = view()
    const ranks = () => [...container.querySelectorAll('.chart .row')].map((r) => r.getAttribute('data-rank'))
    expect(ranks()).toEqual(['worst', 'best'])
    fireEvent.click(screen.getByRole('tab', { name: 'Hallucination rate' }))
    expect(ranks()).toEqual(['best', 'worst']) // lower is better: claude-a 25% beats gpt-a 50%
    fireEvent.click(screen.getByRole('tab', { name: 'Critical thinking' }))
    expect(ranks()).toEqual([null, null])
  })

  it('frames the chart: the tabs and a tabpanel in one block', () => {
    const { container } = view()
    const metrics = container.querySelector('.metrics')!
    expect(metrics.querySelector('[role="tablist"]')).not.toBeNull()
    expect(metrics.querySelector('[role="tabpanel"] figure.chart')).not.toBeNull()
  })

  it('writes the filter into the hash without adding history, a key only when not at its default', () => {
    const before = history.length
    view()
    fireEvent.click(on('Anthropic'))
    expect(location.hash).toBe('#providers=openai')
    fireEvent.click(on('gpt-a'))
    expect(location.hash).toBe('#providers=openai&models=')
    fireEvent.click(off('gpt-a'))
    fireEvent.click(off('Anthropic'))
    expect(location.hash).toBe('')
    fireEvent.click(screen.getByRole('tab', { name: 'Hallucination rate' }))
    fireEvent.click(screen.getByRole('radio', { name: '4x4 cube' }))
    expect(location.hash).toBe('#puzzle=4x4&metric=hallucination')
    fireEvent.click(screen.getByRole('tab', { name: 'Success rate' }))
    fireEvent.click(screen.getByRole('radio', { name: '3x3 cube' }))
    expect(location.hash).toBe('')
    expect(history.length).toBe(before)
  })

  it('starts from the hash, ignoring values that do not exist', () => {
    history.replaceState(null, '', '/#puzzle=4x4&providers=anthropic,nope&models=claude-a&metric=detection')
    view()
    expect(screen.getByRole('radio', { name: '4x4 cube' })).toBeChecked()
    expect(on('Anthropic')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Critical thinking' })).toHaveAttribute('aria-selected', 'true')
    cleanup()
    history.replaceState(null, '', '/#puzzle=9x9&providers=nope&models=zzz&metric=bogus')
    view()
    expect(screen.getByRole('radio', { name: '3x3 cube' })).toBeChecked()
    expect(on('OpenAI')).toBeInTheDocument()
    expect(on('gpt-a')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Success rate' })).toHaveAttribute('aria-selected', 'true')
    expect(location.hash).toBe('')
  })

  it('leaves the filter alone on an in-page anchor, but an emptied hash resets it', () => {
    view()
    fireEvent.click(on('Anthropic'))
    act(() => { history.replaceState(null, '', '/#intro'); window.dispatchEvent(new HashChangeEvent('hashchange')) })
    expect(off('Anthropic')).toBeInTheDocument()
    act(() => { history.replaceState(null, '', '/'); window.dispatchEvent(new HashChangeEvent('hashchange')) })
    expect(on('Anthropic')).toBeInTheDocument()
  })

  it('restores ticked providers and models from the hash, and follows hashchange', () => {
    history.replaceState(null, '', '/#providers=openai,anthropic&models=gpt-a')
    view()
    expect(off('claude-a')).toBeInTheDocument()
    expect(on('gpt-a')).toBeInTheDocument()
    act(() => {
      history.replaceState(null, '', '/#providers=')
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(off('Anthropic')).toBeInTheDocument()
    expect(off('OpenAI')).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Model' })).toBeNull()
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Pick an AI provider to see results.')
  })

  it('shows n/a and no bar for a null rate, never n, and no footnote', () => {
    const { container } = view()
    fireEvent.click(screen.getByRole('tab', { name: 'Critical thinking' }))
    expect(screen.getAllByText('n/a').length).toBe(2)
    expect(container.querySelectorAll('.chart .fill').length).toBe(0)
    expect(container.textContent).not.toMatch(/n = /)
    expect(container.querySelector('.note')).toBeNull()
    expect(container.textContent).not.toMatch(/Based on/)
  })

  it('wears the /cube solver classes so the shared stage and button styles apply', () => {
    const { container } = view()
    expect(container.querySelector('.benchmark.cube-solver')).not.toBeNull()
    expect(container.querySelector('.player .cube-stage .views')).not.toBeNull()
    expect(screen.getByRole('button', { name: 'Run' })).toBeInTheDocument()
  })

  it('fetches attempts.json once across filter changes', async () => {
    resetAttempts()
    const data = { '3x3': [{ model: 'claude-a', puzzle: '3x3', validity: 'valid', setup: 'descriptive', attempt: 1, state: '', moves: [], outcome: 'hallucination', mismatch: false }] }
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => data })))
    view()
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    await act(async () => {})
    fireEvent.click(on('OpenAI'))
    fireEvent.click(screen.getByRole('button', { name: 'Run' }))
    await act(async () => {})
    expect(fetch).toHaveBeenCalledTimes(1)
    vi.unstubAllGlobals()
  })

  describe('metric definitions', () => {
    const defs = [
      { key: 'success', name: 'Success rate', definition: 'The share of attempts that solved it.' },
      { key: 'hallucination', name: 'Hallucination rate', definition: 'The share of attempts with an impossible move.' },
    ]
    const withDefs = () => render(<BenchmarkView metrics={metrics} attemptsUrl="/a.json" definitions={defs} />)

    it('shows a "?" only on a tab whose metric has a definition, and it is no part of the tab button', () => {
      withDefs()
      expect(screen.getByRole('button', { name: 'What is Success rate?' })).toHaveAttribute('aria-expanded', 'false')
      expect(screen.getByRole('button', { name: 'What is Hallucination rate?' })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'What is Critical thinking?' })).toBeNull()
      const help = screen.getByRole('button', { name: 'What is Success rate?' })
      expect(help.closest('[role="tab"]')).toBeNull()
      expect(screen.getAllByRole('tab')).toHaveLength(3)
      // The tablist holds only tabs.
      const list = screen.getByRole('tablist')
      expect([...list.children].every((c) => c.getAttribute('role') === 'tab')).toBe(true)
      expect(list.contains(help)).toBe(false)
    })

    it('shows none without definitions', () => {
      view()
      expect(screen.queryByRole('button', { name: /^What is/ })).toBeNull()
    })

    it('opens on click with the name, the definition and the direction, one at a time, and closes on a second click', () => {
      withDefs()
      const success = screen.getByRole('button', { name: 'What is Success rate?' })
      fireEvent.click(success)
      expect(success).toHaveAttribute('aria-expanded', 'true')
      expect(success).toHaveAttribute('aria-controls', 'metric-popover')
      const pop = document.getElementById('metric-popover')!
      expect(pop).toHaveTextContent('Success rate')
      expect(pop.querySelector('strong')).toHaveTextContent('Success rate')
      expect(pop).toHaveTextContent('The share of attempts that solved it.')
      expect(pop).toHaveTextContent('Higher is better.')
      expect(pop).toHaveAttribute('role', 'region')
      expect(pop).toHaveAccessibleName('Success rate')
      expect(success).toHaveAttribute('aria-describedby', 'metric-popover')
      fireEvent.click(screen.getByRole('button', { name: 'What is Hallucination rate?' }))
      expect(success).toHaveAttribute('aria-expanded', 'false')
      expect(document.querySelectorAll('.metric-popover')).toHaveLength(1)
      expect(document.getElementById('metric-popover')).toHaveTextContent('Lower is better.')
      fireEvent.click(screen.getByRole('button', { name: 'What is Hallucination rate?' }))
      expect(document.getElementById('metric-popover')).toBeNull()
    })

    it('closes on Escape and on a click outside, but not on a click inside', () => {
      withDefs()
      const success = screen.getByRole('button', { name: 'What is Success rate?' })
      fireEvent.click(success)
      success.focus()
      fireEvent.pointerDown(document.getElementById('metric-popover')!)
      expect(document.getElementById('metric-popover')).not.toBeNull()
      fireEvent.keyDown(document, { key: 'Escape' })
      expect(document.getElementById('metric-popover')).toBeNull()
      expect(success).toHaveFocus()
      fireEvent.click(success)
      fireEvent.pointerDown(document.body)
      expect(document.getElementById('metric-popover')).toBeNull()
    })

    it('closes on Escape from anywhere but only takes focus back when it was on the popover or the "?"', () => {
      withDefs()
      const success = screen.getByRole('button', { name: 'What is Success rate?' })
      fireEvent.click(success)
      const other = screen.getByRole('radio', { name: '3x3 cube' })
      other.focus()
      fireEvent.keyDown(document, { key: 'Escape' })
      expect(document.getElementById('metric-popover')).toBeNull()
      expect(other).toHaveFocus()
    })

    describe('hover', () => {
      // jsdom has no PointerEvent, so pointerType would be lost; give the events one.
      const mouse = (type: 'pointerEnter' | 'pointerLeave', el: Element, pointerType = 'mouse') => {
        const Orig = window.PointerEvent
        class P extends MouseEvent { pointerType: string; constructor(t: string, i: any = {}) { super(t, i); this.pointerType = i.pointerType ?? '' } }
        ;(window as any).PointerEvent = P
        fireEvent[type](el, { pointerType })
        ;(window as any).PointerEvent = Orig
      }
      beforeEach(() => vi.useFakeTimers())
      afterEach(() => vi.useRealTimers())

      it('opens when a mouse enters the "?" and closes 150ms after it leaves', () => {
        withDefs()
        const help = screen.getByRole('button', { name: 'What is Success rate?' })
        mouse('pointerEnter', help)
        expect(document.getElementById('metric-popover')).not.toBeNull()
        mouse('pointerLeave', help)
        act(() => { vi.advanceTimersByTime(100) })
        expect(document.getElementById('metric-popover')).not.toBeNull()
        act(() => { vi.advanceTimersByTime(60) })
        expect(document.getElementById('metric-popover')).toBeNull()
      })

      it('stays open when the pointer moves into the box in time, and closes after it leaves the box', () => {
        withDefs()
        const help = screen.getByRole('button', { name: 'What is Success rate?' })
        mouse('pointerEnter', help)
        mouse('pointerLeave', help)
        act(() => { vi.advanceTimersByTime(100) })
        mouse('pointerEnter', document.getElementById('metric-popover')!)
        act(() => { vi.advanceTimersByTime(500) })
        expect(document.getElementById('metric-popover')).not.toBeNull()
        mouse('pointerLeave', document.getElementById('metric-popover')!)
        act(() => { vi.advanceTimersByTime(160) })
        expect(document.getElementById('metric-popover')).toBeNull()
      })

      it('never opens on hover for touch or pen', () => {
        withDefs()
        mouse('pointerEnter', screen.getByRole('button', { name: 'What is Success rate?' }), 'touch')
        expect(document.getElementById('metric-popover')).toBeNull()
      })

      it('a click on a hover-opened "?" pins it open; the next click closes it', () => {
        withDefs()
        const help = screen.getByRole('button', { name: 'What is Success rate?' })
        mouse('pointerEnter', help)
        fireEvent.click(help)
        mouse('pointerLeave', help)
        act(() => { vi.advanceTimersByTime(500) })
        expect(document.getElementById('metric-popover')).not.toBeNull()
        fireEvent.click(help)
        expect(document.getElementById('metric-popover')).toBeNull()
      })
    })

    it('keeps the arrow keys moving between the tabs only', () => {
      withDefs()
      screen.getByRole('tab', { name: 'Success rate' }).focus()
      fireEvent.keyDown(screen.getByRole('tab', { name: 'Success rate' }), { key: 'ArrowRight' })
      expect(screen.getByRole('tab', { name: 'Hallucination rate' })).toHaveAttribute('aria-selected', 'true')
      expect(screen.getByRole('tab', { name: 'Hallucination rate' })).toHaveFocus()
      fireEvent.keyDown(screen.getByRole('button', { name: 'What is Success rate?' }), { key: 'ArrowRight' })
      expect(screen.getByRole('tab', { name: 'Hallucination rate' })).toHaveAttribute('aria-selected', 'true')
    })
  })
})
