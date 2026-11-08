// The one chevron shape, shared by the camera overlay (frame pixels) and the cube drawing (viewBox units).
import type { Direction } from '../steps/state/guide'

export type Dir = Exclude<Direction, 'over'>

/** A chevron pointing right in a unit box, as polygon points. */
const CHEVRON: readonly (readonly [number, number])[] = [[0, 0], [0.4, 0], [1, 0.5], [0.4, 1], [0, 1], [0.6, 0.5]]

/** A chevron pointing `dir`, `size` across, inset `inset` from that edge of the box, centred along it; as polygon points. */
export function chevronPoints(dir: Dir, box: { x: number; y: number; w: number; h: number }, size: number, inset: number): string {
  const x0 = box.x + (dir === 'left' ? inset : dir === 'right' ? box.w - inset - size : (box.w - size) / 2)
  const y0 = box.y + (dir === 'up' ? inset : dir === 'down' ? box.h - inset - size : (box.h - size) / 2)
  const at = ([u, v]: readonly [number, number]) => {
    const [a, b] = dir === 'right' ? [u, v] : dir === 'left' ? [1 - u, v] : dir === 'down' ? [v, u] : [v, 1 - u]
    return `${x0 + a * size},${y0 + b * size}`
  }
  return CHEVRON.map(at).join(' ')
}
