import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ModelMetrics, SetupMetrics } from '../../../lib/benchmark'
import BenchmarkView from './BenchmarkView'
import { chartText } from './copyChart'

const rate = (value: number | null, n = 5) => ({ value, n })
const row = (puzzle: string, model: string, provider: string, o: Partial<ModelMetrics> = {}): ModelMetrics => ({
  puzzle, model, provider, attempts: 10, tokens: 1000, precision: rate(0.5), hallucination: rate(0.25), critical: rate(null, 0), ...o,
})
const metrics = [row('3x3', 'claude-a', 'anthropic'), row('3x3', 'gpt-a', 'openai', { precision: rate(1) })]
const srow = (model: string, setup: string, precision: number): SetupMetrics => ({
  puzzle: '3x3', model, setup, precision: rate(precision), hallucination: rate(0.1), critical: rate(null, 0),
})
const setupMetrics = [srow('claude-a', 'no_model', 0.2), srow('claude-a', 'descriptive', 0.4), srow('claude-a', 'prescriptive', 0.6)]

const view = () => render(<BenchmarkView metrics={metrics} setupMetrics={setupMetrics} attemptsUrl="/a.json" />)

let items: { init: Record<string, unknown> }[]
let write: ReturnType<typeof vi.fn>
let writeText: ReturnType<typeof vi.fn>
const blob = new Blob(['png'], { type: 'image/png' })
let drawn: Record<string, unknown>[]

function stubCanvas() {
  const ctx = new Proxy({ measureText: () => ({ width: 10 }) } as Record<string, unknown>, {
    get: (t, k) => (k in t ? t[k as string] : () => undefined),
    set: () => true,
  })
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(((kind: string) => { drawn.push({ kind }); return ctx }) as never)
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function (this: HTMLCanvasElement, cb: BlobCallback) { drawn.push({ w: this.width, h: this.height }); cb(blob) })
}

beforeEach(() => {
  history.replaceState(null, '', '/')
  items = []
  drawn = []
  write = vi.fn().mockResolvedValue(undefined)
  writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { value: { write, writeText }, configurable: true })
  vi.stubGlobal('ClipboardItem', class { init: Record<string, unknown>; constructor(init: Record<string, unknown>) { this.init = init; items.push(this) } })
  stubCanvas()
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

const copyBtn = (n: number) => screen.getByRole('button', { name: `Copy Chart ${n} to clipboard` })
const click = async (el: HTMLElement) => { await act(async () => { fireEvent.click(el) }) }

describe('copy chart', () => {
  it('has a copy button with a label and a title on every chart, after the caption and the (?)', () => {
    view()
    for (const [section, first] of [['Metrics by AI model', 1], ['Metrics by setup', 4]] as const) {
      const sec = screen.getByRole('region', { name: section })
      for (const [i, tab] of within(sec).getAllByRole('tab').entries()) {
        fireEvent.click(tab)
        const b = within(sec).getByRole('button', { name: `Copy Chart ${first + i} to clipboard` })
        expect(b).toHaveAttribute('title', 'Copy chart')
        const caption = b.closest('figcaption')!
        expect([...caption.querySelectorAll('.chart-title, button')].map((e) => e.getAttribute('aria-label') ?? e.className)).toEqual(['chart-title', `About Chart ${first + i}`, `Copy Chart ${first + i} to clipboard`])
      }
    }
  })

  it('writes one item with a PNG and the exact text', async () => {
    view()
    await click(copyBtn(1))
    expect(write).toHaveBeenCalledTimes(1)
    const [list] = write.mock.calls[0]
    expect(list).toHaveLength(1)
    const init = (list[0] as { init: Record<string, unknown> }).init
    expect(Object.keys(init).sort()).toEqual(['image/png', 'text/plain'])
    expect(await init['image/png']).toBe(blob)
    expect(await (init['text/plain'] as Blob).text()).toBe('Chart 1. Balanced precision by AI model\nclaude-a: 50%\ngpt-a: 100%')
    expect(drawn).toContainEqual({ kind: '2d' })
    expect(drawn.some((d) => d.w === 1280 && typeof d.h === 'number')).toBe(true)
  })

  it('copies the setup chart as it is shown, and the text without the AI model count', async () => {
    view()
    await click(copyBtn(4))
    const init = (write.mock.calls[0][0][0] as { init: Record<string, unknown> }).init
    expect(await (init['text/plain'] as Blob).text()).toBe('Chart 4. Balanced precision by setup\nNo model: 20%\nDescriptive model: 40%\nPrescriptive model: 60%')
  })

  it('formats text as the caption then one label: value line per bar, n/a for no value', () => {
    expect(chartText({ caption: 'Chart 9. X', rows: [{ model: 'a', rate: rate(0.333) }, { model: 'b', rate: rate(null, 0) }] })).toBe('Chart 9. X\na: 33%\nb: n/a')
  })

  it('falls back to writeText without ClipboardItem', async () => {
    vi.stubGlobal('ClipboardItem', undefined)
    view()
    await click(copyBtn(1))
    expect(write).not.toHaveBeenCalled()
    expect(writeText).toHaveBeenCalledWith('Chart 1. Balanced precision by AI model\nclaude-a: 50%\ngpt-a: 100%')
    expect(screen.getAllByRole('status').some((s) => s.textContent === 'Copied')).toBe(true)
  })

  it('falls back to the text when the image write fails', async () => {
    write.mockRejectedValue(new Error('denied'))
    view()
    await click(copyBtn(1))
    expect(writeText).toHaveBeenCalledTimes(1)
    expect(screen.getAllByRole('status').some((s) => s.textContent === 'Copied')).toBe(true)
  })

  it('shows a check for 1.5 s and announces Copied, then goes back', async () => {
    view()
    vi.useFakeTimers()
    const b = copyBtn(1)
    const before = b.innerHTML
    await click(b)
    expect(b.innerHTML).not.toBe(before)
    expect(b.querySelector('path')!.getAttribute('d')).toMatch(/^M5 12\.5/)
    const live = b.closest('figcaption')!.querySelector('[role="status"]')!
    expect(live).toHaveAttribute('aria-live', 'polite')
    expect(live).toHaveTextContent('Copied')
    await act(async () => { vi.advanceTimersByTime(1400) })
    expect(live).toHaveTextContent('Copied')
    await act(async () => { vi.advanceTimersByTime(200) })
    expect(live).toHaveTextContent('')
    expect(b.innerHTML).toBe(before)
  })

  it('announces Copy failed when nothing can be written', async () => {
    write.mockRejectedValue(new Error('denied'))
    writeText.mockRejectedValue(new Error('denied'))
    view()
    await click(copyBtn(1))
    await waitFor(() => expect(copyBtn(1).closest('figcaption')!.querySelector('[role="status"]')).toHaveTextContent('Copy failed'))
    expect(copyBtn(1).closest('figcaption')!.querySelector('.copy-status')).toHaveClass('failed')
  })
})
