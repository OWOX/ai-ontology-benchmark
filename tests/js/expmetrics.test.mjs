// Spec: docs/specs/ui.md (Experiments 4)
// Loads ui/static/expmetrics.js in a bare context and checks the `*` mark and note on the Summary. Exits 1 on any failure.
import fs from "node:fs";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const file = fileURLToPath(new URL("../../ui/static/expmetrics.js", import.meta.url));
const el = (tag, props = {}, ...kids) => {
  const node = { tag, props, kids: [...kids] };
  node.append = (...more) => node.kids.push(...more);
  return node;
};
const window = {};
vm.runInNewContext(fs.readFileSync(file, "utf8"), { window, UI: { el } });
const { summary, NOTE, SUMMARY_NOTE } = window.ExpMetrics;

const text = (n) => (typeof n === "string" ? n : [n.props?.text ?? "", ...n.kids.map(text)].join("|"));
const row = { model: "m", setup: "no_model", validity: "valid", attempts: 4, success_rate: 0.5,
  success_rate_low: 0.1, success_rate_high: 0.9, success_rate_n: 4 };
const detail = (source) => ({ id: "e", metrics_source: source, summary_rows: [row], metric_rows: [] });

let failed = 0;
function check(name, ok) { if (!ok) { failed++; console.error(`FAIL ${name}`); } }

const fromReport = text(summary(detail("report"), []));
check("report summary marks the interval", fromReport.includes("(10.0\u201390.0) n=4 *"));
check("report summary shows the Wilson note", fromReport.includes(SUMMARY_NOTE) && !fromReport.includes(NOTE));
const computed = text(summary(detail("computed"), []));
check("computed summary marks the interval", computed.includes("(10.0\u201390.0) n=4 *"));
check("computed summary shows the computed note", computed.includes(NOTE) && !computed.includes(SUMMARY_NOTE));
process.exit(failed ? 1 : 0);
