import type { Rate } from '../../../lib/benchmark'

export interface BarRow { model: string; rate: Rate }
export type BarRank = 'best' | 'worst' | null

const percent = (r: Rate) => (r.value === null ? 'n/a' : `${Math.round(r.value * 100)}%`)

const shown = (r: Rate) => (r.value === null ? null : Math.round(r.value * 100))

/** Which rows are the best and which the worst by the percentage shown (two rows that both read "33%" never differ); `higherIsBetter` false flips the direction. Null rates are ignored; ties share the rank; with fewer than two non-null rows, or all equal, nothing is ranked. */
export function rankRows(rows: readonly BarRow[], higherIsBetter: boolean): BarRank[] {
  const values = rows.map((r) => shown(r.rate)).filter((v): v is number => v !== null)
  const hi = Math.max(...values)
  const lo = Math.min(...values)
  if (values.length < 2 || hi === lo) return rows.map(() => null)
  const best = higherIsBetter ? hi : lo
  const worst = higherIsBetter ? lo : hi
  return rows.map((r) => (shown(r.rate) === best ? 'best' : shown(r.rate) === worst ? 'worst' : null))
}

/** One thin horizontal bar (the metric tabs name the chart; the model and the percentage are all it shows) per model on a fixed 0 to 100% scale; a null rate has the label "n/a" and no bar. The best bar is green and the worst red (`data-rank`). Text is HTML so it keeps the page font size. */
export function BarChart({ title, rows, higherIsBetter = true }: { title: string; rows: readonly BarRow[]; higherIsBetter?: boolean }) {
  const ranks = rankRows(rows, higherIsBetter)
  return (
    <figure className="chart">
      {rows.length === 0 ? (
        <p className="empty">No model selected.</p>
      ) : (
        <div role="img" aria-label={`${title}: ${rows.map((r, i) => `${r.model} ${percent(r.rate)}${ranks[i] ? ` (${ranks[i]})` : ''}`).join(', ')}`}>
          {rows.map((r, i) => (
            <div key={r.model} className="row" data-rank={ranks[i] ?? undefined}>
              <div className="label">
                <span className="model">{r.model}</span>
                <span className="value">{percent(r.rate)}</span>
              </div>
              <div className="track">
                {r.rate.value !== null && <div className="fill" style={{ width: `${r.rate.value * 100}%` }} />}
              </div>
            </div>
          ))}
        </div>
      )}
    </figure>
  )
}
