import { useId } from 'react'
import { SOURCE } from '../../../lib/benchmark'
import { GitHubIcon } from './icons'

/** Where the numbers come from: the study's repository, in the look of the other sections (a step title with an icon disc, its body under the title text). */
export function Source() {
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
          <p>The repository holds the experiment design (methodology and definitions), the frozen releases with their inputs and prompts, every AI model's raw answers, and the code that scores them. Every number on this page is recomputed from those raw answers.</p>
        </div>
      </div>
    </section>
  )
}
