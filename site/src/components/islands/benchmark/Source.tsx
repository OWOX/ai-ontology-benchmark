import { useId } from 'react'
import { SOURCE } from '../../../lib/benchmark'
import { GitHubIcon } from './icons'

const count = new Intl.NumberFormat('en-GB')

/** Tokens in millions with one decimal from a million up, in thousands ("k") below that, as is under a thousand. */
export function formatTokens(n: number): string {
  // Round first, then pick the unit, so 999,999 reads "1.0 million" and not "1,000k".
  const thousands = Math.round(n / 1000)
  if (thousands >= 1000) return `${(n / 1_000_000).toLocaleString('en-GB', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} million`
  if (n >= 1000) return `${count.format(thousands)}k`
  return count.format(n)
}

/** "12,345 attempts and 67.8 million tokens." */
export function usage(attempts: number, tokens: number): string {
  return `${count.format(attempts)} ${attempts === 1 ? 'attempt' : 'attempts'} and ${formatTokens(tokens)} ${tokens === 1 ? 'token' : 'tokens'}.`
}

interface Props {
  /** The attempts and tokens behind the data shown; the note leads with them when given. */
  shown?: { attempts: number; tokens: number }
}

/** Where the numbers come from: the study's repository, in the look of the other sections (a step title with an icon disc, its body under the title text). */
export function Source({ shown }: Props) {
  const titleId = useId()
  return (
    <section className="steps source" aria-labelledby={titleId}>
      <div className="current">
        <div className="title">
          <span className="num" aria-hidden="true"><GitHubIcon /></span>
          <span className="label" id={titleId}>Source</span>
        </div>
        <div className="body">
          <p><a className="repo" href={SOURCE} target="_blank" rel="noopener noreferrer">{SOURCE.replace('https://', '')}<span className="sr-only"> (opens in a new tab)</span></a></p>
          <p>{shown ? `${usage(shown.attempts, shown.tokens)} ` : ''}The repository holds the experiment design (methodology and definitions), the frozen releases with their inputs and prompts, every AI model's raw answers, and the code that scores them. Every number on this page is recomputed from those raw answers.</p>
        </div>
      </div>
    </section>
  )
}
