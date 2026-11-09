import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ModelMetrics, SetupMetrics } from '../../../lib/benchmark'
import { resetAttempts } from './attempts'
import BenchmarkView from './BenchmarkView'

const rate = (value: number | null, n: number) => ({ value, n })
const row = (puzzle: string, model: string, provider: string, o: Partial<ModelMetrics> = {}): ModelMetrics => ({
  puzzle, model, provider, attempts: 10, tokens: 1000, precision: rate(0.5, 10), hallucination: rate(0.25, 8), critical: rate(null, 0), ...o,
})
const metrics = [
  row('3x3', 'claude-a', 'anthropic'),
  row('3x3', 'gpt-a', 'openai', { precision: rate(1, 4), hallucination: rate(0.5, 8) }),
  row('4x4', 'claude-a', 'anthropic'),
]
const view = () => render(<BenchmarkView metrics={metrics} attemptsUrl="/a.json" />)

const on = (name: string | RegExp) => screen.getByRole('checkbox', { name, checked: true })
const off = (name: string | RegExp) => screen.getByRole('checkbox', { name, checked: false })

beforeEach(() => history.replaceState(null, '', '/'))

describe('BenchmarkView', () => {
  it('opens on the first puzzle with data, every provider ticked as a checkbox, every model on, and no hash', () => {
    view()
    expect(screen.getByRole('button', { name: '3x3 cube' })).toHaveAttribute('aria-pressed', 'true')
    expect(on('Anthropic')).toBeInTheDocument()
    expect(on('OpenAI')).toBeInTheDocument()
    expect(within(screen.getByRole('group', { name: 'Model' })).getAllByRole('checkbox').map((b) => b.parentElement!.textContent)).toEqual(['claude-a', 'gpt-a'])
    expect(location.hash).toBe('')
    expect(screen.getByRole('img', { name: /^Precision/ })).toHaveAccessibleName('Precision: claude-a 50% (worst), gpt-a 100% (best)')
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
    expect(container.querySelector('ol.steps > li > .body [role="group"] button[aria-pressed]')).not.toBeNull()
    for (const r of container.querySelectorAll('button[aria-pressed]')) expect(r.querySelector('svg.cube-view')).not.toBeNull()
    fireEvent.click(on('OpenAI'))
    fireEvent.click(on('Anthropic'))
    expect(titles()).toEqual(['Puzzle', 'AI provider'])
  })

  it('lists only puzzles with data and only providers with a model for the puzzle', () => {
    view()
    expect(screen.queryByRole('button', { name: /2x2/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /5x5/ })).toBeNull()
    expect(screen.queryByText(/no data yet/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '4x4 cube' }))
    expect(screen.queryByRole('checkbox', { name: 'OpenAI' })).toBeNull()
  })

  it('lists the ticked providers\' models, all on, and charts only those', () => {
    view()
    fireEvent.click(on('Anthropic'))
    expect(off('Anthropic')).toBeInTheDocument()
    const models = screen.getByRole('group', { name: 'Model' })
    expect(within(models).getAllByRole('checkbox').map((b) => b.parentElement!.textContent)).toEqual(['gpt-a'])
    expect(on('gpt-a')).toBeInTheDocument()
    const success = screen.getByRole('img', { name: /^Precision/ })
    expect(success).toHaveAccessibleName('Precision: gpt-a 100%')
    fireEvent.click(on('gpt-a'))
    expect(screen.getByText('No model selected.')).toBeInTheDocument()
  })

  it('with no provider ticked: no Model step, no chart or experiment line, a hint, Run disabled, an empty providers= in the hash', () => {
    view()
    fireEvent.click(on('OpenAI'))
    fireEvent.click(on('Anthropic'))
    expect(screen.queryByRole('group', { name: 'Model' })).toBeNull()
    expect(screen.queryByRole('img', { name: /^Precision/ })).toBeNull()
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Pick an AI provider to see results.')
    expect(screen.getByRole('button', { name: 'Run' })).toBeDisabled()
    expect(location.hash).toBe('#providers=')
    fireEvent.click(off('OpenAI'))
    expect(screen.getByRole('img', { name: /^Precision/ })).toHaveAccessibleName('Precision: gpt-a 100%')
    expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled()
  })

  it('falls back to every provider of the puzzle when only absent providers are ticked', () => {
    history.replaceState(null, '', '/#puzzle=4x4&providers=openai')
    view()
    expect(on('Anthropic')).toBeInTheDocument()
    expect(on('claude-a')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /^Precision/ })).toHaveAccessibleName('Precision: claude-a 50%')
    expect(location.hash).toBe('#puzzle=4x4')
    cleanup()
    history.replaceState(null, '', '/')
    view()
    fireEvent.click(on('Anthropic')) // only OpenAI ticked, which 4x4 lacks
    fireEvent.click(screen.getByRole('button', { name: '4x4 cube' }))
    expect(on('Anthropic')).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Model' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled()
  })

  it('a toggle that leaves none of the puzzle\'s providers ticked means none: hint, no fallback, providers= in the hash', () => {
    view()
    fireEvent.click(screen.getByRole('button', { name: '4x4 cube' })) // only Anthropic here
    fireEvent.click(on('Anthropic'))
    expect(off('Anthropic')).toBeInTheDocument()
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Pick an AI provider to see results.')
    expect(screen.queryByRole('group', { name: 'Model' })).toBeNull()
    expect(location.hash).toBe('#puzzle=4x4&providers=')
  })

  it('keeps providers the current puzzle lacks ticked while toggling, across puzzle switches', () => {
    const three = [row('3x3', 'claude-a', 'anthropic'), row('3x3', 'gpt-a', 'openai'), row('4x4', 'claude-a', 'anthropic'), row('4x4', 'gem-a', 'google')]
    render(<BenchmarkView metrics={three} attemptsUrl="/a.json" />)
    fireEvent.click(screen.getByRole('button', { name: '4x4 cube' }))
    fireEvent.click(on('Google')) // 4x4 has no OpenAI: it stays ticked underneath
    expect(off('Google')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '3x3 cube' }))
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
    fireEvent.click(screen.getByRole('button', { name: '4x4 cube' }))
    expect(on('claude-a')).toBeInTheDocument()
  })

  it('shows one chart at a time through the three metric tabs, Precision first', () => {
    const { container } = view()
    expect(screen.getByRole('tab', { name: 'Precision' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(['Precision', 'Hallucination rate', 'Critical thinking'])
    expect(container.querySelectorAll('figure.chart-figure').length).toBe(1)
    expect(screen.getByRole('tabpanel')).toHaveAccessibleName('Precision')
    fireEvent.click(screen.getByRole('tab', { name: 'Hallucination rate' }))
    expect(screen.getByRole('img', { name: /^Hallucination rate/ })).toHaveAccessibleName('Hallucination rate: claude-a 25% (best), gpt-a 50% (worst)')
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Hallucination rate' }), { key: 'ArrowRight' })
    expect(screen.getByRole('tab', { name: 'Critical thinking' })).toHaveAttribute('aria-selected', 'true')
  })


  it('has no cost tab, and an old #metric=cost falls back to Precision', () => {
    history.replaceState(null, '', '/#metric=cost')
    view()
    expect(screen.queryByRole('tab', { name: 'Cost efficiency' })).toBeNull()
    expect(screen.getByRole('tab', { name: 'Precision' })).toHaveAttribute('aria-selected', 'true')
  })

  it('keeps the three tabs in one unwrapped tablist and moves a "?" with the tablist scroll', () => {
    render(<BenchmarkView metrics={metrics} attemptsUrl="/a.json" definitions={[{ key: 'precision', name: 'Balanced precision', definition: 'd' }]} />)
    const list = screen.getByRole('tablist')
    expect(within(list).getAllByRole('tab')).toHaveLength(3)
    const tab = screen.getByRole('tab', { name: 'Precision' })
    const rect = (left: number, right: number) => ({ left, right, top: 0, bottom: 10, width: right - left, height: 10, x: left, y: 0, toJSON() {} }) as DOMRect
    const at = { right: 100 }
    vi.spyOn(list, 'getBoundingClientRect').mockReturnValue(rect(0, 200))
    vi.spyOn(tab, 'getBoundingClientRect').mockImplementation(() => rect(at.right - 100, at.right))
    fireEvent.scroll(list)
    expect(screen.getByRole('button', { name: 'What is Precision?' })).toBeInTheDocument()
    at.right = 300 // scrolled so that the tab ends beyond the tablist
    fireEvent.scroll(list)
    expect(screen.queryByRole('button', { name: 'What is Precision?' })).toBeNull()
    at.right = 150
    fireEvent.scroll(list)
    expect(screen.getByRole('button', { name: 'What is Precision?' })).toBeInTheDocument()
    vi.restoreAllMocks()
  })

  it('closes the open popover when its tab scrolls out of the tablist', () => {
    render(<BenchmarkView metrics={metrics} attemptsUrl="/a.json" definitions={[{ key: 'precision', name: 'Balanced precision', definition: 'd' }]} />)
    const list = screen.getByRole('tablist')
    const tab = screen.getByRole('tab', { name: 'Precision' })
    const rect = (left: number, right: number) => ({ left, right, top: 0, bottom: 10, width: right - left, height: 10, x: left, y: 0, toJSON() {} }) as DOMRect
    const at = { right: 100 }
    vi.spyOn(list, 'getBoundingClientRect').mockReturnValue(rect(0, 200))
    vi.spyOn(tab, 'getBoundingClientRect').mockImplementation(() => rect(at.right - 100, at.right))
    fireEvent.scroll(list)
    fireEvent.click(screen.getByRole('button', { name: 'What is Precision?' }))
    expect(document.getElementById('metric-popover')).not.toBeNull()
    at.right = 300
    fireEvent.scroll(list)
    expect(document.getElementById('metric-popover')).toBeNull()
    vi.restoreAllMocks()
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
    expect(metrics.querySelector('[role="tabpanel"] figure .chart')).not.toBeNull()
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
    fireEvent.click(screen.getByRole('button', { name: '4x4 cube' }))
    expect(location.hash).toBe('#puzzle=4x4&metric=hallucination')
    fireEvent.click(screen.getByRole('tab', { name: 'Precision' }))
    fireEvent.click(screen.getByRole('button', { name: '3x3 cube' }))
    expect(location.hash).toBe('')
    expect(history.length).toBe(before)
  })

  it('leads the Source note with the attempts and tokens of the models shown, following the filter', () => {
    const { container } = view()
    const note = () => container.querySelector('.steps.source .body')!.textContent
    expect(note()).toMatch(/^github\.com\/OWOX\/ai-ontology-benchmark \(opens in a new tab\)20 attempts and 2k tokens\. The repository/)
    fireEvent.click(on('OpenAI'))
    expect(note()).toMatch(/10 attempts and 1k tokens\./)
    fireEvent.click(screen.getByRole('button', { name: '4x4 cube' }))
    expect(note()).toMatch(/10 attempts and 1k tokens\./)
  })

  it('updates the Source note when a single model is unticked', () => {
    const { container } = view()
    fireEvent.click(on('gpt-a'))
    expect(container.querySelector('.steps.source .body')!.textContent).toMatch(/10 attempts and 1k tokens\./)
  })

  it('without pooled rows, clicking the pressed puzzle changes nothing: still pressed, models stay unticked, no hash', () => {
    view()
    fireEvent.click(on('gpt-a'))
    const hash = location.hash
    expect(hash).toBe('#models=claude-a')
    fireEvent.click(screen.getByRole('button', { name: '3x3 cube' }))
    expect(screen.getByRole('button', { name: '3x3 cube' })).toHaveAttribute('aria-pressed', 'true')
    expect(off('gpt-a')).toBeInTheDocument()
    expect(location.hash).toBe(hash)
  })

  it('starts from the hash, ignoring values that do not exist', () => {
    history.replaceState(null, '', '/#puzzle=4x4&providers=anthropic,nope&models=claude-a&metric=critical')
    view()
    expect(screen.getByRole('button', { name: '4x4 cube' })).toHaveAttribute('aria-pressed', 'true')
    expect(on('Anthropic')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Critical thinking' })).toHaveAttribute('aria-selected', 'true')
    cleanup()
    history.replaceState(null, '', '/#metric=detection')
    view()
    expect(screen.getByRole('tab', { name: 'Critical thinking' })).toHaveAttribute('aria-selected', 'true')
    cleanup()
    history.replaceState(null, '', '/#puzzle=9x9&providers=nope&models=zzz&metric=bogus')
    view()
    expect(screen.getByRole('button', { name: '3x3 cube' })).toHaveAttribute('aria-pressed', 'true')
    expect(on('OpenAI')).toBeInTheDocument()
    expect(on('gpt-a')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Precision' })).toHaveAttribute('aria-selected', 'true')
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

  it('shows the Source section after the Experiment Example', () => {
    const { container } = view()
    const source = screen.getByRole('region', { name: 'Source' })
    expect(container.querySelector('.player')!.compareDocumentPosition(source) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
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
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ attempts: data, prompts: {} }) })))
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
      { key: 'precision', name: 'Balanced precision', definition: 'The share of attempts that solved it.' },
      { key: 'hallucination', name: 'Hallucination rate', definition: 'The share of attempts with an impossible move.' },
    ]
    const withDefs = () => render(<BenchmarkView metrics={metrics} attemptsUrl="/a.json" definitions={defs} />)

    it('shows a "?" only on a tab whose metric has a definition, and it is no part of the tab button', () => {
      withDefs()
      expect(screen.getByRole('button', { name: 'What is Precision?' })).toHaveAttribute('aria-expanded', 'false')
      expect(screen.getByRole('button', { name: 'What is Hallucination rate?' })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'What is Critical thinking?' })).toBeNull()
      const help = screen.getByRole('button', { name: 'What is Precision?' })
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
      const success = screen.getByRole('button', { name: 'What is Precision?' })
      fireEvent.click(success)
      expect(success).toHaveAttribute('aria-expanded', 'true')
      expect(success).toHaveAttribute('aria-controls', 'metric-popover')
      const pop = document.getElementById('metric-popover')!
      expect(pop).toHaveTextContent('Balanced precision')
      expect(pop.querySelector('strong')).toHaveTextContent('Balanced precision')
      expect(pop).toHaveTextContent('The share of attempts that solved it.')
      expect(pop).toHaveTextContent('Higher is better.')
      expect(pop).toHaveAttribute('role', 'region')
      expect(pop).toHaveAccessibleName('Balanced precision')
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
      const success = screen.getByRole('button', { name: 'What is Precision?' })
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
      const success = screen.getByRole('button', { name: 'What is Precision?' })
      fireEvent.click(success)
      const other = screen.getByRole('button', { name: '3x3 cube' })
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
        const help = screen.getByRole('button', { name: 'What is Precision?' })
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
        const help = screen.getByRole('button', { name: 'What is Precision?' })
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
        mouse('pointerEnter', screen.getByRole('button', { name: 'What is Precision?' }), 'touch')
        expect(document.getElementById('metric-popover')).toBeNull()
      })

      it('a click on a hover-opened "?" pins it open; the next click closes it', () => {
        withDefs()
        const help = screen.getByRole('button', { name: 'What is Precision?' })
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
      screen.getByRole('tab', { name: 'Precision' }).focus()
      fireEvent.keyDown(screen.getByRole('tab', { name: 'Precision' }), { key: 'ArrowRight' })
      expect(screen.getByRole('tab', { name: 'Hallucination rate' })).toHaveAttribute('aria-selected', 'true')
      expect(screen.getByRole('tab', { name: 'Hallucination rate' })).toHaveFocus()
      fireEvent.keyDown(screen.getByRole('button', { name: 'What is Precision?' }), { key: 'ArrowRight' })
      expect(screen.getByRole('tab', { name: 'Hallucination rate' })).toHaveAttribute('aria-selected', 'true')
    })
  })

  describe('No puzzle selected', () => {
    const pooled = [
      row('all', 'claude-a', 'anthropic', { precision: rate(0.4, 20) }),
      row('all', 'gpt-a', 'openai', { precision: rate(0.9, 8) }),
      row('all', 'gem-a', 'google', { precision: rate(0.6, 6) }),
      ...metrics,
      row('2x2', 'gem-a', 'google'),
    ]
    const all = () => render(<BenchmarkView metrics={pooled} attemptsUrl="/a.json" />)

    it('has no All option: with none selected every puzzle is unpressed and the pooled rows are shown', () => {
      all()
      const buttons = screen.getAllByRole('button', { name: /cube$/ })
      expect(buttons.map((r) => r.getAttribute('aria-label'))).toEqual(['2x2 cube', '3x3 cube', '4x4 cube'])
      for (const b of buttons) expect(b).toHaveAttribute('aria-pressed', 'false')
      expect(screen.queryByRole('button', { name: 'All puzzles' })).toBeNull()
      expect(location.hash).toBe('')
    })

    it('selects a puzzle on click, replaces it with another, and returns to all when the selected one is clicked again', () => {
      all()
      const pressed = () => screen.getAllByRole('button', { name: /cube$/ }).filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.getAttribute('aria-label'))
      fireEvent.click(screen.getByRole('button', { name: '4x4 cube' }))
      expect(pressed()).toEqual(['4x4 cube'])
      expect(location.hash).toBe('#puzzle=4x4')
      fireEvent.click(screen.getByRole('button', { name: '3x3 cube' }))
      expect(pressed()).toEqual(['3x3 cube'])
      expect(location.hash).toBe('#puzzle=3x3')
      fireEvent.click(screen.getByRole('button', { name: '3x3 cube' }))
      expect(pressed()).toEqual([])
      expect(location.hash).toBe('')
      expect(screen.getByRole('img', { name: /^Precision/ })).toHaveAccessibleName('Precision: claude-a 40% (worst), gpt-a 90% (best), gem-a 60%')
    })

    it('charts the pooled rows and lists every model and provider', () => {
      all()
      expect(screen.getByRole('img', { name: /^Precision/ })).toHaveAccessibleName('Precision: claude-a 40% (worst), gpt-a 90% (best), gem-a 60%')
      expect(within(screen.getByRole('group', { name: 'Model' })).getAllByRole('checkbox')).toHaveLength(3)
      expect(screen.getByRole('checkbox', { name: 'Google' })).toBeChecked()
    })

    it('describes the group: none selected shows all puzzles', () => {
      all()
      const group = screen.getByRole('group', { name: 'Puzzle' })
      expect(group).toHaveAccessibleDescription('None selected shows all puzzles.')
    })

    it('resets the experiment example when the selected puzzle is unselected', async () => {
      resetAttempts()
      const a = (model: string) => ({ model, puzzle: '3x3', validity: 'valid', setup: 'descriptive', attempt: 1, state: '', moves: [], outcome: 'failure', mismatch: false })
      vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ attempts: { '3x3': [a('claude-a'), a('gpt-a')] }, prompts: {} }) })))
      all()
      fireEvent.click(screen.getByRole('button', { name: '3x3 cube' }))
      fireEvent.click(screen.getByRole('button', { name: 'Run' }))
      await act(async () => {})
      expect(screen.getByRole('button', { name: 'Re-run' })).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: '3x3 cube' }))
      expect(screen.getByRole('button', { name: 'Run' })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Re-run' })).toBeNull()
      vi.unstubAllGlobals()
    })

    it('reads a hash without a puzzle, puzzle=all, and an unknown puzzle as none selected', () => {
      for (const hash of ['/', '/#metric=critical', '/#puzzle=all', '/#puzzle=9x9']) {
        history.replaceState(null, '', hash)
        all()
        expect(screen.getAllByRole('button', { name: /cube$/ }).filter((b) => b.getAttribute('aria-pressed') === 'true')).toEqual([])
        expect(screen.getByRole('img', { name: /^Precision|^Critical/ })).toBeInTheDocument()
        cleanup()
      }
    })
  })

  describe('setup chart', () => {
    const srow = (puzzle: string, model: string, setup: string, o: Partial<SetupMetrics> = {}): SetupMetrics => ({
      puzzle, model, setup, precision: rate(0.5, 10), hallucination: rate(0.25, 8), critical: rate(null, 0), ...o,
    })
    const setupMetrics = [
      srow('3x3', 'claude-a', 'no_model', { precision: rate(0.2, 99) }),
      srow('3x3', 'claude-a', 'descriptive', { precision: rate(0.4, 10) }),
      srow('3x3', 'claude-a', 'prescriptive', { precision: rate(0.6, 10), hallucination: rate(0.1, 4) }),
      srow('3x3', 'gpt-a', 'no_model', { precision: rate(0.6, 1), hallucination: rate(null, 0) }),
      srow('3x3', 'gpt-a', 'descriptive', { precision: rate(0.8, 10), hallucination: rate(null, 0) }),
      srow('3x3', 'gpt-a', 'prescriptive', { precision: rate(0.8, 3), hallucination: rate(null, 0) }),
      srow('4x4', 'claude-a', 'no_model', { precision: rate(0.9, 10) }),
    ]
    const both = () => render(<BenchmarkView metrics={metrics} setupMetrics={setupMetrics} attemptsUrl="/a.json" />)
    const setupChart = () => screen.getByRole('img', { name: / by setup:/ })
    const modelChart = () => screen.getByRole('img', { name: /^(Precision|Hallucination rate|Critical thinking):/ })
    const modelSection = () => screen.getByRole('region', { name: 'Metrics by AI model' })
    const setupSection = () => screen.getByRole('region', { name: 'Metrics by setup' })
    const heading = (section: HTMLElement) => section.querySelector('figcaption .chart-title')!.textContent!

    it('has no setup section without setup rows', () => {
      view()
      expect(screen.queryByRole('heading', { name: 'Metrics by setup' })).toBeNull()
      expect(screen.getAllByRole('tablist')).toHaveLength(1)
    })

    it('puts the caption after the chart in a figure named by it, and the chart keeps its own name', () => {
      both()
      const figure = within(modelSection()).getByRole('figure', { name: 'Chart 1. Balanced precision by AI model' })
      const chart = figure.querySelector('.chart')!
      const caption = figure.querySelector('figcaption')!
      expect(figure.lastElementChild).toBe(caption)
      expect(chart.compareDocumentPosition(caption) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
      expect(caption).toHaveTextContent('Chart 1. Balanced precision by AI model (?)')
      expect(within(figure).getByRole('img')).toHaveAccessibleName(/^Precision: claude-a/)
    })

    it('gives each section a subtitle, the setup one naming the three setups', () => {
      both()
      expect(screen.getByRole('heading', { level: 2, name: 'Metrics by AI model' })).toBeInTheDocument()
      expect(screen.getByRole('heading', { level: 2, name: 'Metrics by setup' })).toBeInTheDocument()
      expect(setupSection()).toHaveTextContent('no model, descriptive model, and prescriptive model')
    })

    it('numbers the chart titles 1 to 3 on the AI model tabs and 4 to 6 on the setup tabs', () => {
      both()
      const titles = (section: HTMLElement) => within(section).getAllByRole('tab').map((t) => {
        fireEvent.click(t)
        return heading(section)
      })
      expect(titles(modelSection())).toEqual([
        'Chart 1. Balanced precision by AI model',
        'Chart 2. Hallucination rate by AI model',
        'Chart 3. Critical thinking by AI model',
      ])
      expect(titles(setupSection())).toEqual([
        'Chart 4. Balanced precision by setup',
        'Chart 5. Hallucination rate by setup',
        'Chart 6. Critical thinking by setup',
      ])
    })

    const note = () => setupSection().querySelector('.chart-note')!

    it('shows the setups in order with the mean over the ticked AI models, and says how many once', () => {
      both()
      // claude-a 0.2 and gpt-a 0.6 under no model, whatever their attempt counts; both have a value under every setup.
      expect(setupChart()).toHaveAccessibleName('Precision by setup: No model 40% (worst), Descriptive model 60%, Prescriptive model 70% (best)')
      expect(note()).toHaveTextContent('Averaged over 2 AI models.')
      expect(note().textContent).not.toMatch(/left out/)
    })

    it('averages only the AI models that have a value under every setup, and says how many are left out', () => {
      both()
      fireEvent.click(within(setupSection()).getByRole('tab', { name: 'Hallucination rate' }))
      // gpt-a has no hallucination rate (a decision model, say): it is out of all three bars, so they compare the same models.
      expect(setupChart()).toHaveAccessibleName('Hallucination rate by setup: No model 25% (worst), Descriptive model 25% (worst), Prescriptive model 10% (best)')
      expect(note()).toHaveTextContent('Averaged over 1 AI model. 1 left out: no value under every setup.')
      fireEvent.click(on('claude-a'))
      expect(setupChart()).toHaveAccessibleName('Hallucination rate by setup: No model n/a, Descriptive model n/a, Prescriptive model n/a')
      expect(note()).toHaveTextContent('Averaged over 0 AI models. 1 left out: no value under every setup.')
    })

    it('shows the empty message in both charts when no AI model is selected', () => {
      both()
      fireEvent.click(on('claude-a'))
      fireEvent.click(on('gpt-a'))
      expect(within(modelSection()).getByText('No model selected.')).toBeInTheDocument()
      expect(within(setupSection()).getByText('No model selected.')).toBeInTheDocument()
      expect(screen.queryByRole('img', { name: / by setup:/ })).toBeNull()
      expect(screen.queryByRole('button', { name: 'Copy Chart 4 to clipboard' })).toBeNull()
    })

    it('follows the filter in both charts', () => {
      both()
      expect(modelChart()).toHaveAccessibleName('Precision: claude-a 50% (worst), gpt-a 100% (best)')
      fireEvent.click(on('gpt-a'))
      expect(modelChart()).toHaveAccessibleName('Precision: claude-a 50%')
      expect(setupChart()).toHaveAccessibleName('Precision by setup: No model 20% (worst), Descriptive model 40%, Prescriptive model 60% (best)')
      expect(note()).toHaveTextContent('Averaged over 1 AI model.')
      fireEvent.click(screen.getByRole('button', { name: '4x4 cube' }))
      expect(modelChart()).toHaveAccessibleName('Precision: claude-a 50%')
      // 4x4 has a row for no model only: no AI model has a value under every setup.
      expect(setupChart()).toHaveAccessibleName('Precision by setup: No model n/a, Descriptive model n/a, Prescriptive model n/a')
      expect(note()).toHaveTextContent('Averaged over 0 AI models. 1 left out')
    })

    describe('title popover', () => {
      const button = (n: number) => screen.getByRole('button', { name: `About Chart ${n}` })
      const dialog = (n: number) => document.getElementById(button(n).getAttribute('aria-controls')!)!

      it('is a button named for its chart, closed at first, controlling a dialog that exists', () => {
        both()
        expect(button(1)).toHaveTextContent('(?)')
        expect(button(1)).toHaveAttribute('aria-expanded', 'false')
        expect(dialog(1)).toHaveAttribute('role', 'dialog')
        expect(dialog(1)).toHaveAttribute('aria-label', 'About Chart 1')
        expect(dialog(1)).toHaveProperty('hidden', true)
        expect(screen.queryByRole('dialog')).toBeNull()
      })

      it('opens on a click, toggles shut on a second, and says what the chart shows and which question it answers', () => {
        both()
        fireEvent.click(button(1))
        expect(button(1)).toHaveAttribute('aria-expanded', 'true')
        expect(screen.getByRole('dialog', { name: 'About Chart 1' })).toHaveTextContent(/which AI models get the answer right/)
        fireEvent.click(button(1))
        expect(screen.queryByRole('dialog')).toBeNull()
        fireEvent.click(button(4))
        const text = screen.getByRole('dialog', { name: 'About Chart 4' }).textContent!
        expect(text).toMatch(/no model, a descriptive model, or a prescriptive model/)
        expect(text).toMatch(/does giving an AI model the rules of a puzzle change how often its answers are right/)
        expect(text).toMatch(/average over the selected AI models that have a value under every setup, each counting equally/)
      })

      it('closes on Escape, returning focus to the button, and on an outside click', () => {
        both()
        button(1).focus()
        fireEvent.click(button(1))
        fireEvent.keyDown(document, { key: 'Escape' })
        expect(screen.queryByRole('dialog')).toBeNull()
        expect(button(1)).toHaveFocus()
        // Focus elsewhere stays there.
        fireEvent.click(button(1))
        const box = screen.getByRole('checkbox', { name: 'claude-a' })
        box.focus()
        fireEvent.keyDown(document, { key: 'Escape' })
        expect(screen.queryByRole('dialog')).toBeNull()
        expect(box).toHaveFocus()
        fireEvent.click(button(1))
        fireEvent.click(document.body)
        expect(screen.queryByRole('dialog')).toBeNull()
      })

      it("stays open for a click inside it, and only one chart's opens at a time", () => {
        both()
        fireEvent.click(button(1))
        fireEvent.click(screen.getByRole('dialog'))
        expect(screen.getByRole('dialog')).toBeInTheDocument()
        fireEvent.click(button(4))
        expect(screen.getAllByRole('dialog')).toHaveLength(1)
        expect(screen.getByRole('dialog', { name: 'About Chart 4' })).toBeInTheDocument()
      })

      it('is closed by opening the metric definition in the same chart, and the other way round', () => {
        render(<BenchmarkView metrics={metrics} setupMetrics={setupMetrics} attemptsUrl="/a.json" definitions={[{ key: 'precision', name: 'Balanced precision', definition: 'd' }]} />)
        fireEvent.click(button(1))
        expect(screen.getByRole('dialog', { name: 'About Chart 1' })).toBeInTheDocument()
        fireEvent.click(screen.getByRole('button', { name: 'What is Precision?' }))
        expect(screen.queryByRole('dialog')).toBeNull()
        expect(document.getElementById('metric-popover')).not.toBeNull()
        fireEvent.click(button(1))
        expect(document.getElementById('metric-popover')).toBeNull()
        expect(screen.getByRole('dialog', { name: 'About Chart 1' })).toBeInTheDocument()
      })

      it('names the setup chart\'s "?" buttons apart from the AI model chart\'s', () => {
        render(<BenchmarkView metrics={metrics} setupMetrics={setupMetrics} attemptsUrl="/a.json" definitions={[{ key: 'precision', name: 'Balanced precision', definition: 'd' }]} />)
        expect(screen.getByRole('button', { name: 'What is Precision?' })).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'What is Precision? (by setup)' })).toBeInTheDocument()
      })

      it('gets a new number and text with the tab, and closes when the tab changes', () => {
        both()
        fireEvent.click(button(4))
        fireEvent.click(within(setupSection()).getByRole('tab', { name: 'Critical thinking' }))
        expect(screen.queryByRole('dialog')).toBeNull()
        fireEvent.click(button(6))
        expect(screen.getByRole('dialog', { name: 'About Chart 6' })).toHaveTextContent(/how well it judges whether a puzzle can be solved/)
      })
    })
  })
})
