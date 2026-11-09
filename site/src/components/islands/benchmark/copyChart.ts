// Copies the chart on show to the clipboard: a PNG drawn on a canvas from the chart's data (not a screenshot of the page), and the same data as text.
import { label as percent, rankRows, type BarRow } from './BarChart'

export interface ChartCopy {
  /** "Chart N. <label>" */
  caption: string
  rows: readonly BarRow[]
  higherIsBetter: boolean
  /** The filter in words, e.g. "All puzzles, 4 AI models". */
  filter: string
  /** An extra line of small text, e.g. how many AI models the bars average. */
  note?: string
  url: string
}

/** The caption, one "label: value" line per bar, then the filter line and the note, as under the image. */
export function chartText({ caption, rows, filter, note }: Pick<ChartCopy, 'caption' | 'rows' | 'filter' | 'note'>): string {
  return [caption, ...rows.map((r) => `${r.model}: ${percent(r.rate.value)}`), filter, ...(note ? [note] : [])].join('\n')
}

// The light theme's colours (site/src/styles/global.css), on white, whatever theme the page is in.
const INK = '#1a1f2e'
const MUTED = '#5e6b85'
const RULE = '#e2e8f1'
const OK = '#14713c'
const DANGER = '#c60e0e'
const SANS = 'Roboto, system-ui, -apple-system, "Segoe UI", sans-serif'
const MONO = 'ui-monospace, Menlo, Consolas, monospace'

const WIDTH = 640
const PAD = 24
const SCALE = 2
const ROW = 44

/** The text cut with an ellipsis so it is at most `max` wide in the context's current font. */
export function ellipsize(ctx: Pick<CanvasRenderingContext2D, 'measureText'>, text: string, max: number): string {
  if (ctx.measureText(text).width <= max) return text
  let end = text.length
  while (end > 0 && ctx.measureText(`${text.slice(0, end).trimEnd()}…`).width > max) end--
  return `${text.slice(0, end).trimEnd()}…`
}

/** The chart as a PNG at 2x: the bars with their labels and values, then the caption, then the filter and the page URL in small text. */
export function drawChart(c: ChartCopy): Promise<Blob> {
  const lines = c.note ? 3 : 2
  const height = PAD + c.rows.length * ROW + 34 + lines * 18 + PAD - 6
  const canvas = document.createElement('canvas')
  canvas.width = WIDTH * SCALE
  canvas.height = height * SCALE
  const ctx = canvas.getContext('2d')
  if (!ctx) return Promise.reject(new Error('no canvas'))
  ctx.scale(SCALE, SCALE)
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, WIDTH, height)
  const ranks = rankRows(c.rows, c.higherIsBetter)
  const inner = WIDTH - 2 * PAD
  ctx.textBaseline = 'alphabetic'
  c.rows.forEach((r, i) => {
    const y = PAD + i * ROW
    const colour = ranks[i] === 'best' ? OK : ranks[i] === 'worst' ? DANGER : null
    // The value first (it sits at the right), then the label in what is left of the row, a 12px gap short of it.
    const value = percent(r.rate.value)
    ctx.font = `15px ${MONO}`
    const valueWidth = ctx.measureText(value).width
    ctx.textAlign = 'right'
    ctx.fillStyle = colour ?? MUTED
    ctx.fillText(value, WIDTH - PAD, y + 16)
    ctx.font = `16px ${SANS}`
    ctx.textAlign = 'left'
    ctx.fillStyle = INK
    ctx.fillText(ellipsize(ctx, r.model, inner - valueWidth - 12), PAD, y + 16)
    ctx.fillStyle = RULE
    ctx.fillRect(PAD, y + 24, inner, 6)
    if (r.rate.value !== null) {
      ctx.fillStyle = colour ?? INK
      ctx.fillRect(PAD, y + 24, inner * r.rate.value, 6)
    }
  })
  const base = PAD + c.rows.length * ROW + 14
  ctx.textAlign = 'left'
  ctx.fillStyle = INK
  ctx.font = `italic 500 16px ${SANS}`
  ctx.fillText(ellipsize(ctx, c.caption, inner), PAD, base)
  ctx.fillStyle = MUTED
  ctx.font = `12px ${SANS}`
  ctx.fillText(ellipsize(ctx, c.filter, inner), PAD, base + 24)
  if (c.note) ctx.fillText(ellipsize(ctx, c.note, inner), PAD, base + 42)
  ctx.fillText(ellipsize(ctx, c.url, inner), PAD, base + (c.note ? 60 : 42))
  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('no image'))), 'image/png'))
}

/** Writes one ClipboardItem with the PNG and the text; without image support, or when the image write fails, only the text. Rejects when nothing could be written. */
export async function copyChart(c: ChartCopy): Promise<void> {
  const text = chartText(c)
  const clip = navigator.clipboard
  if (typeof ClipboardItem !== 'undefined' && clip?.write) {
    try {
      // The image is a promise so the write starts inside the click (Safari asks for that).
      await clip.write([new ClipboardItem({ 'image/png': drawChart(c), 'text/plain': new Blob([text], { type: 'text/plain' }) })])
      return
    } catch {
      /* fall back to the text */
    }
  }
  await clip.writeText(text)
}
