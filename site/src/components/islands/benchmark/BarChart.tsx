import type { Rate } from '../../../lib/benchmark'

export interface BarRow { model: string; rate: Rate }
export type BarRank = 'best' | 'worst' | null

export type BarFormat = 'percent' | 'usd'

/** The label of a value: `42%`, or `$0.0123` (two decimals from $1 up); null is `n/a`. */
export function label(v: number | null, format: BarFormat = 'percent'): string {
  if (v === null) return 'n/a'
  if (format === 'percent') return `${Math.round(v * 100)}%`
  return `$${v.toFixed(v >= 1 ? 2 : 4)}`
}

/** The value as the label shows it, so ranking agrees with the text. */
const shown = (v: number | null, format: BarFormat) => (v === null ? null : Number(label(v, format).replace(/[$%]/g, '')))

/** Which rows are the best and which the worst by the value shown (two rows that both read "33%" never differ); `higherIsBetter` false flips the direction. Null values are ignored; ties share the rank; with fewer than two non-null rows, or all equal, nothing is ranked. */
export function rankRows(rows: readonly BarRow[], higherIsBetter: boolean, format: BarFormat = 'percent'): BarRank[] {
  const values = rows.map((r) => shown(r.rate.value, format)).filter((v): v is number => v !== null)
  const hi = Math.max(...values)
  const lo = Math.min(...values)
  if (values.length < 2 || hi === lo) return rows.map(() => null)
  const best = higherIsBetter ? hi : lo
  const worst = higherIsBetter ? lo : hi
  return rows.map((r) => {
    const v = shown(r.rate.value, format)
    return v === best ? 'best' : v === worst ? 'worst' : null
  })
}

/** One thin horizontal bar (the metric tabs name the chart; the model and the value are all it shows) per model. A percentage runs on a fixed 0 to 100% scale; a cost is as wide as its share of the largest cost shown. A null value has the label "n/a" and no bar. The best bar is green and the worst red (`data-rank`). Text is HTML so it keeps the page font size. */
export function BarChart({ title, rows, higherIsBetter = true, format = 'percent' }: { title: string; rows: readonly BarRow[]; higherIsBetter?: boolean; format?: BarFormat }) {
  const ranks = rankRows(rows, higherIsBetter, format)
  const max = Math.max(...rows.map((r) => r.rate.value ?? 0))
  const width = (v: number) => (format === 'percent' ? v * 100 : max > 0 ? (v / max) * 100 : 0)
  return (
    <figure className="chart">
      {rows.length === 0 ? (
        <p className="empty">No model selected.</p>
      ) : (
        <div role="img" aria-label={`${title}: ${rows.map((r, i) => `${r.model} ${label(r.rate.value, format)}${ranks[i] ? ` (${ranks[i]})` : ''}`).join(', ')}`}>
          {rows.map((r, i) => (
            <div key={r.model} className="row" data-rank={ranks[i] ?? undefined}>
              <div className="label">
                <span className="model">{r.model}</span>
                <span className="value">{label(r.rate.value, format)}</span>
              </div>
              <div className="track">
                {r.rate.value !== null && <div className="fill" style={{ width: `${width(r.rate.value)}%` }} />}
              </div>
            </div>
          ))}
        </div>
      )}
    </figure>
  )
}
