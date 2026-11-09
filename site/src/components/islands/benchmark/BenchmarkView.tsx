import { useEffect, useMemo, useState } from 'react'
import { ALL, PROVIDERS, puzzleSize, setupBars, type ModelMetrics, type SetupMetrics } from '../../../lib/benchmark'
import { cubeGeometry } from '../cube/core/geometry'
import { CubeView } from '../cube/svg/CubeView'
import { BarChart } from './BarChart'
import { Filter, type Option } from './Filter'
import { parseHash, serializeHash } from './hash'
import { MetricChart, type ChartTab, type MetricDefinition } from './MetricChart'
import { Player } from './Player'
import { Source } from './Source'

export const PUZZLES = ['2x2', '3x3', '4x4', '5x5']

/** The solved puzzle, small and still: the puzzle option's face. Not focusable; the .preview rules switch off its pointer events. */
function Preview({ puzzle }: { puzzle: string }) {
  const g = useMemo(() => cubeGeometry(puzzleSize(puzzle)), [puzzle])
  return <CubeView geometry={g} facelets={g.SOLVED} label="" focusable={false} />
}

const METRICS = [
  { id: 'precision', label: 'Precision', title: 'Balanced precision', higherIsBetter: true, pick: (m: ModelMetrics) => m.precision, setupPick: (m: SetupMetrics) => m.precision },
  { id: 'hallucination', label: 'Hallucination rate', title: 'Hallucination rate', higherIsBetter: false, pick: (m: ModelMetrics) => m.hallucination, setupPick: (m: SetupMetrics) => m.hallucination },
  { id: 'critical', label: 'Critical thinking', title: 'Critical thinking', higherIsBetter: true, pick: (m: ModelMetrics) => m.critical, setupPick: (m: SetupMetrics) => m.critical },
] as const

const SETUP_QUESTION = 'does giving an AI model the rules of a puzzle change'
const AVERAGE = 'Each bar is the average over the selected AI models that have a value under every setup, each counting equally'

/** The tabs of Charts 1 to 3, which compare AI models. The "(?)" text says what the chart shows and which question it answers (docs/methodology.md, "The question"). */
export const MODEL_TABS: readonly ChartTab[] = [
  { ...METRICS[0], explanation: "Shows how often each AI model's answer is right, as the mean of its precision on solvable and on unsolvable puzzles. It answers which AI models get the answer right." },
  { ...METRICS[1], explanation: "Shows how often each AI model gives a move that doesn't exist for the puzzle, among the answers that give moves. It answers which AI models hallucinate." },
  { ...METRICS[2], explanation: 'Shows how well each AI model judges whether a puzzle can be solved at all, by naming the defect in an unsolvable puzzle without claiming one in a solvable puzzle. It answers which AI models spot an impossible puzzle.' },
]

/** The tabs of Charts 4 to 6, which compare setups. */
export const SETUP_TABS: readonly ChartTab[] = [
  { ...METRICS[0], explanation: `Shows how often answers are right when the prompt gives no model, a descriptive model, or a prescriptive model of the puzzle's rules. It addresses the research question: ${SETUP_QUESTION} how often its answers are right? ${AVERAGE}.` },
  { ...METRICS[1], explanation: `Shows how often answers contain a move that doesn't exist for the puzzle under each setup. It addresses the research question: ${SETUP_QUESTION} how often it hallucinates? ${AVERAGE} A model with no value, such as a decision model, is skipped.` },
  { ...METRICS[2], explanation: `Shows how well answers judge whether a puzzle can be solved at all under each setup. It addresses the research question: ${SETUP_QUESTION} how well it judges whether a puzzle can be solved? ${AVERAGE}.` },
]

interface Props {
  /** One row per (puzzle, model), from metricsByModel. Each row also carries the model's provider. */
  metrics: ModelMetrics[]
  attemptsUrl: string
  /** Each puzzle's move group, from the engine's legal_moves() via the export. */
  legalMoves?: Readonly<Record<string, readonly string[]>>
  /** One row per (puzzle, model, setup), from setupMetrics; without any, the setup chart is not shown. */
  setupMetrics?: SetupMetrics[]
  /** The study's definitions of the metrics (imported into Payload); a tab only gets its "?" when its metric has one. */
  definitions?: readonly MetricDefinition[]
}

export type { MetricDefinition }

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

/** The filter as the URL hash describes it; a key that is missing, or holds nothing that exists, falls back to its default (no puzzle selected, which pools all of them, every provider, every model, Precision). */
function restore(hash: string, metrics: ModelMetrics[]): FilterState {
  const h = parseHash(hash)
  const withData = new Set(metrics.map((m) => m.puzzle))
  // No puzzle selected (the pooled rows) is the default; without pooled rows (older data) the first puzzle with data stands in.
  const first = withData.has(ALL) ? ALL : PUZZLES.find((p) => withData.has(p)) ?? null
  const puzzle = h.puzzle && (h.puzzle === ALL || PUZZLES.includes(h.puzzle)) && withData.has(h.puzzle) ? h.puzzle : first
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
  // `detection`, the old id of the critical thinking tab, keeps old shared links working.
  const wanted = h.metric === 'detection' ? 'critical' : h.metric
  const metric = METRICS.find((m) => m.id === wanted)?.id ?? 'precision'
  return { puzzle, providerOn, modelOff, metric }
}

