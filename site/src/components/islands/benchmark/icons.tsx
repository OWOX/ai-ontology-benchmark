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
