// The convex hull of 2D points (Andrew's monotone chain) and a strict point-outside test. Pure.
export type Pt = readonly [number, number]

const cross = (o: Pt, a: Pt, b: Pt) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

/** The hull's vertices in a consistent winding, no collinear points. */
export function convexHull(points: readonly Pt[]): Pt[] {
  const pts = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1])
  const half = (list: Pt[]) => list.reduce<Pt[]>((h, p) => {
    while (h.length >= 2 && cross(h[h.length - 2], h[h.length - 1], p) <= 0) h.pop()
    h.push(p)
    return h
  }, [])
  const lo = half(pts), up = half([...pts].reverse())
  return [...lo.slice(0, -1), ...up.slice(0, -1)]
}

/** True when p lies strictly outside the hull (on the wrong side of at least one edge). */
export const outsideHull = (hull: readonly Pt[], p: Pt): boolean =>
  hull.some((a, i) => cross(a, hull[(i + 1) % hull.length], p) < 0)

/** The distance from p to the nearest hull edge (segment). */
export function distanceToHull(hull: readonly Pt[], p: Pt): number {
  return Math.min(...hull.map((a, i) => {
    const b = hull[(i + 1) % hull.length]
    const dx = b[0] - a[0], dy = b[1] - a[1]
    const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy || 1)))
    return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)
  }))
}
