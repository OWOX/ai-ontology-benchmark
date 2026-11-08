// Spec: docs/specs/ui.md (Definition icons, How to test)
// Loads ui/static/definitions.js in a bare context with a small fake DOM. Checks the icon's aria-label and that
// keepFocus puts focus back on the same term in the same table after a rebuild. Exits 1 on any failure.
import fs from "node:fs";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const file = fileURLToPath(new URL("../../ui/static/definitions.js", import.meta.url));
const document = { activeElement: null };
function node(tag, attrs = {}, ...kids) {
  const n = { tag, attrs, kids: [], parent: null };
  n.getAttribute = (k) => (k in attrs ? attrs[k] : null);
  n.classList = { contains: (c) => String(attrs.class || "").split(/\s+/).includes(c) };
  n.append = (...more) => more.forEach((k) => { k.parent = n; n.kids.push(k); });
  n.addEventListener = () => {};
  n.focus = () => { document.activeElement = n; };
  n.blur = () => {};
  n.closest = (t) => { for (let p = n; p; p = p.parent) if (p.tag === t) return p; return null; };
  n.contains = (o) => { for (let p = o; p; p = p.parent) if (p === n) return true; return false; };
  const walk = (m, out) => { m.kids.forEach((k) => { out.push(k); walk(k, out); }); return out; };
  n.querySelectorAll = (sel) => walk(n, []).filter((k) => (sel[0] === "." ? k.classList.contains(sel.slice(1)) : k.tag === sel));
  n.append(...kids.filter((k) => k && typeof k === "object"));
  return n;
}
const window = {};
const UI = { el: (tag, props = {}, ...kids) => node(tag, props, ...kids.flat()), tipOn() {} };
const ctx = vm.createContext({ window, document, UI });
vm.runInContext(fs.readFileSync(file, "utf8"), ctx);
const { infoTerm, keepFocus } = window.Defs;

let failed = 0;
function check(name, ok) { if (!ok) { failed++; console.error(`FAIL ${name}`); } }

const defs = { terms: {
  Precision: { text: "The share of right answers.", source: "https://example.test/d.md#metrics" },
  Coverage: { text: "The share of classified answers." },
} };
const iconOf = (term) => infoTerm(defs, term).find((n) => n && n.kids).kids[0];
check("a linked icon is labelled with its term", iconOf("Precision").getAttribute("aria-label") === "Definition of Precision");
check("an icon without a source is labelled with its term", iconOf("Coverage").getAttribute("aria-label") === "Definition of Coverage");

// Two tables with the same terms. The page draws them again after a job ends.
const tables = () => ["summary", "metrics"].map((key) => node("table", { "data-table": key },
  node("th", {}, iconOf("Precision")), node("th", {}, iconOf("Coverage"))));
const container = node("div");
const first = tables();
container.append(...first);
const icon = (t, term) => t.querySelectorAll(".info").find((i) => i.getAttribute("data-term") === term);
icon(first[1], "Coverage").focus();
const back = keepFocus(container);
container.kids.length = 0;
const second = tables().reverse();  // the order differs, so an index would pick the wrong table
container.append(...second);
back();
const metrics = second.find((t) => t.getAttribute("data-table") === "metrics");
check("focus returns to the same term", document.activeElement && document.activeElement.getAttribute("data-term") === "Coverage");
check("focus returns in the same table", document.activeElement === icon(metrics, "Coverage"));

document.activeElement = node("button");
check("focus outside an icon is left alone", keepFocus(container)() === undefined && document.activeElement.tag === "button");
process.exit(failed ? 1 : 0);
