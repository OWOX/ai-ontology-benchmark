// The share card's face: a 1x1x1 cube, one sticker per face, drawn the way CubeView draws a cube
// (same view, sticker colours, outline, and rounded corners). Used only by og-card.tsx.
import { useMemo } from 'react'
import { COLOR_OF, DOWN, FACES, NORMAL, RIGHT, type Vec } from '../src/components/islands/cube/core/geometry'
import { roundCorners } from '../src/components/islands/cube/svg/rounded'
import { projectWith, targetOf } from '../src/components/islands/cube/svg/CubeView'

const view = targetOf({ face: 'F', turn: 0 })
// The cube is 3 units wide; a sticker is 0.9 of its pitch, as in CubeView, so the outline matches a 3x3's strip.
const HALF = 1.5
const REACH = 1.5 * 0.9

/** The faces towards the viewer, farthest first, each as the points of its rounded polygon. */
function faces() {
  const at = (f: (typeof FACES)[number], r: number, d: number): Vec => [
    NORMAL[f][0] * HALF + RIGHT[f][0] * r + DOWN[f][0] * d,
    NORMAL[f][1] * HALF + RIGHT[f][1] * r + DOWN[f][1] * d,
    NORMAL[f][2] * HALF + RIGHT[f][2] * r + DOWN[f][2] * d,
  ]
  return FACES.flatMap((f) => {
    const depth = projectWith(view, NORMAL[f])[2]
    if (depth <= 1e-6) return []
    const corners = [at(f, -REACH, -REACH), at(f, REACH, -REACH), at(f, REACH, REACH), at(f, -REACH, REACH)]
    const pts = roundCorners(corners.map((v) => projectWith(view, v))).map(([x, y]) => `${x.toFixed(3)},${y.toFixed(3)}`).join(' ')
    return [{ face: f, depth, pts }]
  }).sort((a, b) => a.depth - b.depth)
}

export function OneCube() {
  const drawn = useMemo(faces, [])
  return (
    <svg className="cube-view" style={{ '--sticker-stroke': 0.18 } as React.CSSProperties} viewBox="-2.8 -2.8 5.6 5.6" role="img" aria-label="">
      {drawn.map((p) => <polygon key={p.face} className="sticker" points={p.pts} style={{ fill: `var(--cube-${COLOR_OF[p.face]})` }} />)}
    </svg>
  )
}
