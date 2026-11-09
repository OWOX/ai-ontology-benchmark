import { describe, expect, it } from 'vitest'
import { setupBars, type SetupMetrics } from './benchmark'

const rate = (value: number | null, n = 5) => ({ value, n })
const row = (model: string, setup: string, o: Partial<SetupMetrics> = {}): SetupMetrics => ({
  puzzle: '3x3', model, setup, precision: rate(0.5), hallucination: rate(0.2), critical: rate(0.6), ...o,
})
const pickPrecision = (r: SetupMetrics) => r.precision
const full = (model: string, p: [number, number, number], o: Partial<SetupMetrics> = {}) =>
  ['no_model', 'descriptive', 'prescriptive'].map((s, i) => row(model, s, { precision: rate(p[i]), ...o }))

describe('setupBars', () => {
  it('orders the bars no model, descriptive model, prescriptive model, with readable labels', () => {
    const { bars } = setupBars(full('a', [0.1, 0.2, 0.3]), '3x3', ['a'], pickPrecision)
    expect(bars.map((b) => b.label)).toEqual(['No model', 'Descriptive model', 'Prescriptive model'])
  })

  it('is the unweighted mean over the models, whatever their attempt counts', () => {
    const rows = [
      ...['no_model', 'descriptive', 'prescriptive'].map((s) => row('a', s, { precision: rate(0.2, 1000) })),
      ...['no_model', 'descriptive', 'prescriptive'].map((s) => row('b', s, { precision: rate(0.6, 2) })),
    ]
    const { bars, used, left } = setupBars(rows, '3x3', ['a', 'b'], pickPrecision)
    expect(bars[0].rate.value).toBeCloseTo(0.4)
    expect(bars[0].rate.n).toBe(2)
    expect([used, left]).toEqual([2, 0])
  })

  it('counts only the given models and the given puzzle', () => {
    const rows = [...full('a', [0.2, 0.2, 0.2]), ...full('b', [0.8, 0.8, 0.8]), ...full('a', [0.9, 0.9, 0.9]).map((r) => ({ ...r, puzzle: 'all' }))]
    expect(setupBars(rows, '3x3', ['a'], pickPrecision).bars[0].rate.value).toBeCloseTo(0.2)
    expect(setupBars(rows, 'all', ['a', 'b'], pickPrecision).used).toBe(1)
  })

  it('averages complete cases only, so every bar has the same models, and counts the rest as left out', () => {
    const rows = [
      ...full('a', [0.2, 0.4, 0.6]),
      // b has no value under prescriptive: it is out of all three bars, not just that one.
      row('b', 'no_model', { precision: rate(1) }), row('b', 'descriptive', { precision: rate(1) }), row('b', 'prescriptive', { precision: rate(null, 0) }),
      // c has no row at all under descriptive.
      row('c', 'no_model', { precision: rate(0) }), row('c', 'prescriptive', { precision: rate(0) }),
    ]
    const { bars, used, left } = setupBars(rows, '3x3', ['a', 'b', 'c', 'd'], pickPrecision)
    expect(bars.map((b) => b.rate.value)).toEqual([0.2, 0.4, 0.6])
    expect(bars.map((b) => b.rate.n)).toEqual([1, 1, 1])
    expect([used, left]).toEqual([1, 3])
  })

  it('leaves a model out of every bar when its value is n/a for one setup, such as a decision model hallucination, and shows n/a when none counts', () => {
    const rows = [...full('a', [0, 0, 0], { hallucination: rate(0.4) }), ...full('decision', [0, 0, 0], { hallucination: rate(null, 0) })]
    const { bars, used, left } = setupBars(rows, '3x3', ['a', 'decision'], (r) => r.hallucination)
    expect(bars.map((b) => b.rate)).toEqual([{ value: 0.4, n: 1 }, { value: 0.4, n: 1 }, { value: 0.4, n: 1 }])
    expect([used, left]).toEqual([1, 1])
    const none = setupBars(full('decision', [0, 0, 0], { hallucination: rate(null, 0) }), '3x3', ['decision'], (r) => r.hallucination)
    expect(none.bars.map((b) => b.rate)).toEqual([{ value: null, n: 0 }, { value: null, n: 0 }, { value: null, n: 0 }])
  })

  it('keeps the three setups when there are no rows, and requires an unknown setup too once the data has one', () => {
    expect(setupBars([], '3x3', ['a'], pickPrecision).bars.map((b) => b.rate.value)).toEqual([null, null, null])
    const { bars } = setupBars([...full('a', [0.1, 0.2, 0.3]), row('a', 'zeta')], '3x3', ['a'], pickPrecision)
    expect(bars.map((b) => b.setup)).toEqual(['no_model', 'descriptive', 'prescriptive', 'zeta'])
  })
})
