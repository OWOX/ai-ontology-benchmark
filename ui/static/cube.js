"use strict";
// Spec: docs/specs/ui.md
// Cube drawing for the page: the sticker colours, the net, the isometric view, and the rotatable 3D view. Loaded before
// the page scripts, which use these names. Reads only the states it is given and writes only the SVG it returns.

const STICKERS = { U: "#ffffff", R: "#d62d20", F: "#1f9d55", D: "#f5d90a", L: "#f08a1c", B: "#2155c4" };
const FACE_ORDER = "URFDLB";
const NET_POS = { U: [1, 0], L: [0, 1], F: [1, 1], R: [2, 1], B: [3, 1], D: [1, 2] };
const SVGNS = "http://www.w3.org/2000/svg";
// How the 3D view places the three faces it shows: the face normal, and the 3D direction in which the
// row number and the column number grow. These are the entries of READING and NORMAL in
// src/puzzles/cube.py for U, F, and R. They place stickers only; the move group stays in the engine.
const ISO_FACES = {
  U: { normal: [0, 1, 0], row: [0, 0, 1], col: [1, 0, 0] },
  F: { normal: [0, 0, 1], row: [0, -1, 0], col: [1, 0, 0] },
  R: { normal: [1, 0, 0], row: [0, -1, 0], col: [0, 0, -1] },
};
const ISO_OUTLINE = "#111111";

function svg(tag, attrs) {
  const node = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
  return node;
}

function solvedState(n) {
  return [...FACE_ORDER].map((f) => f.repeat(n * n)).join("");
}

// The size of a cube from its state length, or 0 when the length is not 6*n*n.
function cubeSize(state) {
  const n = Math.round(Math.sqrt(state.length / 6));
  return n >= 1 && 6 * n * n === state.length ? n : 0;
}

// ---- Cube net --------------------------------------------------------------
// Returns an <svg> of a cube net for a 6*n*n state; sized by viewBox, 4x3 faces.
function cubeNet(state, attrs) {
  const n = Math.round(Math.sqrt(state.length / 6));
  const root = svg("svg", { viewBox: "0 0 4 3", ...attrs });
  if (n < 1 || 6 * n * n !== state.length) return root;
  const cell = 1 / n;
  const pad = 0.012;
  [...FACE_ORDER].forEach((face, fi) => {
    const [fx, fy] = NET_POS[face];
    for (let i = 0; i < n * n; i++) {
      const ch = state[fi * n * n + i];
      root.append(svg("rect", {
        x: fx + (i % n) * cell + pad, y: fy + Math.floor(i / n) * cell + pad,
        width: cell - 2 * pad, height: cell - 2 * pad,
        fill: STICKERS[ch] || "#999", stroke: "#2a2f38", "stroke-width": 0.02,
      }));
    }
  });
  return root;
}

// The solved net with each sticker named <face><index>, the index counted from 1 row by row, in the
// order cubeNet draws and the state is read. Returns an <svg>; empty for a size that is not a cube.
function cubeNetNamed(n, attrs) {
  const ok = Number.isInteger(n) && n >= 1;
  const root = cubeNet(ok ? solvedState(n) : "", attrs);
  if (!ok) return root;
  const cell = 1 / n;
  [...FACE_ORDER].forEach((face) => {
    const [fx, fy] = NET_POS[face];
    for (let i = 0; i < n * n; i++) {
      const t = svg("text", {
        x: fx + ((i % n) + 0.5) * cell, y: fy + (Math.floor(i / n) + 0.5) * cell,
        "text-anchor": "middle", "dominant-baseline": "central", "font-size": cell * 0.32,
        fill: face === "U" || face === "D" ? "#111" : "#fff", "pointer-events": "none",
      });
      t.textContent = face + (i + 1);
      root.append(t);
    }
  });
  return root;
}

// ---- Isometric view --------------------------------------------------------
// Orthographic view with U on top, F front-left, R front-right. A 3D point (x, y, z) lands at
// screen x = (x - z) * cos 30, screen y = (x + z) / 2 - y. Units are half a sticker.
const COS30 = Math.sqrt(3) / 2;

function isoPoint([x, y, z]) {
  return [(x - z) * COS30, (x + z) / 2 - y];
}

function isoCorners(face, n, r, c, half) {
  // The corners of the rectangle centred on sticker (r, c), half a sticker (or half a face) wide.
  const { normal, row, col } = ISO_FACES[face];
  const mid = [0, 1, 2].map((k) => n * normal[k] + (2 * r - n + 1) * row[k] + (2 * c - n + 1) * col[k]);
  return [[-1, -1], [-1, 1], [1, 1], [1, -1]].map(([a, b]) =>
    isoPoint(mid.map((m, k) => m + half * (a * row[k] + b * col[k]))));
}

const pointList = (pts) => pts.map((p) => `${p[0].toFixed(3)},${p[1].toFixed(3)}`).join(" ");

// The stickers the 3D view shows, as {face, index, points}: index is the sticker's place in the state.
function isoStickers(n) {
  const out = [];
  for (const face of "URF") {
    const fi = FACE_ORDER.indexOf(face);
    for (let r = 0; r < n; r++) {
      for (let c = 0; c < n; c++) out.push({ face, index: fi * n * n + r * n + c, points: isoCorners(face, n, r, c, 1) });
    }
  }
  return out;
}

