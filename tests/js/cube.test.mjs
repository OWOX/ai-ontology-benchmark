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
const { cubeNet, cubeNetNamed, solvedState } = ctx.module.exports;

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

if (failed) process.exit(1);
console.log("cube tests passed");
