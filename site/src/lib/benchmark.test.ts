import { describe, expect, it } from 'vitest'
import { setupBars, type SetupMetrics } from './benchmark'

const rate = (value: number | null, n = 5) => ({ value, n })
const row = (model: string, setup: string, o: Partial<SetupMetrics> = {}): SetupMetrics => ({
  puzzle: '3x3', model, setup, precision: rate(0.5), hallucination: rate(0.2), critical: rate(0.6), ...o,
})
const pickPrecision = (r: SetupMetrics) => r.precision

describe('setupBars', () => {
  it('orders the bars no model, descriptive model, prescriptive model, with readable labels', () => {
    const bars = setupBars([row('a', 'prescriptive'), row('a', 'no_model'), row('a', 'descriptive')], '3x3', ['a'], pickPrecision)
    expect(bars.map((b) => b.label)).toEqual(['No model', 'Descriptive model', 'Prescriptive model'])
  })

  it('is the unweighted mean over the models, whatever their attempt counts', () => {
    const rows = [
      row('a', 'no_model', { precision: rate(0.2, 1000) }),
      row('b', 'no_model', { precision: rate(0.6, 2) }),
    ]
    const [bar] = setupBars(rows, '3x3', ['a', 'b'], pickPrecision)
    expect(bar.rate.value).toBeCloseTo(0.4)
    expect(bar.models).toBe(2)
    expect(bar.rate.n).toBe(2)
  })

  it('counts only the given models and the given puzzle', () => {
    const rows = [
      row('a', 'no_model', { precision: rate(0.2) }),
      row('b', 'no_model', { precision: rate(0.8) }),
      row('a', 'no_model', { puzzle: 'all', precision: rate(0.9) }),
    ]
    expect(setupBars(rows, '3x3', ['a'], pickPrecision)[0].rate.value).toBeCloseTo(0.2)
    expect(setupBars(rows, 'all', ['a', 'b'], pickPrecision)[0].models).toBe(1)
  })

  it('skips a model whose value is n/a for the setup, and shows n/a when none has one', () => {
    const rows = [
      row('a', 'no_model', { hallucination: rate(0.4) }),
      row('decision', 'no_model', { hallucination: rate(null, 0) }),
      row('decision', 'descriptive', { hallucination: rate(null, 0) }),
    ]
    const bars = setupBars(rows, '3x3', ['a', 'decision'], (r) => r.hallucination)
    expect(bars[0].rate).toEqual({ value: 0.4, n: 1 })
    expect(bars[1].rate).toEqual({ value: null, n: 0 })
    expect(bars[2].models).toBe(0)
  })

  it('keeps the three setups when there are no rows, and appends an unknown setup after them', () => {
    expect(setupBars([], '3x3', ['a'], pickPrecision).map((b) => b.rate.value)).toEqual([null, null, null])
    const bars = setupBars([row('a', 'zeta')], '3x3', ['a'], pickPrecision)
    expect(bars.map((b) => b.setup)).toEqual(['no_model', 'descriptive', 'prescriptive', 'zeta'])
  })
})