// Returns an <svg> of the U, F, and R faces of a 6*n*n state. highlightFace (a face letter or null)
// draws that face's outline thicker; a face the view does not show is not outlined.
function cubeIso(state, n, highlightFace, attrs) {
  const root = svg("svg", { viewBox: `${-2 * n * COS30 - 0.3} ${-2 * n - 0.3} ${4 * n * COS30 + 0.6} ${4 * n + 0.6}`, ...attrs });
  if (!cubeSize(state) || cubeSize(state) !== n) return root;
  for (const s of isoStickers(n)) {
    root.append(svg("polygon", {
      points: pointList(s.points), fill: STICKERS[state[s.index]] || "#999",
      stroke: "#2a2f38", "stroke-width": 0.08, "stroke-linejoin": "round", "data-face": s.face, "data-index": s.index,
    }));
  }
  if (highlightFace && ISO_FACES[highlightFace]) {
    root.append(svg("polygon", {
      points: pointList(isoCorners(highlightFace, n, (n - 1) / 2, (n - 1) / 2, n)), fill: "none",
      stroke: ISO_OUTLINE, "stroke-width": 0.4, "stroke-linejoin": "round", class: "iso-hilite",
    }));
  }
  return root;
}

// ---- Rotatable 3D view -----------------------------------------------------
// All six faces, placed as NORMAL and READING in src/puzzles/cube.py place them. They place
// stickers only; the move group stays in the engine.
const FACES_3D = {
  U: { normal: [0, 1, 0], row: [0, 0, 1], col: [1, 0, 0] },
  R: { normal: [1, 0, 0], row: [0, -1, 0], col: [0, 0, -1] },
  F: { normal: [0, 0, 1], row: [0, -1, 0], col: [1, 0, 0] },
  D: { normal: [0, -1, 0], row: [0, 0, -1], col: [1, 0, 0] },
  L: { normal: [-1, 0, 0], row: [0, -1, 0], col: [0, 0, 1] },
  B: { normal: [0, 0, -1], row: [0, -1, 0], col: [-1, 0, 0] },
};
// The start angles in radians: U on top, F front-left, R front-right, as in the isometric view.
const VIEW_3D = { yaw: -Math.PI / 4, pitch: Math.atan(1 / Math.SQRT2) };

// Turns a 3D point by yaw about the vertical axis, then by pitch about the screen's horizontal axis.
function turn3d([x, y, z], yaw, pitch) {
  const x1 = x * Math.cos(yaw) + z * Math.sin(yaw), z1 = -x * Math.sin(yaw) + z * Math.cos(yaw);
  return [x1, y * Math.cos(pitch) - z1 * Math.sin(pitch), y * Math.sin(pitch) + z1 * Math.cos(pitch)];
}

// The faces that point at the viewer under yaw and pitch, as {face, outline, stickers}: outline is the
// face's screen polygon and each sticker is {index, points}, index being its place in the state.
// Units are half a sticker. A cube is convex, so the faces it returns never overlap.
function cube3dFaces(n, yaw, pitch) {
  const out = [];
  for (const face of FACE_ORDER) {
    const { normal, row, col } = FACES_3D[face];
    if (turn3d(normal, yaw, pitch)[2] <= 1e-9) continue;
    const corners = (r, c, half) => {
      const mid = [0, 1, 2].map((k) => n * normal[k] + (2 * r - n + 1) * row[k] + (2 * c - n + 1) * col[k]);
      return [[-1, -1], [-1, 1], [1, 1], [1, -1]].map(([a, b]) => {
        const p = turn3d(mid.map((m, k) => m + half * (a * row[k] + b * col[k])), yaw, pitch);
        return [p[0], -p[1]];
      });
    };
    const fi = FACE_ORDER.indexOf(face);
    const stickers = [];
    for (let r = 0; r < n; r++) {
      for (let c = 0; c < n; c++) stickers.push({ index: fi * n * n + r * n + c, points: corners(r, c, 0.86) });
    }
    out.push({ face, outline: corners((n - 1) / 2, (n - 1) / 2, n), stickers });
  }
  return out;
}

// Returns an <svg> of a 6*n*n state that the viewer turns by dragging with the mouse or a finger.
function cube3d(state, n, attrs) {
  const r = n * Math.sqrt(3) + 0.5;
  const root = svg("svg", { viewBox: `${-r} ${-r} ${2 * r} ${2 * r}`, class: "cube3d", ...attrs });
  if (!cubeSize(state) || cubeSize(state) !== n) return root;
  let { yaw, pitch } = VIEW_3D;
  const draw = () => {
    const nodes = [];
    for (const f of cube3dFaces(n, yaw, pitch)) {
      nodes.push(svg("polygon", { points: pointList(f.outline), fill: "#1b1f27", stroke: "#1b1f27", "stroke-width": 0.2, "stroke-linejoin": "round" }));
      for (const s of f.stickers) nodes.push(svg("polygon", { points: pointList(s.points), fill: STICKERS[state[s.index]] || "#999" }));
    }
    root.replaceChildren(...nodes);
  };
  let last = null;
  root.addEventListener("pointerdown", (e) => { last = [e.clientX, e.clientY]; root.setPointerCapture(e.pointerId); });
  root.addEventListener("pointermove", (e) => {
    if (!last) return;
    // One full turn per 400 screen pixels in either direction.
    yaw += ((e.clientX - last[0]) / 400) * 2 * Math.PI;
    pitch += ((e.clientY - last[1]) / 400) * 2 * Math.PI;
    last = [e.clientX, e.clientY];
    draw();
  });
  const stop = () => { last = null; };
  root.addEventListener("pointerup", stop);
  root.addEventListener("pointercancel", stop);
  draw();
  return root;
}

if (typeof module !== "undefined") {
  module.exports = { STICKERS, FACE_ORDER, NET_POS, ISO_FACES, svg, solvedState, cubeSize, cubeNet, cubeNetNamed, cubeIso, isoStickers, cube3d, cube3dFaces, VIEW_3D };
}
