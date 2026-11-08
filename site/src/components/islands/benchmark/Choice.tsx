import type { KeyboardEvent, ReactNode } from 'react'

/** `icon` replaces the visible text (a drawing, aria-hidden); `name` is then the button's accessible name. Such a button wears `.square`, which the shared button rules skip. */
export interface Option { id: string; label: string; icon?: ReactNode; name?: string }

interface Props {
  /** `radio` for a one-of choice (puzzle), `tab` for the metric tabs. */
  role: 'radio' | 'tab'
  label: string
  /** The id of a visible heading that names the group; used instead of `label` when set. */
  labelledBy?: string
  options: readonly Option[]
  value: string | null
  onChange: (id: string) => void
  /** Prefix of the tab ids, so a tabpanel can name its tab. */
  idPrefix?: string
  /** The tabpanel's id, for aria-controls on each tab. */
  panelId?: string
  /** An option for which a "?" button is laid over the tab's right end: the tab reserves room for it (`.has-help`). The button itself lives outside the tablist, so the tablist holds only tabs. */
  reserve?: (o: Option) => boolean
}

/** A row of toggle buttons where exactly one is on. They wear the /cube solver's text-button look (`.cube-solver button`, src/styles/cube-stage.css), and the on one `.primary`. */
export function Choice({ role, label, labelledBy, options, value, onChange, idPrefix, panelId, reserve }: Props) {
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    if (options.length === 0) return
    const at = options.findIndex((o) => o.id === value)
    const last = options.length - 1
    let to: number
    if (e.key === 'Home') to = 0
    else if (e.key === 'End') to = last
    else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') to = at === -1 || at === last ? 0 : at + 1
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') to = at <= 0 ? last : at - 1
    else return
    e.preventDefault()
    const next = options[to]
    onChange(next.id)
    const buttons = e.currentTarget.querySelectorAll<HTMLButtonElement>('button')
    buttons[options.indexOf(next)]?.focus()
  }
  return (
    <div className="options" role={role === 'tab' ? 'tablist' : 'radiogroup'} aria-label={labelledBy ? undefined : label} aria-labelledby={labelledBy} onKeyDown={key}>
      {options.map((o) => {
        const on = value === o.id
        return (
          <button
            key={o.id}
            type="button"
            role={role}
            id={idPrefix ? `${idPrefix}-${o.id}` : undefined}
            aria-controls={role === 'tab' ? panelId : undefined}
            {...(role === 'tab' ? { 'aria-selected': on } : { 'aria-checked': on })}
            tabIndex={on || value === null ? 0 : -1}
            className={[on && !o.icon ? 'primary' : null, o.icon ? 'square' : null, reserve?.(o) ? 'has-help' : null].filter(Boolean).join(' ') || undefined}
            aria-label={o.icon ? (o.name ?? o.label) : undefined}
            onClick={() => onChange(o.id)}
          >
            {o.icon ? <span aria-hidden="true">{o.icon}</span> : o.label}
          </button>
        )
      })}
    </div>
  )
}
