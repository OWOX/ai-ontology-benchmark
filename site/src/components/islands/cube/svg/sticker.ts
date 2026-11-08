// What both drawings share about a sticker: its fill and how it announces and answers a tap, kept in one place so
// the 3D cube and the net cannot drift apart. Spec: docs/superpowers/specs/2026-10-11-cube-steps-design.md
import type { KeyboardEvent, MouseEvent } from 'react'
import type { PolyModel } from '../poly/model'
import { POLY_PALETTES } from '../poly/palettes'
import { COLOR_OF, type CubeGeometry, type Face, type Facelets } from '../core/geometry'

export const stickerFill = (ch: string) => (ch === '?' ? 'var(--cube-unknown)' : `var(--cube-${COLOR_OF[ch as Face]})`)

/** The CSS fill of a poly facelet letter: the colour its face has in the puzzle's palette, or the unknown fill for `?`. */
export const polyFill = (m: PolyModel, ch: string) => POLY_PALETTES[m.id][ch.charCodeAt(0) - 97]?.fill ?? 'var(--cube-unknown)'

/** Whether a tap on sticker i paints: every sticker does, except an odd cube's centres, which name their faces, and the `frozen` ones. */
export const tappable = (g: CubeGeometry, i: number, frozen?: readonly number[]) => (g.centre < 0 || i % g.perFace !== g.centre) && !frozen?.includes(i)

/** Button props for a tappable sticker when taps are wanted; none for centres, a `frozen` sticker or a read-only drawing. */
export function stickerProps(g: CubeGeometry, i: number, facelets: Facelets, pending: ReadonlySet<number>, onSticker?: (index: number, el: Element) => void, frozen?: readonly number[]) {
  if (!onSticker || !tappable(g, i, frozen)) return {}
  return {
    role: 'button',
    tabIndex: 0,
    'aria-label': `${COLOR_OF[g.STICKERS[i].face]} face, sticker ${(i % g.perFace) + 1}, ${
      pending.has(i) ? 'reading' : facelets[i] === '?' ? 'unread' : COLOR_OF[facelets[i] as Face]
    }`,
    // Assistive tech activates a button with a synthetic click (detail 0); real clicks are handled on pointer up.
    onClick: (e: MouseEvent<Element>) => {
      if (e.detail === 0) onSticker(i, e.currentTarget)
    },
    // Enter acts on press. Space acts on release, so the keyup cannot land on what the tap opens (a picker takes focus).
    onKeyDown: (e: KeyboardEvent<Element>) => {
      if (e.key === 'Enter') { e.preventDefault(); onSticker(i, e.currentTarget) }
      else if (e.key === ' ') e.preventDefault()
    },
    onKeyUp: (e: KeyboardEvent<Element>) => {
      if (e.key === ' ') { e.preventDefault(); onSticker(i, e.currentTarget) }
    },
  }
}

/** Whether a tap on a poly sticker paints: every one does, except the Megaminx centres, which name their faces. */
export const polyTappable = (m: PolyModel, i: number) => m.id !== 'megaminx' || m.stickers[i].orbit !== 'CENTERS'

/** Button props for a tappable poly sticker, as stickerProps gives a cube's. */
export function polyStickerProps(m: PolyModel, i: number, facelets: string, pending: ReadonlySet<number>, onSticker?: (index: number, el: Element) => void) {
  if (!onSticker || !polyTappable(m, i)) return {}
  const palette = POLY_PALETTES[m.id]
  const colour = (ch: string) => palette[ch.charCodeAt(0) - 97]?.name ?? 'unread'
  return {
    role: 'button',
    tabIndex: 0,
    'aria-label': `${palette[m.stickers[i].face].name} face, sticker ${(i % m.perFace) + 1}, ${pending.has(i) ? 'reading' : facelets[i] === '?' ? 'unread' : colour(facelets[i])}`,
    onClick: (e: MouseEvent<Element>) => {
      if (e.detail === 0) onSticker(i, e.currentTarget)
    },
    // As stickerProps: Space acts on release, so its keyup cannot land on the ring's first swatch.
    onKeyDown: (e: KeyboardEvent<Element>) => {
      if (e.key === 'Enter') { e.preventDefault(); onSticker(i, e.currentTarget) }
      else if (e.key === ' ') e.preventDefault()
    },
    onKeyUp: (e: KeyboardEvent<Element>) => {
      if (e.key === ' ') { e.preventDefault(); onSticker(i, e.currentTarget) }
    },
  }
}
