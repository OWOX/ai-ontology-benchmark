// Spec: docs/specs/ui.md (Experiments 4)
// Loads ui/static/expmetrics.js in a bare context and checks the `*` mark and note on the Summary. Exits 1 on any failure.
import fs from "node:fs";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { loadRouter } from "./load_router.mjs";

const file = fileURLToPath(new URL("../../ui/static/expmetrics.js", import.meta.url));
const el = (tag, props = {}, ...kids) => {
  const node = { tag, props, kids: [...kids] };
  node.append = (...more) => node.kids.push(...more);
  node.addEventListener = () => {};
  return node;
};
const window = {};
const ctx = vm.createContext({ window, UI: { el, usd: loadRouter().UI.usd, tipOn() {} } });
vm.runInContext(fs.readFileSync(fileURLToPath(new URL("../../ui/static/definitions.js", import.meta.url)), "utf8"), ctx);
ctx.Defs = window.Defs;
vm.runInContext(fs.readFileSync(file, "utf8"), ctx);
const { summary, NOTE, SUMMARY_NOTE } = window.ExpMetrics;

const text = (n) => (typeof n === "string" ? n : [n.props?.text ?? "", ...n.kids.map(text)].join("|"));
const row = { model: "m", setup: "no_model", validity: "valid", attempts: 4, precision: 0.5,
  precision_low: 0.1, precision_high: 0.9, precision_n: 4 };
const detail = (source) => ({ id: "e", metrics_source: source, summary_rows: [row], metric_rows: [] });

let failed = 0;
function check(name, ok) { if (!ok) { failed++; console.error(`FAIL ${name}`); } }

const fromReport = text(summary(detail("report"), []));
check("report summary marks the interval", fromReport.includes("(10.0\u201390.0) n=4 *"));
check("report summary shows the Wilson note", fromReport.includes(SUMMARY_NOTE) && !fromReport.includes(NOTE));
const computed = text(summary(detail("computed"), []));
check("computed summary marks the interval", computed.includes("(10.0\u201390.0) n=4 *"));
check("computed summary shows the computed note", computed.includes(NOTE) && !computed.includes(SUMMARY_NOTE));
// A header with a definition gets the icon and its tooltip, and one without gets none.
const defs = { terms: { Precision: { text: "The share of right answers.", source: "https://example.test/d.md#metrics" } } };
const withIcon = text(summary(detail("report"), [], defs));
check("a defined header has its tooltip", withIcon.includes("The share of right answers."));
check("an undefined header has no icon", !text(summary(detail("report"), [], { terms: {} })).includes("|i"));
process.exit(failed ? 1 : 0);
