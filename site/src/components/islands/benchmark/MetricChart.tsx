import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Choice } from './Choice'

/** One metric tab of a chart: `title` names the metric in the chart title ("Chart 1. <title> by AI model"), `explanation` is the title's "(?)" text. */
export interface ChartTab { id: string; label: string; title: string; higherIsBetter: boolean; explanation: string }

/** One metric's definition, as imported from the research repo's docs/definitions.md. */
export interface MetricDefinition { key: string; name: string; definition: string }

interface Props {
  /** Prefix of the element ids (`<prefix>-<tab id>`, `<prefix>-panel`, `<prefix>-popover`), so two charts on a page never share one. */
  idPrefix: string
  /** The section's subtitle and the plain sentence under it. */
  heading: string
  intro: string
  /** What the bars compare, for the chart title: "AI model" or "setup". */
  by: string
  /** The number of the first tab's chart; the next tabs follow. */
  firstNumber: number
  tabs: readonly ChartTab[]
  metric: string
  onMetric: (id: string) => void
  /** The study's definitions of the metrics; a tab only gets its "?" when its metric has one. */
  definitions: readonly MetricDefinition[]
  /** Anything that moves the tabs (the puzzle), so the "?" buttons are measured again. */
  layoutKey: string
  /** The chart of the selected metric. */
  children: ReactNode
}

