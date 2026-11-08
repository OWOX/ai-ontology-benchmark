// One rotatable drawing of a facelet string: an orthographic projection under one rotation matrix, three
// faces visible, turned like a trackball by the pointer or the arrow keys. A pose (a face, a quarter turn and
// an optional tilt of the camera's lean) composes into that one rotation, which the drawing eases to
// (`opposite` draws it as seen from the far side, for a visitor facing the webcam). It greys when the cube is
// lost. Stickers are a colour, unknown (`?`), or pending (votes, not yet confirmed; dashed).
// Styled in src/pages/_cube.astro.
// Spec: docs/superpowers/specs/2026-10-11-cube-angle-design.md ("The drawing"),
// docs/superpowers/specs/2026-10-11-cube-recognition-design.md ("Following the cube")
import { Fragment, memo, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from 'react'
import { G3, NORMAL, parseMove, type CubeGeometry, type Face, type Facelets, type Vec } from '../core/geometry'
import { fromOpposite, type Pose, type Tilt } from '../core/pose'
import type { Direction } from '../steps/state/guide'
import { layerPolygons, rotateAbout, type Part } from './turn'
import { moveArrow, polyMoveArrow } from './moveArrow'
import { polyDrawModel } from './drawModel'
import type { PolyModel } from '../poly/model'
import { bandArrow, polyBandArrow, polyBandOptions, type Arrow } from './bandArrow'
import type { Pt } from './hull'
import { chevronPoints } from './chevron'
import { roundCorners } from './rounded'
import { stickerFill, stickerProps, tappable, polyStickerProps, polyTappable } from './sticker'
import { facingView } from './polyFacing'
import { IDENTITY, axisAngle, fromAxisAngle, mul, rotX, rotY, rotZ, transpose, type Mat } from './rotation'

interface Props {
  /** The cube's size; defaults to the 3x3. */
  geometry?: CubeGeometry
  /** A poly puzzle (Pyraminx, Skewb, Megaminx) to draw instead of a cube: `facelets` is then its state string, and `geometry` and `pose` are ignored. */
  poly?: PolyModel
  facelets: Facelets
  move?: string | null
  /** A face, quarter turn and tilt to ease to, unless the visitor dragged in the last DRAG_HOLD ms. */
  pose?: Pose | null
  /** Draw the pose from the visitor's side of the camera: the opposite face, and the turn and tilt mapped by fromOpposite. */
  opposite?: boolean
  /** The cube is out of view: the drawing greys and holds its position. */
  lost?: boolean
  /** Facelet indices with votes but not yet confirmed: drawn dashed. */
  pending?: readonly number[]
  /** The sticker tapped, and its element (the colour picker anchors there). */
  onSticker?: (index: number, el: Element) => void
  /** Stickers that take no tap now: no button, no picker. */
  frozen?: readonly number[]
  /** The pointer is over the drawing, or a finger is on it; the State step shows the colours then even while the cube is out of view. */
  onHot?: (hot: boolean) => void
  /** The colours are showing on a cube that is out of view: when this ends the drawing eases back to the pose at once, however recently it was dragged. */
  peek?: boolean
  /** Which way to turn the cube next: a chevron at that edge of the drawing, static in the frame. */
  arrow?: Direction | null
  /** A face turn part-way: its layer drawn rotated by `progress`, the eased share (0 to 1) of the move's angle (see turnFraction), with the cut closed by dark cells. */
  turn?: { move: string; progress: number } | null
  /** The Megaminx holds still this many ms after a move arrives before it turns to the move's face, and hides the arrow until it has. 0 (default) turns at once: Back, a jump, or reduced motion. */
  aimDelay?: number
  label: string
  /** Takes keyboard focus and turns on the arrow keys (default). The player turns it off: its arrows step the solution, and a press is kept from moving focus. Pointer drags still turn it. */
  focusable?: boolean
}

export const DEG_PER_PX = 0.5
export const TAP_PX = 5
export const KEY_STEP = 15
export const DRAG_HOLD = 3000
/** Time constant of the ease to a pose, and the angle (degrees) at which it counts as arrived. */
export const EASE_MS = 120
export const EASE_EPS = 0.2
/** A face edge-on has a depth of rounding noise, not zero; below this it counts as hidden. */
const FACE_EPS = 1e-6
/** Mid-turn, a poly sticker whose normal is this close to edge-on is a sliver and is not drawn. */
const TURN_EPS = 0.02

/** The camera's lean when a pose has no tilt: F beside the face in front, from above (from below for U). */
export const LEAN = (face: Face): Tilt => ({ yaw: -35, pitch: face === 'U' ? -25 : 25, roll: 0 })

/** A face square-on to the viewer, its net top up (checked in svg.test.tsx against NORMAL, DOWN and RIGHT). */
export const SQUARE: Record<Face, Mat> = {
  F: IDENTITY, R: rotY(-90), B: rotY(180), L: rotY(90), U: rotX(90), D: rotX(-90),
}

/** The face square-on, rolled `turn` clockwise quarter turns. */
export const faceRotation = (face: Face, turn: number): Mat => mul(rotZ(turn * 90), SQUARE[face])

const tiltRotation = (t: Tilt): Mat => mul(rotZ(t.roll), mul(rotX(t.pitch), rotY(t.yaw)))

/** The rotation that shows a pose: its face and turn under its tilt, or under the lean when it has none. */
export const targetOf = (pose: Pose): Mat => mul(tiltRotation(pose.tilt ?? LEAN(pose.face)), faceRotation(pose.face, pose.turn))

const BOX = { x: -2.8, y: -2.8, w: 5.6, h: 5.6 }

const DEFAULT_VIEW = targetOf({ face: 'F', turn: 0 })

/** A poly puzzle opens on the same three-quarter view and turns by drag; nothing steers it. */
const POLY_VIEW = DEFAULT_VIEW

/** The Megaminx's view: every face's normal is clearly toward the viewer (z at least 0.3) or clearly away (at most -0.15), none edge-on. */
const MEGAMINX_VIEW = mul(rotX(27), rotY(-72))

/**
 * The view a poly puzzle opens on. The Skewb and Megaminx read well on the cube's view; the Pyraminx looks at the edge between its
 * front and right faces from slightly above, so two faces show evenly instead of the second being a sliver.
 */
export function polyOpening(m: PolyModel): Mat {
  if (m.id === 'megaminx') return MEGAMINX_VIEW
  if (m.id !== 'pyraminx') return POLY_VIEW
  const [a, b] = [m.faces[0].normal, m.faces[3].normal]
  const d = [a[0] + b[0], a[1] + b[1] + 0.6, a[2] + b[2]]
  const dl = Math.hypot(d[0], d[1], d[2])
  const z = d.map((c) => c / dl)
  // x = up x z with up the world's y, then y = z x x; the rows are the screen's axes in puzzle space.
  const xr = [z[2], 0, -z[0]], xl = Math.hypot(xr[0], xr[2])
  const x = [xr[0] / xl, 0, xr[2] / xl]
  const y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
  return [...x, ...y, ...z] as unknown as Mat
}

/** Outline widths per poly: the Megaminx's many small stickers need a thinner line to keep their light gaps. */
const POLY_STROKE = { pyraminx: 0.03, skewb: 0.05, megaminx: 0.025 }

/** The 3x3 with only its centres known; another size asks its geometry's blank(). */
export const blankFacelets = (): Facelets => G3.blank()

/** Screen x, screen y (down) and depth toward the viewer of a cube-space point under a rotation matrix. */
export function projectWith(m: Mat, v: Vec): [number, number, number] {
  const x = m[0] * v[0] + m[1] * v[1] + m[2] * v[2]
  const y = m[3] * v[0] + m[4] * v[1] + m[5] * v[2]
  const z = m[6] * v[0] + m[7] * v[1] + m[8] * v[2]
  return [x, -y, z] // cube y points up, the screen's down
}

/**
 * Screen x, screen y (down) and depth toward the viewer of a cube-space point under yaw (about y), then pitch
 * (about x), then roll: a turn of the screen plane, clockwise for positive degrees (y points down).
 */
export function project(v: Vec, yaw: number, pitch: number, roll = 0): [number, number, number] {
  return projectWith(mul(rotZ(roll), mul(rotX(pitch), rotY(yaw))), v)
}

const centroid = (c: readonly Vec[]): Vec => [
  c.reduce((a, v) => a + v[0], 0) / c.length,
  c.reduce((a, v) => a + v[1], 0) / c.length,
  c.reduce((a, v) => a + v[2], 0) / c.length,
]

function CubeViewImpl({ geometry: g = G3, poly, facelets, pending = [], move, pose, opposite, lost, peek, onSticker, frozen, onHot, arrow: arrowDir, turn: flying, aimDelay = 0, label, focusable = true }: Props) {
  const [view, setView] = useState<Mat>(() => (poly ? polyOpening(poly) : pose ? targetOf(opposite ? fromOpposite(pose) : pose) : DEFAULT_VIEW))
  const current = useRef<Mat>(view)
  const frame = useRef<number | null>(null)
  const lastDrag = useRef(0)
  const drag = useRef<{ id: number; x: number; y: number; start: Mat; moved: boolean; index: number | null } | null>(null)

  const show = (m: Mat) => {
    if (m.every((a, i) => a === current.current[i])) return
    current.current = m
    setView(m)
  }
  const stopEase = () => {
    if (frame.current !== null) cancelAnimationFrame(frame.current)
    frame.current = null
  }
  /** Moves a fraction 1 - exp(-dt / EASE_MS) of the way along the relative rotation each frame; stops, exactly on target, within EASE_EPS. */
  const easeTo = (target: Mat, done?: () => void) => {
    stopEase()
    if (typeof requestAnimationFrame === 'undefined' || axisAngle(mul(target, transpose(current.current))).angle <= EASE_EPS) return (show(target), done?.())
    let last: number | null = null
    const step = (now: number) => {
      const dt = last === null ? 16 : Math.max(0, now - last)
      last = now
      const f = 1 - Math.exp(-dt / EASE_MS)
      const from = current.current
      const rel = axisAngle(mul(target, transpose(from)))
      if (rel.angle <= EASE_EPS) {
        frame.current = null
        show(target)
        return done?.()
      }
      show(mul(fromAxisAngle(rel.axis, rel.angle * f), from))
      frame.current = requestAnimationFrame(step)
    }
    frame.current = requestAnimationFrame(step)
  }
  useEffect(() => stopEase, [])

  const face = pose?.face, turn = pose?.turn
  const tyaw = pose?.tilt?.yaw, tpitch = pose?.tilt?.pitch, troll = pose?.tilt?.roll
  useEffect(() => {
    // A poly ignores the pose; stopping here would cancel the Megaminx's turn to its first move, which runs before this effect on mount.
    if (poly) return
    if (!pose) return stopEase()
    const target = targetOf(opposite ? fromOpposite(pose) : pose)
    let t: ReturnType<typeof setTimeout> | undefined
    const settle = () => {
      const wait = DRAG_HOLD - (Date.now() - lastDrag.current)
      if (drag.current || wait > 0) {
        t = setTimeout(settle, drag.current ? DRAG_HOLD : wait)
        return
      }
      easeTo(target)
    }
    const wait = DRAG_HOLD - (Date.now() - lastDrag.current)
    if (wait <= 0 && !drag.current) easeTo(target)
    else t = setTimeout(settle, Math.max(wait, 0))
    return () => clearTimeout(t)
  }, [face, turn, tyaw, tpitch, troll, opposite])

  // A peek that ends hands the drawing back to the camera pose, dragged or not.
  const wasPeek = useRef(false)
  useEffect(() => {
    if (wasPeek.current && !peek && pose) {
      lastDrag.current = 0
      easeTo(targetOf(opposite ? fromOpposite(pose) : pose))
    }
    wasPeek.current = !!peek
  }, [peek])

  const onPointerDown = (e: PointerEvent<SVGSVGElement>) => {
    if (e.pointerType === 'touch') onHot?.(true)
    if (!e.isPrimary || e.button !== 0) return
    if (drag.current && drag.current.id !== e.pointerId) return
    // The default of a press is to focus what is under it; a drag must not focus a sticker.
    e.preventDefault()
    const hit = (e.target as Element).closest?.('[data-index]')
    const index = hit ? Number(hit.getAttribute('data-index')) : null
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, start: current.current, moved: false, index }
  }
  const onPointerMove = (e: PointerEvent<SVGSVGElement>) => {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    if (e.buttons === 0) { drag.current = null; return }
    const dx = e.clientX - d.x, dy = e.clientY - d.y
    if (!d.moved) {
      if (Math.hypot(dx, dy) < TAP_PX) return
      d.moved = true
      // The drag takes over from wherever an ease in flight had got to.
      stopEase()
      setAiming(false)
      d.start = current.current
      e.currentTarget.setPointerCapture?.(e.pointerId)
    }
    lastDrag.current = Date.now()
    // About the screen's axes, so a drag moves the cube the way the pointer moves whatever the roll.
    show(mul(mul(rotX(dy * DEG_PER_PX), rotY(dx * DEG_PER_PX)), d.start))
  }
  const onPointerUp = (e: PointerEvent<SVGSVGElement>) => {
    if (e.pointerType === 'touch') onHot?.(false)
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    drag.current = null
    if (e.type === 'pointerup' && !d.moved && d.index !== null && (poly ? polyTappable(poly, d.index) : tappable(g, d.index, frozen))) onSticker?.(d.index, e.currentTarget.querySelector(`[data-index="${d.index}"]`) ?? e.currentTarget)
  }
  const onPointerLeave = () => {
    onHot?.(false)
    if (drag.current && !drag.current.moved) drag.current = null
  }
  const onKeyDown = (e: KeyboardEvent<SVGSVGElement>) => {
    const step: Record<string, [number, number]> = {
      ArrowLeft: [-KEY_STEP, 0], ArrowRight: [KEY_STEP, 0], ArrowUp: [0, -KEY_STEP], ArrowDown: [0, KEY_STEP],
    }
    const s = step[e.key]
    if (!s || e.target !== e.currentTarget) return
    e.preventDefault()
    lastDrag.current = Date.now()
    stopEase()
    setAiming(false)
    show(mul(mul(rotX(s[1]), rotY(s[0])), current.current))
  }

  const pendingSet = new Set(pending)
  // Every polygon that faces the viewer, back to front by its centre's depth, so nearer ones paint over farther ones.
  // Mid-turn the layer's stickers leave their faces, so culling and sorting are per polygon, not per face.
  const dm = useMemo(() => (poly ? polyDrawModel(poly) : null), [poly])
  // The Megaminx turns its drawing to the face each move turns, so the face is in sight in front or on the side. A whole-puzzle
  // turn has no face to show; a drag or the DRAG_HOLD after one wins, as for the cube's pose; reduced motion snaps.
  const isFlying = !!flying
  // True from the move's arrival until the drawing has turned to its face: the arrow waits, so it is drawn on the view it belongs to.
  const [aiming, setAiming] = useState(false)
  useLayoutEffect(() => {
    setAiming(false)
    if (!dm || poly?.id !== 'megaminx' || !move || isFlying || !dm.cut?.(move)) return
    const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
    const delay = reduced ? 0 : aimDelay
    // The side of the cut: a half-puzzle turn (R++) has its cut on the far side of the axis, so the view turns to show that side, where the band is.
    const { axis } = dm.turn(move), cutAt = dm.cut!(move)![0].reduce((a, c, k) => a + c * axis[k], 0)
    const aimed: Vec = cutAt < 0 ? [-axis[0], -axis[1], -axis[2]] : axis
    // Aimed from the view as it is when the turn starts, which a drag in the delay may have changed.
    const aim = () => {
      const target = facingView(current.current, aimed)
      if (target === current.current) return setAiming(false)
      if (reduced) {
        stopEase()
        show(target)
        return setAiming(false)
      }
      // A drag in the beat cleared the wait; the arrow still waits for the ease. With no beat (Back, a jump) it shows during the turn.
      if (delay > 0) setAiming(true)
      easeTo(target, () => setAiming(false))
    }
    let t: ReturnType<typeof setTimeout> | undefined
    const settle = () => {
      const wait = DRAG_HOLD - (Date.now() - lastDrag.current)
      if (drag.current || wait > 0) {
        t = setTimeout(settle, drag.current ? DRAG_HOLD : wait)
        return
      }
      aim()
    }
    const start = () => {
      const wait = DRAG_HOLD - (Date.now() - lastDrag.current)
      if (wait <= 0 && !drag.current) aim()
      else t = setTimeout(settle, Math.max(wait, 0))
    }
    // Nothing to turn: the arrow shows at once, and no beat is held for a turn that does not come.
    if (facingView(current.current, aimed) === current.current) return
    if (delay > 0) {
      setAiming(true)
      t = setTimeout(start, delay)
    } else start()
    return () => {
      clearTimeout(t)
      stopEase()
    }
  }, [move, dm, isFlying])
  const flight = flying && !dm ? layerPolygons(g, flying.move, flying.progress) : null
  const polys: { key: string | number; index?: number; corners: readonly Vec[]; normal: Vec; part: Part }[] = []
  const turned = flying && !dm ? parseMove(flying.move) : null
  const partOf = (i: number): Part => {
    const { face, layers: [from, to] } = turned!
    return g.inLayers(i, face, from, to) ? 1 : g.inLayers(i, face, 1, from - 1) ? 2 : 0
  }
  const moveSet = dm && move && !flying ? dm.turn(move).moving : null
  const polyTurn = dm && flying ? dm.turn(flying.move) : null
  if (dm) for (let i = 0; i < dm.count; i++) {
    const moves = !!polyTurn?.moving.has(i)
    const spin = moves ? polyTurn!.angle * flying!.progress : 0
    polys.push({ key: i, index: i, part: moves ? 1 : 0, corners: spin ? dm.corners(i).map((c) => rotateAbout(c, polyTurn!.axis, spin)) : dm.corners(i), normal: spin ? rotateAbout(dm.normal(i), polyTurn!.axis, spin) : dm.normal(i) })
  }
  if (dm && polyTurn) {
    // The cut closed by the puzzle's cross-section: a still copy facing the moving side, and one turning with the moving block facing back.
    const section = dm.cut?.(flying!.move)
    if (section) {
      const { axis, angle } = polyTurn, spin = angle * flying!.progress
      const back: Vec = [-axis[0], -axis[1], -axis[2]]
      polys.push({ key: 'cut-0', corners: section, normal: axis, part: 0 })
      polys.push({ key: 'cut-1', corners: section.map((c) => rotateAbout(c, axis, spin)), normal: rotateAbout(back, axis, spin), part: 1 })
    }
  }
  if (!dm) g.STICKERS.forEach((s, i) => polys.push({ key: i, index: i, part: flight?.stickers.get(i)?.part ?? (turned ? partOf(i) : 0), corners: flight?.stickers.get(i)?.corners ?? g.stickerCorners(i), normal: flight?.stickers.get(i)?.normal ?? s.n }))
  flight?.cuts.forEach((c, k) => polys.push({ key: `cut-${k}`, ...c }))
  // Along the turned axis the near block is the one the face normal points to: with the normal toward the viewer
  // the order is 0, 1, 2, and with it away 2, 1, 0.
  const flipped = turned ? projectWith(view, NORMAL[turned.face])[2] < 0 : polyTurn ? projectWith(view, polyTurn.axis)[2] < 0 : false
  const rank = (p: Part) => (flipped ? 2 - p : p)
  const drawn = polys
    .filter((p) => projectWith(view, p.normal)[2] > (dm && flying && p.index !== undefined ? TURN_EPS : FACE_EPS))
    .map((p) => {
      const pts = p.corners.map((v) => projectWith(view, v))
      return { ...p, pts, depth: projectWith(view, centroid(p.corners))[2] }
    })
    .sort((a, b) => {
      // Mid-turn the parts interleave in centroid depth, so the part farther from the viewer paints first, whole.
      if (flying && a.part !== b.part) return rank(a.part) - rank(b.part)
      return a.depth - b.depth
    })

  // The turn direction: an arrow along each moving layer on the visible adjacent faces (a wide move gets one per layer); when no
  // adjacent face is clearly visible (a face held square-on) it falls back to a single arc beside the cube, clear of its drawing.
  const proj = (v: Vec) => projectWith(view, v)
  // A poly puzzle draws the same band on its moving layer, and the arc beside it when no band is in sight.
  const bands = move && !flying && !aiming ? (dm ? polyBandArrow(dm, proj, move, polyBandOptions(poly!)) : bandArrow(g, proj, move)) : []
  const arrows: Arrow[] = bands.length ? bands : (() => {
    const arc = move && !flying && !aiming ? (dm ? polyMoveArrow(proj, dm, move) : moveArrow(proj, move)) : null
    return arc ? [arc] : []
  })()
  const fixed = ([x, y]: Pt) => `${x.toFixed(3)},${y.toFixed(3)}`
  const pathD = (path: Pt[]) => path.map((p, k) => `${k ? 'L' : 'M'}${fixed(p)}`).join(' ')

  const strokeVars: Record<`--${string}`, string | number> = poly
    ? { '--sticker-stroke': POLY_STROKE[poly.id], '--sticker-dash': `${POLY_STROKE[poly.id] * 2} ${POLY_STROKE[poly.id] * 1.4}` }
    : { '--sticker-stroke': `${(0.06 * 3) / g.n}`, '--sticker-dash': `${(0.12 * 3) / g.n} ${(0.08 * 3) / g.n}` }

  return (
    // The gap between stickers is 0.1 of the pitch and the outline 0.06 of it, so a 5x5 shows the same light strip between outlines as a 3x3.
    <svg
      className={lost ? 'cube-view lost' : 'cube-view'}
      style={strokeVars as CSSProperties}
      viewBox="-2.8 -2.8 5.6 5.6"
      role={onSticker ? 'group' : 'img'}
      aria-label={label}
      tabIndex={focusable ? 0 : undefined}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onPointerLeave={onPointerLeave}
      onPointerEnter={onHot && (() => onHot(true))}
      onKeyDown={focusable ? onKeyDown : undefined}
    >
      {drawn.map((p) => {
        const points = p.pts.map(([x, y]) => `${x.toFixed(3)},${y.toFixed(3)}`).join(' ')
        if (p.index === undefined) return <polygon key={p.key} className={dm ? 'cut core' : 'cut'} points={points} />
        const i = p.index
        if (dm) {
          const cls = [moveSet?.has(i) ? 'sticker turning' : 'sticker', pendingSet.has(i) ? 'pending' : ''].filter(Boolean).join(' ')
          return <polygon key={p.key} data-index={i} className={cls} points={points} style={{ fill: dm.fill(facelets[i]) }} {...polyStickerProps(poly!, i, facelets, pendingSet, onSticker)} />
        }
        const layer = !flying && move && (({ face, layers: [from, to] }) => g.inLayers(i, face, from, to))(parseMove(move))
        const cls = [layer ? 'sticker turning' : 'sticker', pendingSet.has(i) ? 'pending' : ''].filter(Boolean).join(' ')
        // A cube's stickers have slightly rounded corners; the poly stickers and the cut faces keep theirs sharp.
        const round = roundCorners(p.pts).map(([x, y]) => `${x.toFixed(3)},${y.toFixed(3)}`).join(' ')
        return <polygon key={p.key} data-index={i} className={cls} points={round} style={{ fill: stickerFill(facelets[i]) }} {...stickerProps(g, i, facelets, pendingSet, onSticker, frozen)} />
      })}
      {arrows.map((arrow, i) => (
        <Fragment key={i}>
          {bands.length > 0 && <path className="move-arrow-halo" d={pathD(arrow.path)} />}
          <path className="move-arrow" d={pathD(arrow.path)} />
          <polygon className="move-arrow-head" points={arrow.head.map(fixed).join(' ')} />
        </Fragment>
      ))}
      {arrowDir && arrowDir !== 'over' && <polygon className="arrow" points={chevronPoints(arrowDir, BOX, 0.6, 0.15)} />}
    </svg>
  )
}

/** Memoised: the camera loop re-renders its parent at 10 fps with mostly unchanged props. */
export const CubeView = memo(CubeViewImpl)
