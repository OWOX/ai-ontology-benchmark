// The default colours of the three poly puzzles, one per face in the model's face order (cubing.js's own
// get3d() order, so face k of the model has the colour cubing.js gives it). `css` names the --cube-<css> custom
// property that fills it on screen (shared with the cube's six, plus six more in src/pages/_cube.astro);
// `rgb` is how a camera sees that plastic, for naming sticker reads.
// Spec: docs/superpowers/specs/2026-10-13-cube-polyhedra-design.md ("Drawing", "Colours")
import { DEFAULT_RGB, type RGB } from '../vision/colors'
import type { PolyId } from './model'

export interface PolyColour {
  name: string
  css: string
  rgb: RGB
  /** The CSS fill. */
  fill: string
}

const colour = (name: string, rgb: RGB, css = name): PolyColour => ({ name, css, rgb, fill: `var(--cube-${css})` })
const cube = (name: keyof typeof DEFAULT_RGB) => colour(name, DEFAULT_RGB[name])

/** The rgb the colour is drawn in, for picking pill lettering: dark green and dark blue are painted in the cube's green and blue, not their camera rgb. */
export const paintedRgb = (c: PolyColour): RGB => (c.css in DEFAULT_RGB ? DEFAULT_RGB[c.css as keyof typeof DEFAULT_RGB] : c.rgb)

export const POLY_PALETTES: Record<PolyId, readonly PolyColour[]> = {
  // faces F, D, L, R
  pyraminx: [cube('green'), cube('yellow'), cube('red'), cube('blue')],
  // faces F, D, L, B, U, R
  skewb: [cube('green'), cube('yellow'), cube('orange'), cube('blue'), cube('white'), cube('red')],
  // faces U, F, L, BL, BR, R, C, A, I, BF, E, D; the two dark ones reuse the cube's green and blue
  megaminx: [
    colour('white', [235, 235, 235]),
    colour('darkgreen', [20, 125, 60], 'green'),
    colour('purple', [115, 55, 175]),
    colour('yellow', [230, 220, 40]),
    colour('darkblue', [30, 60, 185], 'blue'),
    colour('red', [200, 30, 40]),
    colour('beige', [225, 205, 160]),
    colour('lightblue', [60, 155, 230]),
    colour('orange', [240, 120, 30]),
    colour('lightgreen', [140, 215, 45]),
    colour('pink', [240, 115, 175]),
    colour('grey', [145, 145, 150]),
  ],
}