/** A chart section: a subtitle, the metric tabs hanging off a framed panel, and in the panel a figure: the chart, then its numbered caption ending in a "(?)" popover. Each tab keeps its own "?" for the metric's definition. */
export function MetricChart({ idPrefix, heading, intro, by, firstNumber, tabs, metric, onMetric, definitions, layoutKey, children }: Props) {
  const headingId = useId()
  const root = useRef<HTMLElement>(null)
  // The metric whose definition popover is open (one at a time).
  const [helpOpen, setHelpOpen] = useState<string | null>(null)
  const defined = (id: string) => definitions.find((d) => d.key === id && d.definition.trim() !== '')
  const openHelp = helpOpen && defined(helpOpen) ? helpOpen : null
  // The "?" buttons live in a layer beside the tablist (the tablist holds only tabs); each is laid over its tab's reserved right end from the tab's measured box, and the popover is inset to the chart panel's text.
  const row = useRef<HTMLDivElement>(null)
  const pop = useRef<HTMLDivElement>(null)
  const [spots, setSpots] = useState<Record<string, { x: number; y: number }>>({})
  // Where the open popover goes: as wide as the chart panel's text (inset by the panel's border and padding); above the tab by default or below when the viewport has no room above, and the arrow's x.
  const [place, setPlace] = useState({ above: true, bottom: 0, arrow: 0 })
  // Hover opens it for a mouse only; pinned = opened by click/tap (or clicked while hover-opened), so leaving does not close it.
  const pinned = useRef(false)
  const byFocus = useRef(false)
  const leaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const clearLeave = () => { if (leaveTimer.current) clearTimeout(leaveTimer.current); leaveTimer.current = null }
  useEffect(() => clearLeave, [])
  const spotKey = definitions.map((d) => d.key).join('|')
  useLayoutEffect(() => {
    const el = row.current
    if (!el) return
    const measure = () => {
      const r = el.getBoundingClientRect()
      const next: Record<string, { x: number; y: number }> = {}
      let tabTop = 0
      let helpX = 0
      const l = el.querySelector('[role="tablist"]')?.getBoundingClientRect()
      for (const m of tabs) {
        const tab = document.getElementById(`${idPrefix}-${m.id}`)
        if (!tab) continue
        const t = tab.getBoundingClientRect()
        // A tab scrolled out of the tablist takes its "?" with it.
        if (l && (t.right > l.right + 0.5 || t.right < l.left - 0.5)) continue
        next[m.id] = { x: t.right - r.left, y: t.bottom - r.top }
        if (m.id === openHelp) {
          tabTop = t.top
          const hb = document.getElementById(`${idPrefix}-help-${m.id}`)?.getBoundingClientRect()
          helpX = hb ? hb.left + hb.width / 2 - r.left : t.right - r.left
        }
      }
      setSpots((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next))
      // The open popover's tab scrolled out of the tablist: its "?" is gone, so the popover goes too.
      if (openHelp && !next[openHelp]) setHelpOpen(null)
      const w = pop.current?.offsetWidth ?? 0
      const h = pop.current?.offsetHeight ?? 0
      const gap = 6.4
      // Room above counts from the bottom of the sticky site header, which covers the top of the viewport.
      const headerBottom = document.querySelector('.site-header')?.getBoundingClientRect().bottom ?? 0
      const above = !openHelp || tabTop - gap - 6 - Math.max(0, headerBottom) >= h
      const bottom = r.height - (tabTop - r.top) + gap
      // The arrow's x inside the popover, which is inset from the row by the panel's border and padding.
      const arrow = Math.max(10, Math.min(helpX - (pop.current?.offsetLeft ?? 0), w - 10))
      setPlace((prev) => (prev.above === above && prev.bottom === bottom && prev.arrow === arrow ? prev : { above, bottom, arrow }))
    }
    measure()
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    ro?.observe(el)
    for (const m of tabs) { const tab = document.getElementById(`${idPrefix}-${m.id}`); if (tab) ro?.observe(tab) }
    const list = el.querySelector('[role="tablist"]')
    list?.addEventListener('scroll', measure)
    if (openHelp) window.addEventListener('scroll', measure, { passive: true })
    let cancelled = false
    document.fonts?.ready.then(() => { if (!cancelled) measure() })
    return () => {
      cancelled = true
      list?.removeEventListener('scroll', measure)
      window.removeEventListener('scroll', measure)
      ro?.disconnect()
    }
  }, [metric, openHelp, spotKey, layoutKey])
  // Selecting a tab brings it fully into the tablist (only the tablist scrolls, never the page), so its "?" shows.
  useEffect(() => {
    const tab = document.getElementById(`${idPrefix}-${metric}`)
    const list = tab?.closest('[role="tablist"]') as HTMLElement | null | undefined
    if (!tab || !list) return
    const t = tab.getBoundingClientRect()
    const l = list.getBoundingClientRect()
    if (t.right > l.right) list.scrollLeft += t.right - l.right
    else if (t.left < l.left) list.scrollLeft -= l.left - t.left
  }, [metric])
  // After a mouse leaves the "?" or the box it closes once the grace delay passes, unless it was pinned by a click or the pointer came back.
  const hoverLeave = (e: { pointerType: string }) => {
    if (e.pointerType !== 'mouse' || pinned.current) return
    clearLeave()
    leaveTimer.current = setTimeout(() => setHelpOpen(null), 150)
  }
  useEffect(() => {
    if (!openHelp) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      const help = document.getElementById(`${idPrefix}-help-${openHelp}`)
      const active = document.activeElement
      // Escape closes it from anywhere; focus goes back to the "?" only when it was on the popover or on that "?" (never pulled away from a field elsewhere).
      if (active && (active === help || active.closest('.metric-popover'))) help?.focus()
      setHelpOpen(null)
    }
    const onDown = (e: Event) => {
      const t = e.target as Element | null
      if (t && root.current?.contains(t) && t.closest('.metric-popover, button.help')) return
      setHelpOpen(null)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onDown)
    }
  }, [openHelp])


  // The title's "(?)" popover, the Player's pattern: a text button with aria-controls, a dialog always in the DOM (hidden while closed), closing on an outside click and on Escape.
  const [titleOpen, setTitleOpen] = useState(false)
  const head = useRef<HTMLDivElement>(null)
  const popId = useId()
  const captionId = useId()
  // The popover opens upwards over the chart, the caption being under it, or below the caption when the viewport has no room above (under the sticky header).
  const [up, setUp] = useState(true)
  useLayoutEffect(() => {
    if (!titleOpen) return
    const h = head.current?.getBoundingClientRect()
    const popH = head.current?.querySelector<HTMLElement>('.pop')?.offsetHeight ?? 0
    if (!h) return
    const headerBottom = document.querySelector('.site-header')?.getBoundingClientRect().bottom ?? 0
    setUp(h.top - Math.max(0, headerBottom) - 8 >= popH)
  }, [titleOpen, metric])
  useEffect(() => setTitleOpen(false), [metric])
  useEffect(() => {
    if (!titleOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setTitleOpen(false)
      head.current?.querySelector<HTMLElement>('button.pop-btn')?.focus()
    }
    // The click is not stopped, so the control under the pointer still does its job.
    const onClick = (e: Event) => {
      if (!head.current?.contains(e.target as Node | null)) setTitleOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('click', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('click', onClick)
    }
  }, [titleOpen])

  const at = tabs.findIndex((t) => t.id === metric)
  const current = tabs[at === -1 ? 0 : at]
  const number = firstNumber + (at === -1 ? 0 : at)
  const title = `Chart ${number}. ${current.title} by ${by}`

  return (
    <section className="chart-section" aria-labelledby={headingId} ref={root}>
      <h2 className="subtitle" id={headingId}>{heading}</h2>
      <p className="lead">{intro}</p>
      <div className="metrics">
        <div className="tabs-row" ref={row}>
          <Choice
            role="tab"
            label={by === 'AI model' ? 'Metric' : `Metric by ${by}`}
            idPrefix={idPrefix}
            panelId={`${idPrefix}-panel`}
            options={tabs.map(({ id, label }) => ({ id, label }))}
            value={metric}
            onChange={onMetric}
            reserve={(o) => !!defined(o.id)}
          />
          {tabs.filter((m) => defined(m.id) && spots[m.id]).map((m) => (
            <button
              key={m.id}
              type="button"
              className={`help${m.id === metric ? ' current' : ''}`}
              id={`${idPrefix}-help-${m.id}`}
              style={{ left: spots[m.id].x, top: spots[m.id].y }}
              aria-label={`What is ${m.label}?`}
              aria-expanded={openHelp === m.id}
              aria-controls={`${idPrefix}-popover`}
              aria-describedby={openHelp === m.id ? `${idPrefix}-popover` : undefined}
              onClick={() => {
                clearLeave()
                byFocus.current = false
                // Clicking a "?" the hover just opened keeps it open (pinned); otherwise a click toggles.
                if (openHelp === m.id && !pinned.current) pinned.current = true
                else {
                  pinned.current = openHelp !== m.id
                  setHelpOpen(openHelp === m.id ? null : m.id)
                }
              }}
              onPointerEnter={(e) => {
                if (e.pointerType !== 'mouse') return
                clearLeave()
                if (openHelp !== m.id) { pinned.current = false; byFocus.current = false; setHelpOpen(m.id) }
              }}
              onPointerLeave={hoverLeave}
              onFocus={(e) => {
                let visible = false
                try { visible = e.currentTarget.matches(':focus-visible') } catch { /* no :focus-visible */ }
                if (visible && openHelp !== m.id) { pinned.current = true; byFocus.current = true; setHelpOpen(m.id) }
              }}
              onBlur={(e) => {
                if (byFocus.current && (!e.relatedTarget || !(e.relatedTarget as Element).closest('.metric-popover'))) setHelpOpen((cur) => (cur === m.id ? null : cur))
              }}
            >
              ?
            </button>
          ))}
          {openHelp && (
            <div className={`metric-popover${place.above ? ' above' : ''}`} id={`${idPrefix}-popover`} role="region" aria-labelledby={`${idPrefix}-popover-name`} ref={pop} onPointerEnter={(e) => { if (e.pointerType === 'mouse') clearLeave() }} onPointerLeave={hoverLeave}
              style={{ ...(place.above ? { bottom: place.bottom, ['--arrow-x' as string]: `${place.arrow}px` } : { top: 'calc(100% + 0.35rem)' }) }}>
              <p><strong id={`${idPrefix}-popover-name`}>{defined(openHelp)!.name}</strong></p>
              <p>{defined(openHelp)!.definition}</p>
              <p className="direction">{tabs.find((m) => m.id === openHelp)!.higherIsBetter ? 'Higher is better.' : 'Lower is better.'}</p>
            </div>
          )}
        </div>
        <div role="tabpanel" id={`${idPrefix}-panel`} aria-labelledby={`${idPrefix}-${metric}`} tabIndex={0}>
          <figure className="chart-figure" aria-labelledby={captionId}>
            {children}
            <figcaption className="chart-head" ref={head}>
              <span className="chart-title" id={captionId}>{title}</span>{' '}
              <span className="pop-wrap">
                <button type="button" className="pop-btn" aria-label={`About Chart ${number}`} aria-expanded={titleOpen} aria-controls={popId} onClick={() => setTitleOpen(!titleOpen)}>(?)</button>
              </span>
              {/* Always in the DOM (hidden while closed), so the button's aria-controls points at an element that exists. */}
              <div className={`pop pop-wrap${up ? '' : ' below'}`} id={popId} role="dialog" aria-label={`About Chart ${number}`} hidden={!titleOpen}>
                <p>{current.explanation}</p>
              </div>
            </figcaption>
          </figure>
        </div>
      </div>
    </section>
  )
}
