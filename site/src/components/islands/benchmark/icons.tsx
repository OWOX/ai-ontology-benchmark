import { useId, type ReactNode } from 'react'

/** Small monochrome icons for the filter's step circles. Each draws the whole circle: a disc in the current colour with the icon's strokes cut out of it, so the page shows through them. Hidden from assistive tech (the step title names the step). */
const props = { viewBox: '-8.2 -8.2 40.4 40.4', width: '1.6rem', height: '1.6rem', 'aria-hidden': true, focusable: false } as const
const stroke = { fill: 'none', stroke: '#000', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round' } as const

/** The disc (r 20.2 in the icon's 24-unit grid, i.e. 1.6rem against the icon's 0.95rem) minus the paths. */
function Knockout({ children }: { children: ReactNode }) {
  // Unique per render, so a second copy of an icon never points at another copy's mask; useId's punctuation is dropped for url(#...).
  const id = `icon-${useId().replace(/[^\w-]/g, '')}`
  return (
    <svg {...props}>
      <mask id={id} maskUnits="userSpaceOnUse" x="-8.2" y="-8.2" width="40.4" height="40.4">
        <rect x="-8.2" y="-8.2" width="40.4" height="40.4" fill="#fff" />
        <g {...stroke}>{children}</g>
      </mask>
      <circle cx="12" cy="12" r="20.2" fill="currentColor" mask={`url(#${id})`} />
    </svg>
  )
}

/** Puzzle: an isometric cube with its three faces. */
export function CubeIcon() {
  return (
    <Knockout>
      <path d="M12 2.5 20.5 7.25v9.5L12 21.5 3.5 16.75v-9.5Z" />
      <path d="M3.5 7.25 12 12l8.5-4.75M12 12v9.5" />
    </Knockout>
  )
}

/** AI provider: a four-point sparkle. */
export function SparkleIcon() {
  return (
    <Knockout>
      <path d="M12 3c.6 5 3 7.4 8 8-5 .6-7.4 3-8 8-.6-5-3-7.4-8-8 5-.6 7.4-3 8-8Z" />
    </Knockout>
  )
}

/** Experiment: a lab flask. */
export function FlaskIcon() {
  return (
    <Knockout>
      <path d="M9.5 3h5M10.5 3v6L4.8 18.6A1.6 1.6 0 0 0 6.2 21h11.6a1.6 1.6 0 0 0 1.4-2.4L13.5 9V3" />
      <path d="M7.4 15h9.2" />
    </Knockout>
  )
}

/** Model: stacked layers. */
export function LayersIcon() {
  return (
    <Knockout>
      <path d="m12 3 9 4.5-9 4.5-9-4.5Z" />
      <path d="m3 12 9 4.5 9-4.5M3 16.5 12 21l9-4.5" />
    </Knockout>
  )
}

/** Small inline icons for the Experiment block, drawn in the current colour (stroke only), hidden from assistive tech. */
const inline = { viewBox: '0 0 24 24', width: '1em', height: '1em', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, focusable: false } as const

/** Another case: a circular arrow. */
export function RefreshIcon() {
  return (
    <svg {...inline}>
      <path d="M20 12a8 8 0 1 1-2.34-5.66" />
      <path d="M20 4v4.5h-4.5" />
    </svg>
  )
}

/** Opens elsewhere: a box with an arrow out of its top-right corner. */
export function ExternalLinkIcon() {
  return (
    <svg {...inline} className="external-icon">
      <path d="M18 13.5V19a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 19V8a1.5 1.5 0 0 1 1.5-1.5H11" />
      <path d="M14.5 3.5h6v6M20.5 3.5 10.5 13.5" />
    </svg>
  )
}

/** A result that matches the expected one: a tick in a circle. */
export function CheckCircleIcon() {
  return (
    <svg {...inline} className="verdict-icon">
      <circle cx="12" cy="12" r="9" />
      <path d="m8 12.5 2.7 2.7L16.2 9.5" />
    </svg>
  )
}

/** A result that misses the expected one: a cross in a circle. */
export function CrossCircleIcon() {
  return (
    <svg {...inline} className="verdict-icon">
      <circle cx="12" cy="12" r="9" />
      <path d="m9 9 6 6M15 9l-6 6" />
    </svg>
  )
}

/** Source: the GitHub mark, filled, cut out of the disc like the other icons' strokes. */
export function GitHubIcon() {
  const id = `icon-${useId().replace(/[^\w-]/g, '')}`
  return (
    <svg {...props}>
      <mask id={id} maskUnits="userSpaceOnUse" x="-8.2" y="-8.2" width="40.4" height="40.4">
        <rect x="-8.2" y="-8.2" width="40.4" height="40.4" fill="#fff" />
        <path
          transform="translate(4.4 4.4) scale(0.95)"
          fill="#000"
          d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"
        />
      </mask>
      <circle cx="12" cy="12" r="20.2" fill="currentColor" mask={`url(#${id})`} />
    </svg>
  )
}
