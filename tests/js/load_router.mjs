// Spec: docs/specs/ui.md (How to test)
// Loads ui/static/router.js in a bare context with a small DOM stub and returns { UI, document }. The stub keeps what
// the helpers read back: attributes, children, className, textContent, value, checked, disabled, open, and listeners.
import fs from "node:fs";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const file = fileURLToPath(new URL("../../ui/static/router.js", import.meta.url));

function node(tag) {
  const n = {
    tag, attrs: {}, children: [], listeners: {}, className: "", _text: "", value: "", checked: false, disabled: false, open: false,
    setAttribute(k, v) { this.attrs[k] = String(v); if (k === "value") this.value = String(v); },
    append(...kids) { for (const k of kids) this.children.push(typeof k === "string" ? { tag: "#text", textContent: k, children: [] } : k); },
    addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); },
    focus() { this.focused = true; },
    fire(ev) { for (const fn of this.listeners[ev] || []) fn({ target: this, preventDefault() {} }); },
    get firstChild() { return this.children[0] || null; },
    get textContent() { return this._text !== "" ? this._text : this.children.map((c) => c.textContent).join(""); },
    set textContent(v) { this._text = String(v); },
    find(pred, out = []) { for (const c of this.children) { if (pred(c)) out.push(c); c.find && c.find(pred, out); } return out; },
  };
  return n;
}

export function loadRouter() {
  const document = {
    createElement: node,
    getElementById: () => node("div"),
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener() {},
  };
  const window = { addEventListener() {} };
  const context = { window, document, location: { hash: "" }, localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    requestAnimationFrame: (fn) => fn(), fetch: async () => ({ ok: false }), URLSearchParams, setTimeout: () => 0, setInterval: () => 0 };
  vm.runInNewContext(fs.readFileSync(file, "utf8"), context);
  return { UI: window.UI, document };
}
