// Spec: docs/specs/ui.md (Puzzles)
// Loads ui/static/cube.js with a minimal fake DOM and checks that cubeNetNamed labels follow the
// sticker order cubeNet draws. Exits 1 on any failure.
import fs from "node:fs";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const file = fileURLToPath(new URL("../../ui/static/cube.js", import.meta.url));
class Node {
  constructor(tag) { this.tag = tag; this.attrs = {}; this.children = []; this.textContent = ""; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  append(...kids) { this.children.push(...kids); }
}
const document = { createElementNS: (ns, tag) => new Node(tag) };
const ctx = { document, module: { exports: {} } };
vm.runInNewContext(fs.readFileSync(file, "utf8"), ctx);
const { cubeNet, cubeNetNamed, solvedState, cube3dFaces, VIEW_3D, turnedStickers, cubeIsoTurn } = ctx.module.exports;

let failed = 0;
function check(name, ok, got) {
  if (!ok) { failed++; console.error(`FAIL ${name}\n  got: ${got}`); }
}

for (const n of [2, 3]) {
  const named = cubeNetNamed(n);
  const texts = named.children.filter((c) => c.tag === "text");
  const rects = cubeNet(solvedState(n)).children;
  const labels = texts.map((t) => t.textContent);
  check(`${n}: label count`, labels.length === 6 * n * n, labels.length);
  check(`${n}: first and last faces`, labels.includes("U1") && labels.includes(`U${n * n}`) && labels.includes(`B${n * n}`) && labels.includes(`D${n * n}`), labels.join());
  check(`${n}: labels unique`, new Set(labels).size === labels.length, labels.join());
  texts.forEach((t, i) => {
    const r = rects[i].attrs;
    const x = Number(t.attrs.x), y = Number(t.attrs.y);
    const inside = x > Number(r.x) && x < Number(r.x) + Number(r.width) && y > Number(r.y) && y < Number(r.y) + Number(r.height);
    const want = "URFDLB"[Math.floor(i / (n * n))] + ((i % (n * n)) + 1);
    check(`${n}: label ${i} sits on its sticker and is named ${want}`, inside && t.textContent === want, `${t.textContent} at ${x},${y} vs rect ${JSON.stringify(r)}`);
  });
}
check("non-cube size draws nothing", cubeNetNamed(0).children.length === 0, "");

const shown = (yaw, pitch) => cube3dFaces(3, yaw, pitch).map((f) => f.face).sort().join("");
check("3D view starts on U, F, and R", shown(VIEW_3D.yaw, VIEW_3D.pitch) === "FRU", shown(VIEW_3D.yaw, VIEW_3D.pitch));
check("3D view turned half a turn shows U, B, and L", shown(VIEW_3D.yaw + Math.PI, VIEW_3D.pitch) === "BLU", shown(VIEW_3D.yaw + Math.PI, VIEW_3D.pitch));
check("3D view tipped over shows D", shown(VIEW_3D.yaw, -VIEW_3D.pitch).includes("D"), shown(VIEW_3D.yaw, -VIEW_3D.pitch));
// U's first sticker (back-left corner) sits above and left of its last one in the start view.
const u = cube3dFaces(3, VIEW_3D.yaw, VIEW_3D.pitch).find((f) => f.face === "U").stickers;
const centre = (s) => s.points.reduce((a, p) => [a[0] + p[0] / 4, a[1] + p[1] / 4], [0, 0]);
check("U1 is behind U9", centre(u[0])[1] < centre(u[8])[1], JSON.stringify([centre(u[0]), centre(u[8])]));

// A finished turn puts each sticker where the engine's permutation does (src/puzzles/cube.py, checked for
// every move by hand): on the 3x3, R moves F3 (index 20) to U3 (index 2), R' moves U9 (index 8) to F9
// (index 26), and R2 moves F3 to B7 (index 51).
const landed = (n, move, from) => {
  const base = turnedStickers(n, move, 0), end = turnedStickers(n, move, 1);
  return base.findIndex((b) => b.mid.every((v, k) => Math.abs(v - end[from].mid[k]) < 1e-9) && b.normal.every((v, k) => Math.abs(v - end[from].normal[k]) < 1e-9));
};
check("R moves F3 to U3", landed(3, "R", 20) === 2, landed(3, "R", 20));
check("R' moves U9 to F9", landed(3, "R'", 8) === 26, landed(3, "R'", 8));
check("R2 moves F3 to B7", landed(3, "R2", 20) === 51, landed(3, "R2", 20));
check("a turn at progress 0 and 1 moves 21 stickers, the outer layer", turnedStickers(3, "U", 1).filter((s) => s.moving).length === 21, "");
check("a move that is not a face turn draws the plain view", cubeIsoTurn("U".repeat(9) + "R".repeat(45), 3, "X", 0.5).children.length === 27, "");

if (failed) process.exit(1);
console.log("cube tests passed");
