// Spec: docs/specs/ui.md (Menu 5, Definition icons, How to test)
// Loads ui/static/router.js with a fake DOM and fake timers and checks the shared tooltip helper UI.tipOn: the panel
// stays 500 ms after the pointer leaves the source, stays while the pointer is on it, closes the previous panel at
// once, and follows keyboard focus. Exits 1 on any failure.
import fs from "node:fs";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const file = fileURLToPath(new URL("../../ui/static/router.js", import.meta.url));

let now = 0, nextId = 1;
const timers = new Map();
const fake = {
  setTimeout(fn, ms) { const id = nextId++; timers.set(id, { at: now + ms, fn }); return id; },
  clearTimeout(id) { timers.delete(id); },
  advance(ms) {
    now += ms;
    for (const [id, t] of [...timers]) if (t.at <= now && timers.has(id)) { timers.delete(id); t.fn(); }
  },
};

function node() {
  const classes = new Set(), listeners = {};
  return {
    listeners, style: {}, offsetWidth: 100, offsetHeight: 40, children: [], _text: "",
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c) },
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    fire(ev) { for (const fn of listeners[ev] || []) fn({ target: this }); },
    getBoundingClientRect: () => ({ left: 10, right: 20, top: 10, bottom: 20 }),
    append() {}, replaceChildren() {}, setAttribute() {},
    get textContent() { return this._text; }, set textContent(v) { this._text = v; },
    get open() { return classes.has("open"); },
  };
}

const docListeners = {};
const document = { createElement: node, getElementById: () => node(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener(ev, fn) { (docListeners[ev] = docListeners[ev] || []).push(fn); } };
const window = { addEventListener() {}, innerWidth: 1000, innerHeight: 800 };
const context = { window, document, location: { hash: "" }, localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  requestAnimationFrame: (fn) => fn(), fetch: async () => ({ ok: false }), URLSearchParams,
  setTimeout: fake.setTimeout, clearTimeout: fake.clearTimeout, setInterval: () => 0 };
vm.runInNewContext(fs.readFileSync(file, "utf8"), context);
const { UI } = window;

let failed = 0;
const check = (name, ok) => { if (!ok) { failed++; console.error(`FAIL ${name}`); } };

function pair() {
  const src = node(), tip = node();
  src.nextElementSibling = tip;
  UI.tipOn(src);
  return { src, tip };
}

{
  const { src, tip } = pair();
  src.fire("mouseenter");
  check("hover opens the panel", tip.open);
  src.fire("mouseleave");
  fake.advance(499);
  check("the panel stays open for 500 ms after leaving", tip.open);
  fake.advance(2);
  check("the panel closes after 500 ms", !tip.open);
}
{
  const { src, tip } = pair();
  src.fire("mouseenter"); src.fire("mouseleave");
  fake.advance(300);
  tip.fire("mouseenter");
  fake.advance(5000);
  check("the panel stays open while the pointer is on it", tip.open);
  tip.fire("mouseleave");
  fake.advance(499);
  check("leaving the panel starts the same delay", tip.open);
  fake.advance(2);
  check("the panel closes 500 ms after leaving it", !tip.open);
}
{
  const { src, tip } = pair();
  src.fire("mouseenter"); src.fire("mouseleave");
  fake.advance(400);
  src.fire("mouseenter");
  fake.advance(400);
  check("re-entering the source cancels the pending close", tip.open);
}
{
  const a = pair(), b = pair();
  a.src.fire("mouseenter"); a.src.fire("mouseleave");
  b.src.fire("mouseenter");
  check("opening another panel closes the previous one at once", !a.tip.open && b.tip.open);
  fake.advance(1000);
  check("the old timer does not close the new panel", b.tip.open);
}
{
  const { src, tip } = pair();
  src.fire("focus");
  check("focus opens the panel", tip.open);
  src.fire("blur");
  check("blur closes the panel at once", !tip.open);
}
{
  const { src, tip } = pair();
  src.fire("mouseenter");
  tip.fire("mouseenter");
  src.fire("blur"); // a click on the panel blurs the source
  check("blur does not close a panel the pointer is on", tip.open);
}

{
  const a = pair(), b = pair();
  a.src.fire("mouseenter");
  b.src.fire("blur"); // another icon losing focus
  check("blur of another source leaves the open panel", a.tip.open);
  a.src.fire("mouseleave");
  fake.advance(1000);
}
{
  const { src, tip } = pair();
  src.fire("focus");
  src.fire("mouseenter"); src.fire("mouseleave");
  fake.advance(5000);
  check("a focused icon keeps its panel after the pointer leaves", tip.open);
  src.fire("blur");
  check("blur then closes it", !tip.open);
}
{
  const { src, tip } = pair();
  src.fire("focus");
  tip.fire("mouseenter"); tip.fire("mouseleave");
  fake.advance(5000);
  check("a focused icon keeps its panel after the pointer leaves the panel", tip.open);
  src.fire("blur");
}
{
  const { src, tip } = pair();
  src.fire("mouseenter");
  for (const fn of docListeners.keydown) fn({ key: "a" });
  check("another key leaves the panel", tip.open);
  for (const fn of docListeners.keydown) fn({ key: "Escape" });
  check("Escape closes the panel", !tip.open);
  src.fire("focus");
  for (const fn of docListeners.keydown) fn({ key: "Escape" });
  check("Escape closes a focused panel", !tip.open);
}
{
  const { src, tip } = pair();
  const box = { contains: (n) => n === src }, other = { contains: () => false };
  check("tipHolds is false with nothing open", !UI.tipHolds(box));
  src.fire("mouseenter");
  check("tipHolds is true for the container of the open source", UI.tipHolds(box) && !UI.tipHolds(other));
  let closed = 0;
  UI.afterTipClose(() => { closed++; });
  src.fire("mouseleave");
  check("tipHolds stays true during the delay", UI.tipHolds(box) && closed === 0);
  fake.advance(501);
  check("afterTipClose runs once when the panel closes", closed === 1 && !UI.tipHolds(box) && !tip.open);
}

if (failed) process.exit(1);
console.log("tips ok");
