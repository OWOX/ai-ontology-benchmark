import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { PROVIDERS, puzzleSize, type ModelMetrics } from '../../../lib/benchmark'
import { cubeGeometry } from '../cube/core/geometry'
import { CubeView } from '../cube/svg/CubeView'
import { BarChart } from './BarChart'
import { Choice } from './Choice'
import { Filter, type Option } from './Filter'
import { parseHash, serializeHash } from './hash'
import { Player } from './Player'

export const PUZZLES = ['2x2', '3x3', '4x4', '5x5']

/** The solved puzzle, small and still: the puzzle option's face. Not focusable; the .preview rules switch off its pointer events. */
function Preview({ puzzle }: { puzzle: string }) {
  const g = useMemo(() => cubeGeometry(puzzleSize(puzzle)), [puzzle])
  return <CubeView geometry={g} facelets={g.SOLVED} label="" focusable={false} />
}

const METRICS = [
  { id: 'success', label: 'Success rate', higherIsBetter: true, pick: (m: ModelMetrics) => m.success },
  { id: 'hallucination', label: 'Hallucination rate', higherIsBetter: false, pick: (m: ModelMetrics) => m.hallucination },
  { id: 'detection', label: 'Critical thinking', higherIsBetter: true, pick: (m: ModelMetrics) => m.detection },
] as const

interface Props {
  /** One row per (puzzle, model), from metricsByModel. Each row also carries the model's provider. */
  metrics: ModelMetrics[]
  attemptsUrl: string
  /** Each puzzle's move group, from the engine's legal_moves() via the export. */
  legalMoves?: Readonly<Record<string, readonly string[]>>
  /** The study's definitions of the metrics (imported into Payload); a tab only gets its "?" when its metric has one. */
  definitions?: readonly MetricDefinition[]
}

/** One metric's definition, as imported from the research repo's docs/definitions.md. */
export interface MetricDefinition { key: string; name: string; definition: string }

const rank = (provider: string) => {
  const i = PROVIDERS.findIndex((p) => p.id === provider)
  return i === -1 ? PROVIDERS.length : i
}

type MetricId = (typeof METRICS)[number]['id']
interface FilterState { puzzle: string | null; providerOn: Set<string>; modelOff: Set<string>; metric: MetricId }

const sortedModels = (metrics: ModelMetrics[], puzzle: string | null) =>
  metrics.filter((m) => m.puzzle === puzzle).sort((a, b) => rank(a.provider) - rank(b.provider) || (a.model < b.model ? -1 : a.model > b.model ? 1 : 0))

/** The ticked providers that have a model for the puzzle. When providers are ticked but none of them exists here (a hash or an earlier puzzle left only absent ones), every provider of the puzzle counts instead; an empty tick set stays empty. */
const effectiveTicked = (providerOn: ReadonlySet<string>, here: readonly ModelMetrics[]) => {
  const present = new Set(here.map((m) => m.provider))
  const ticked = new Set([...providerOn].filter((id) => present.has(id)))
  return ticked.size > 0 || providerOn.size === 0 ? ticked : present
}

/** The filter as the URL hash describes it; a key that is missing, or holds nothing that exists, falls back to its default (first puzzle with data, every provider, every model, Success rate). */
function restore(hash: string, metrics: ModelMetrics[]): FilterState {
  const h = parseHash(hash)
  const withData = new Set(metrics.map((m) => m.puzzle))
  const first = PUZZLES.find((p) => withData.has(p)) ?? null
  const puzzle = h.puzzle && PUZZLES.includes(h.puzzle) && withData.has(h.puzzle) ? h.puzzle : first
  const known = new Set(metrics.map((m) => m.provider))
  const valid = h.providers?.filter((id) => known.has(id))
  const providerOn = new Set(h.providers && (h.providers.length === 0 || valid!.length > 0) ? valid : known)
  const here = sortedModels(metrics, puzzle)
  const tickedIds = effectiveTicked(providerOn, here)
  const ticked = here.filter((m) => tickedIds.has(m.provider))
  const modelOff = new Set<string>()
  if (h.models && ticked.length > 0) {
    const keep = h.models.filter((n) => ticked.some((m) => m.model === n))
    if (h.models.length === 0 || keep.length > 0) for (const m of ticked) if (!keep.includes(m.model)) modelOff.add(m.model)
  }
  const metric = METRICS.find((m) => m.id === h.metric)?.id ?? 'success'
  return { puzzle, providerOn, modelOff, metric }
}

