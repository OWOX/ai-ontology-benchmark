import type { Rate } from '../../../lib/benchmark'
import { LabelHelp } from './LabelHelp'

/** `help` is the label's definition; a row without one has no "?". */
export interface BarRow { model: string; rate: Rate; help?: string }
export type BarRank = 'best' | 'worst' | null

/** The label of a value: `42%`; null is `n/a`. */
export function label(v: number | null): string {
  return v === null ? 'n/a' : `${Math.round(v * 100)}%`
}

/** The value as the label shows it, so ranking agrees with the text. */
const shown = (v: number | null) => (v === null ? null : Number(label(v).replace('%', '')))

/** Which rows are the best and which the worst by the value shown (two rows that both read "33%" never differ); `higherIsBetter` false flips the direction. Null values are ignored; ties share the rank; with fewer than two non-null rows, or all equal, nothing is ranked. */
export function rankRows(rows: readonly BarRow[], higherIsBetter: boolean): BarRank[] {
  const values = rows.map((r) => shown(r.rate.value)).filter((v): v is number => v !== null)
  const hi = Math.max(...values)
  const lo = Math.min(...values)
  if (values.length < 2 || hi === lo) return rows.map(() => null)
  const best = higherIsBetter ? hi : lo
  const worst = higherIsBetter ? lo : hi
  return rows.map((r) => {
    const v = shown(r.rate.value)
    return v === best ? 'best' : v === worst ? 'worst' : null
  })
}

/** One thin horizontal bar (the metric tabs name the chart; the model and the value are all it shows) per model. A bar runs on a fixed 0 to 100% scale. A row with a `help` definition gets a round "?" after its label, so the bars are then a labelled group instead of one image (an image's children are not exposed). A null value has the label "n/a" and no bar. The best bar is green and the worst red (`data-rank`). Text is HTML so it keeps the page font size. */
/** The bars only; the parent puts them in a `<figure>` and the caption after them. */
export function BarChart({ title, rows, higherIsBetter = true }: { title: string; rows: readonly BarRow[]; higherIsBetter?: boolean }) {
  const ranks = rankRows(rows, higherIsBetter)
  return (
    <div className="chart">
      {rows.length === 0 ? (
        <p className="empty">No model selected.</p>
      ) : (
        <div role={rows.some((r) => r.help) ? 'group' : 'img'} aria-label={`${title}: ${rows.map((r, i) => `${r.model} ${label(r.rate.value)}${ranks[i] ? ` (${ranks[i]})` : ''}`).join(', ')}`}>
          {rows.map((r, i) => (
            <div key={r.model} className="row" data-rank={ranks[i] ?? undefined}>
              <div className="label">
                <span className="model">{r.model}{r.help && <LabelHelp name={r.model} definition={r.help} />}</span>
                <span className="value">{label(r.rate.value)}</span>
              </div>
              <div className="track">
                {r.rate.value !== null && <div className="fill" style={{ width: `${r.rate.value * 100}%` }} />}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
