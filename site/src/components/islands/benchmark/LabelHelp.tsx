import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'

/** A round "?" after a bar label, with a popover holding the term's definition. A mouse hover opens it and it closes 150ms after the pointer leaves the "?" and the popover, unless a click pinned it; a click or keyboard focus (focus-visible) opens it for touch and keyboard users. It closes on Escape, on a click outside, and when focus leaves it. Opening it closes every other chart popover on the page (the `chart-popover` window event), and the other way round. */
export function LabelHelp({ name, definition }: { name: string; definition: string }) {
  const [open, setOpen] = useState(false)
  const [up, setUp] = useState(false)
  const wrap = useRef<HTMLSpanElement>(null)
  const pinned = useRef(false)
  const byFocus = useRef(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const id = useId()
  const clear = () => { if (timer.current) clearTimeout(timer.current); timer.current = null }
  useEffect(() => clear, [])
  useEffect(() => {
    if (open) window.dispatchEvent(new CustomEvent('chart-popover', { detail: id }))
  }, [open])
  useEffect(() => {
    const onOther = (e: Event) => { if ((e as CustomEvent<string>).detail !== id) setOpen(false) }
    window.addEventListener('chart-popover', onOther)
    return () => window.removeEventListener('chart-popover', onOther)
  }, [id])
  // Below the label by default, above it when the viewport has no room below.
  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const b = wrap.current?.getBoundingClientRect()
      const h = wrap.current?.querySelector<HTMLElement>('.label-pop')?.offsetHeight ?? 0
      if (!b) return
      const headerBottom = document.querySelector('.site-header')?.getBoundingClientRect().bottom ?? 0
      const roomBelow = window.innerHeight - b.bottom - 8
      const roomAbove = b.top - Math.max(0, headerBottom) - 8
      setUp(roomBelow < h && roomAbove >= h)
    }
    place()
    window.addEventListener('scroll', place, { passive: true })
    window.addEventListener('resize', place)
    return () => { window.removeEventListener('scroll', place); window.removeEventListener('resize', place) }
  }, [open])
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setOpen(false)
      if (wrap.current?.contains(document.activeElement)) wrap.current.querySelector<HTMLElement>('button')?.focus()
    }
    const onClick = (e: Event) => { if (!wrap.current?.contains(e.target as Node | null)) setOpen(false) }
    document.addEventListener('keydown', onKey)
    document.addEventListener('click', onClick)
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('click', onClick) }
  }, [open])
  const leave = (e: { pointerType: string }) => {
    if (e.pointerType !== 'mouse' || pinned.current) return
    clear()
    timer.current = setTimeout(() => setOpen(false), 150)
  }
  return (
    <span className="label-help" ref={wrap} onBlur={(e) => { if (byFocus.current && !e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false) }}>
      <button
        type="button"
        className="label-help-btn"
        aria-label={`What is ${name}?`}
        aria-expanded={open}
        aria-controls={id}
        aria-describedby={open ? id : undefined}
        onClick={() => {
          clear()
          byFocus.current = false
          // Clicking the "?" the hover just opened keeps it open (pinned); otherwise a click toggles.
          if (open && !pinned.current) pinned.current = true
          else { pinned.current = !open; setOpen(!open) }
        }}
        onPointerEnter={(e) => {
          if (e.pointerType !== 'mouse') return
          clear()
          if (!open) { pinned.current = false; byFocus.current = false; setOpen(true) }
        }}
        onPointerLeave={leave}
        onFocus={(e) => {
          let visible = false
          try { visible = e.currentTarget.matches(':focus-visible') } catch { /* no :focus-visible */ }
          if (visible && !open) { pinned.current = true; byFocus.current = true; setOpen(true) }
        }}
      >?</button>
      {/* Always in the DOM (hidden while closed), so aria-controls points at an element that exists. */}
      <span className={`label-pop${up ? ' up' : ''}`} id={id} role="dialog" aria-label={name} hidden={!open} tabIndex={-1} onPointerEnter={(e) => { if (e.pointerType === 'mouse') clear() }} onPointerLeave={leave}>{definition}</span>
    </span>
  )
}