export default function BenchmarkView({ metrics, attemptsUrl, legalMoves = {}, definitions = [] }: Props) {
  const withData = useMemo(() => new Set(metrics.map((m) => m.puzzle)), [metrics])
  const defaultPuzzle = useMemo(() => restore('', metrics).puzzle, [metrics])
  const [init] = useState(() => restore(typeof location === 'undefined' ? '' : location.hash, metrics))
  const [puzzle, setPuzzle] = useState<string | null>(init.puzzle)
  const [providerOn, setProviderOn] = useState<Set<string>>(init.providerOn)
  const [modelOff, setModelOff] = useState<Set<string>>(init.modelOff)
  const [metric, setMetric] = useState<MetricId>(init.metric)
  // The metric whose definition popover is open (one at a time).
  const [helpOpen, setHelpOpen] = useState<MetricId | null>(null)
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
      for (const m of METRICS) {
        const tab = document.getElementById(`metric-${m.id}`)
        if (!tab) continue
        const t = tab.getBoundingClientRect()
        next[m.id] = { x: t.right - r.left, y: t.bottom - r.top }
        if (m.id === openHelp) {
          tabTop = t.top
          const hb = document.getElementById(`metric-help-${m.id}`)?.getBoundingClientRect()
          helpX = hb ? hb.left + hb.width / 2 - r.left : t.right - r.left
        }
      }
      setSpots((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next))
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
    for (const m of METRICS) { const tab = document.getElementById(`metric-${m.id}`); if (tab) ro?.observe(tab) }
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
  }, [metric, openHelp, spotKey, puzzle])
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
      const help = document.getElementById(`metric-help-${openHelp}`)
      const active = document.activeElement
      // Escape closes it from anywhere; focus goes back to the "?" only when it was on the popover or on that "?" (never pulled away from a field elsewhere).
      if (active && (active === help || active.closest('.metric-popover'))) help?.focus()
      setHelpOpen(null)
    }
    const onDown = (e: Event) => {
      const t = e.target as Element | null
      if (t?.closest('.metric-popover, button.help')) return
      setHelpOpen(null)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onDown)
    }
  }, [openHelp])

  const forPuzzle = useMemo(() => sortedModels(metrics, puzzle), [metrics, puzzle])
  // A ticked provider with no model for this puzzle is not listed, so it does not count (it stays in providerOn for the puzzles that have it); when every ticked provider is absent here, all providers of this puzzle count instead.
  const providersHere = new Set(forPuzzle.map((m) => m.provider))
  const ticked = effectiveTicked(providerOn, forPuzzle)
  const showModels = ticked.size > 0
  // Only the ticked providers' models count, minus the ones switched off; with no provider ticked nothing does.
  const available = forPuzzle.filter((m) => ticked.has(m.provider))
  const selected = available.filter((m) => !modelOff.has(m.model))
  const names = selected.map((m) => m.model)

  // The hash mirrors the filter, a key only when it is not at its default, so the plain page has none. replaceState adds no history entry.
  const hash = serializeHash({
    puzzle: puzzle !== null && puzzle !== defaultPuzzle ? puzzle : undefined,
    providers: providersHere.size === 0 || ticked.size === providersHere.size ? undefined : PROVIDERS.filter((p) => ticked.has(p.id)).map((p) => p.id),
    models: showModels && selected.length < available.length ? names : undefined,
    metric: metric !== 'success' ? metric : undefined,
  })
  useEffect(() => {
    const current = location.hash || (location.href.endsWith('#') ? '#' : '')
    if (current !== hash) history.replaceState(null, '', `${location.pathname}${location.search}${hash}`)
  }, [hash])
  // The user edits the hash or follows a link to it: start over from what it says.
  useEffect(() => {
    const onHash = () => {
      // An in-page anchor (a hash with none of our keys) leaves the filter alone; an emptied hash resets it.
      if (location.hash.replace('#', '') !== '' && Object.keys(parseHash(location.hash)).length === 0) return
      const s = restore(location.hash, metrics)
      setPuzzle(s.puzzle)
      setProviderOn(s.providerOn)
      setModelOff(s.modelOff)
      setMetric(s.metric)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [metrics])

  const choosePuzzle = (id: string) => (setPuzzle(id), setModelOff(new Set()))
  const toggleProvider = (id: string, on: boolean) => {
    // Edit providerOn itself so providers this puzzle lacks stay ticked; only the fallback (all absent) starts from what is shown.
    // A toggle that leaves none of this puzzle's providers ticked is a deliberate "none": clear the absent ones too, so the click shows and the fallback does not re-tick.
    const fallback = providerOn.size > 0 && ![...providerOn].some((p) => providersHere.has(p))
    setProviderOn(() => {
      const next = new Set(fallback ? ticked : providerOn)
      on ? next.add(id) : next.delete(id)
      return [...next].some((p) => providersHere.has(p)) ? next : new Set<string>()
    })
    setModelOff(new Set())
  }
  const toggleModel = (id: string, on: boolean) =>
    setModelOff((s) => {
      const next = new Set(s)
      on ? next.delete(id) : next.add(id)
      return next
    })

  const puzzles: Option[] = PUZZLES.filter((p) => withData.has(p)).map((p) => ({ id: p, label: p, name: `${p} cube`, icon: <Preview puzzle={p} /> }))
  const providers: Option[] = PROVIDERS.filter((p) => providersHere.has(p.id)).map((p) => ({ id: p.id, label: p.label }))
  const models = available.map((m) => ({ id: m.model, label: m.model, provider: m.provider }))
  const modelOn = new Set(names)
  const current = METRICS.find((m) => m.id === metric)!

  return (
    <div className="benchmark cube-solver">
      <Filter puzzles={puzzles} puzzle={puzzle} onPuzzle={choosePuzzle} providers={providers} providerOn={ticked} onProvider={toggleProvider} models={models} modelOn={modelOn} onModel={toggleModel} showModels={showModels} />
      {puzzle === null ? (
        <p>No results yet.</p>
      ) : (
        <>
          <div className="metrics">
            <div className="tabs-row" ref={row}>
              <Choice
                role="tab"
                label="Metric"
                idPrefix="metric"
                panelId="metric-panel"
                options={METRICS.map(({ id, label }) => ({ id, label }))}
                value={metric}
                onChange={(id) => setMetric(id as MetricId)}
                reserve={(o) => !!defined(o.id)}
              />
              {METRICS.filter((m) => defined(m.id) && spots[m.id]).map((m) => (
                <button
                  key={m.id}
                  type="button"
                  className={`help${m.id === metric ? ' current' : ''}`}
                  id={`metric-help-${m.id}`}
                  style={{ left: spots[m.id].x, top: spots[m.id].y }}
                  aria-label={`What is ${m.label}?`}
                  aria-expanded={openHelp === m.id}
                  aria-controls="metric-popover"
                  aria-describedby={openHelp === m.id ? 'metric-popover' : undefined}
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
                <div className={`metric-popover${place.above ? ' above' : ''}`} id="metric-popover" role="region" aria-labelledby="metric-popover-name" ref={pop} onPointerEnter={(e) => { if (e.pointerType === 'mouse') clearLeave() }} onPointerLeave={hoverLeave}
                  style={{ ...(place.above ? { bottom: place.bottom, ['--arrow-x' as string]: `${place.arrow}px` } : { top: 'calc(100% + 0.35rem)' }) }}>
                  <p><strong id="metric-popover-name">{defined(openHelp)!.name}</strong></p>
                  <p>{defined(openHelp)!.definition}</p>
                  <p className="direction">{METRICS.find((m) => m.id === openHelp)!.higherIsBetter ? 'Higher is better.' : 'Lower is better.'}</p>
                </div>
              )}
            </div>
            <div role="tabpanel" id="metric-panel" aria-labelledby={`metric-${metric}`} tabIndex={0}>
              {showModels ? (
                <BarChart title={current.label} higherIsBetter={current.higherIsBetter} rows={selected.map((m) => ({ model: m.model, rate: current.pick(m) }))} />
              ) : (
                <p className="empty">Pick an AI provider to see results.</p>
              )}
            </div>
          </div>
          <Player key={`${puzzle}|${names.join('\u0000')}`} puzzle={puzzle} models={names} attemptsUrl={attemptsUrl} legalMoves={legalMoves} />
        </>
      )}
    </div>
  )
}
