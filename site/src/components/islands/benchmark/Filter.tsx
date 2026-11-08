import type { ReactNode } from 'react'
import { Choice, type Option } from './Choice'
import { CubeIcon, LayersIcon, SparkleIcon } from './icons'
import { PROVIDERS } from '../../../lib/benchmark'

export type { Option }
export type ModelOption = Option & { provider: string }

interface Props {
  puzzles: readonly Option[]
  puzzle: string | null
  onPuzzle: (id: string) => void
  providers: readonly Option[]
  providerOn: ReadonlySet<string>
  onProvider: (id: string, on: boolean) => void
  models: readonly ModelOption[]
  modelOn: ReadonlySet<string>
  onModel: (id: string, on: boolean) => void
  /** Whether the Model group shows: only while a provider is ticked. */
  showModels: boolean
}

function Check({ o, on, onToggle }: { o: Option; on: ReadonlySet<string>; onToggle: (id: string, on: boolean) => void }) {
  return (
    <label>
      <input type="checkbox" checked={on.has(o.id)} onChange={(e) => onToggle(o.id, e.target.checked)} />
      <span>{o.label}</span>
    </label>
  )
}

function Toggles({ labelledBy, options, on, onToggle }: { labelledBy: string; options: readonly Option[]; on: ReadonlySet<string>; onToggle: (id: string, on: boolean) => void }) {
  return (
    <div className="options checks" role="group" aria-labelledby={labelledBy}>
      {options.map((o) => <Check key={o.id} o={o} on={on} onToggle={onToggle} />)}
    </div>
  )
}

/** The models as columns, one per provider (in the order given), each model under the one before it. */
function ModelColumns({ labelledBy, options, on, onToggle }: { labelledBy: string; options: readonly ModelOption[]; on: ReadonlySet<string>; onToggle: (id: string, on: boolean) => void }) {
  const columns = [...new Set(options.map((o) => o.provider))].map((p) => options.filter((o) => o.provider === p))
  return (
    <div className="options checks columns" role="group" aria-labelledby={labelledBy}>
      {columns.map((col) => (
        <div key={col[0].provider} className="column">
          {col.map((o) => <Check key={o.id} o={o} on={on} onToggle={onToggle} />)}
        </div>
      ))}
    </div>
  )
}

/** One step of the filter: /cube's markup (`ol.steps > li > .title (.num + .label)`, then `.body`). The circle holds an icon, not /cube's digit. All are `current`: ringed, the title in full text colour. */
function Step({ icon, title, id, children }: { icon: ReactNode; title: string; id: string; children: ReactNode }) {
  return (
    <li className="current">
      <div className="title">
        <span className="num" aria-hidden="true">{icon}</span>
        <span className="label" id={id}>{title}</span>
      </div>
      <div className="body">{children}</div>
    </li>
  )
}

/** Puzzle (one, buttons with a cube drawing), AI provider (any) and model (any, checkboxes with their text) as numbered steps, the options of each in a row under its title; the parent owns the state and the cascade between them. */
export function Filter({ puzzles, puzzle, onPuzzle, providers, providerOn, onProvider, models, modelOn, onModel, showModels }: Props) {
  return (
    <ol className="steps filter" role="list" aria-label="Filter">
      <Step icon={<CubeIcon />} title="Puzzle" id="filter-puzzle">
        <Choice role="radio" label="Puzzle" labelledBy="filter-puzzle" options={puzzles} value={puzzle} onChange={onPuzzle} />
      </Step>
      <Step icon={<SparkleIcon />} title="AI provider" id="filter-provider">
        <Toggles labelledBy="filter-provider" options={providers} on={providerOn} onToggle={onProvider} />
        {/* Every provider, invisible and zero-high: the step is always as wide as with all of them, so its right-aligned title stays put when a puzzle has fewer. */}
        <div className="options checks sizer" aria-hidden="true">
          {PROVIDERS.map((p) => <label key={p.id}><input type="checkbox" tabIndex={-1} disabled /><span>{p.label}</span></label>)}
        </div>
      </Step>
      {showModels && (
        <Step icon={<LayersIcon />} title="Model" id="filter-model">
          <ModelColumns labelledBy="filter-model" options={models} on={modelOn} onToggle={onModel} />
        </Step>
      )}
    </ol>
  )
}
