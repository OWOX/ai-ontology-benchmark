import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { BarChart, label, rankRows } from './BarChart'

afterEach(cleanup)
const r = (model: string, value: number | null) => ({ model, rate: { value, n: 5 } })

describe('rankRows', () => {
  it('higher is better: the top value is best, the bottom worst', () => {
    expect(rankRows([r('a', 0.2), r('b', 0.9), r('c', 0.5)], true)).toEqual(['worst', 'best', null])
  })
  it('lower is better flips it', () => {
    expect(rankRows([r('a', 0.2), r('b', 0.9), r('c', 0.5)], false)).toEqual(['best', 'worst', null])
  })
  it('ignores null rates', () => {
    expect(rankRows([r('a', null), r('b', 0.9), r('c', 0.5)], true)).toEqual([null, 'best', 'worst'])
  })
  it('ties share the rank', () => {
    expect(rankRows([r('a', 1), r('b', 1), r('c', 0.5), r('d', 0), r('e', 0)], true)).toEqual(['best', 'best', null, 'worst', 'worst'])
  })
  it('ranks on the shown percentage', () => {
    expect(rankRows([r('a', 0.333), r('b', 0.334), r('c', 0.9)], true)).toEqual(['worst', 'worst', 'best'])
    expect(rankRows([r('a', 0.331), r('b', 0.334)], true)).toEqual([null, null])
  })
  it('ranks nothing with fewer than two values or all equal', () => {
    expect(rankRows([r('a', 0.5)], true)).toEqual([null])
    expect(rankRows([r('a', 0.5), r('b', null)], true)).toEqual([null, null])
    expect(rankRows([r('a', 0.5), r('b', 0.5)], true)).toEqual([null, null])
    expect(rankRows([], true)).toEqual([])
  })
})

describe('BarChart', () => {
  it('exposes the rank on the row and in the label', () => {
    const { container, getByRole } = render(<BarChart title="T" higherIsBetter={false} rows={[r('a', 0.1), r('b', 0.4)]} />)
    expect([...container.querySelectorAll('.row')].map((e) => e.getAttribute('data-rank'))).toEqual(['best', 'worst'])
    expect(getByRole('img')).toHaveAccessibleName('T: a 10% (best), b 40% (worst)')
  })
})

describe('percent format', () => {
  it('labels whole percentages, and n/a for null', () => {
    expect(label(0.333)).toBe('33%')
    expect(label(null)).toBe('n/a')
  })
  it('keeps bars on the fixed 0 to 100 scale, none for null', () => {
    const { container } = render(<BarChart title="P" rows={[r('a', 0.2), r('b', 0.4), r('c', null)]} />)
    expect([...container.querySelectorAll<HTMLElement>('.fill')].map((f) => f.style.width)).toEqual(['20%', '40%'])
    expect([...container.querySelectorAll('.value')].map((e) => e.textContent)).toEqual(['20%', '40%', 'n/a'])
  })
})

describe('BarChart detail', () => {
  it('shows a row\'s detail after its label and in the accessible name', () => {
    const { container } = render(<BarChart title="Precision" rows={[{ ...r('No model', 0.4), detail: '2 models' }, r('Other', 0.8)]} />)
    expect(container.querySelector('.row .detail')).toHaveTextContent('(2 models)')
    expect(container.querySelectorAll('.detail')).toHaveLength(1)
    expect(container.querySelector('[role="img"]')).toHaveAccessibleName('Precision: No model 40% (2 models) (worst), Other 80% (best)')
  })
})