export default function BenchmarkView({ metrics, setupMetrics = [], attemptsUrl, legalMoves = {}, definitions = [] }: Props) {
  const withData = useMemo(() => new Set(metrics.map((m) => m.puzzle)), [metrics])
  const defaultPuzzle = useMemo(() => restore('', metrics).puzzle, [metrics])
  const [init] = useState(() => restore(typeof location === 'undefined' ? '' : location.hash, metrics))
  const [puzzle, setPuzzle] = useState<string | null>(init.puzzle)
  const [providerOn, setProviderOn] = useState<Set<string>>(init.providerOn)
  const [modelOff, setModelOff] = useState<Set<string>>(init.modelOff)
  const [metric, setMetric] = useState<MetricId>(init.metric)
  // The setup chart's own tab; the URL hash holds only the model chart's.
  const [setupMetric, setSetupMetric] = useState<MetricId>('precision')
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
    metric: metric !== 'precision' ? metric : undefined,
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

  // Clicking the selected puzzle again switches it off, back to all puzzles (when the data has pooled rows to show); clicking another replaces it.
  const choosePuzzle = (id: string) => {
    const next = id === puzzle ? (withData.has(ALL) ? ALL : puzzle) : id
    if (next === puzzle) return
    setPuzzle(next)
    setModelOff(new Set())
  }
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
  const setupCurrent = METRICS.find((m) => m.id === setupMetric)!
  // Each setup's mean over the models the filter shows.
  const setupResult = useMemo(() => setupBars(setupMetrics, puzzle ?? ALL, names, setupCurrent.setupPick), [setupMetrics, puzzle, names.join('\u0000'), setupCurrent])

  const modelBars = selected.map((m) => ({ model: m.model, rate: current.pick(m) }))
  const { bars, used, left } = setupResult
  const setupRows = names.length > 0 ? bars.map((b) => ({ model: b.label, rate: b.rate })) : []
  const aiModels = (n: number) => `${n} AI ${n === 1 ? 'model' : 'models'}`
  const setupNote = `Averaged over ${aiModels(used)}.${left > 0 ? ` ${left} left out: no value under every setup.` : ''}`
  const filterText = `${puzzle === ALL || puzzle === null ? 'All puzzles' : `${puzzle} cube`}, ${names.length} AI ${names.length === 1 ? 'model' : 'models'}`

  return (
    <div className="benchmark cube-solver">
      <Filter puzzles={puzzles} puzzle={puzzle === ALL ? null : puzzle} onPuzzle={choosePuzzle} providers={providers} providerOn={ticked} onProvider={toggleProvider} models={models} modelOn={modelOn} onModel={toggleModel} showModels={showModels} />
      {puzzle === null ? (
        <p>No results yet.</p>
      ) : (
        <>
          <MetricChart
            idPrefix="metric"
            heading="Metrics by AI model"
            intro="Compares the selected AI models on each metric, over the puzzle and models chosen above."
            by="AI model"
            firstNumber={1}
            tabs={MODEL_TABS}
            metric={metric}
            onMetric={(id) => setMetric(id as MetricId)}
            definitions={definitions}
            layoutKey={String(puzzle)}
            bars={modelBars}
            filterText={filterText}
          >
            {showModels ? (
              <BarChart title={current.label} higherIsBetter={current.higherIsBetter} rows={modelBars} />
            ) : (
              <p className="empty">Pick an AI provider to see results.</p>
            )}
          </MetricChart>
          {setupMetrics.length > 0 && (
            <MetricChart
              idPrefix="setup-metric"
              heading="Metrics by setup"
              intro="Compares no model, descriptive model, and prescriptive model: how much of the puzzle's rules the prompt carries. Each bar averages the selected AI models that have a value under every setup."
              by="setup"
              firstNumber={4}
              tabs={SETUP_TABS}
              metric={setupMetric}
              onMetric={(id) => setSetupMetric(id as MetricId)}
              definitions={definitions}
              layoutKey={String(puzzle)}
              bars={setupRows}
              note={setupRows.length > 0 ? setupNote : undefined}
              filterText={filterText}
            >
              {showModels ? (
                <BarChart title={`${setupCurrent.label} by setup`} higherIsBetter={setupCurrent.higherIsBetter} rows={setupRows} />
              ) : (
                <p className="empty">Pick an AI provider to see results.</p>
              )}
            </MetricChart>
          )}
          <Player key={`${puzzle}|${names.join('\u0000')}`} puzzle={puzzle} models={names} attemptsUrl={attemptsUrl} legalMoves={legalMoves} />
        </>
      )}
      <Source shown={selected.length > 0 ? { attempts: selected.reduce((a, m) => a + m.attempts, 0), tokens: selected.reduce((a, m) => a + m.tokens, 0) } : undefined} />
    </div>
  )
}
