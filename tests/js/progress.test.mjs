// Spec: docs/specs/ui.md (Polling 3)
// Loads ui/static/progress.js in a bare context and checks which attempts it infers are in flight. Exits 1 on any failure.
import fs from "node:fs";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const file = fileURLToPath(new URL("../../ui/static/progress.js", import.meta.url));
const window = {};
vm.runInNewContext(fs.readFileSync(file, "utf8"), { window, UI: { el: () => null } });
const { inFlight } = window.Progress;

let failed = 0;
function check(name, got, want) {
  if (JSON.stringify(got) !== JSON.stringify(want)) { failed++; console.error(`FAIL ${name}\n  got:  ${JSON.stringify(got)}\n  want: ${JSON.stringify(want)}`); }
}

const snap = { setups: ["no_model", "descriptive"], attempts: 2, inputs: [{ input_id: "a" }, { input_id: "b" }] };
// Loop order: input, then setup, then attempt number.
const order = ["m|a|no_model|1", "m|a|no_model|2", "m|a|descriptive|1", "m|a|descriptive|2", "m|b|no_model|1"];
const none = () => false;

check("one is the first pending", inFlight(snap, "m", 1, none), order.slice(0, 1));
check("four are the first four", inFlight(snap, "m", 4, none), order.slice(0, 4));
check("the first N after records", inFlight(snap, "m", 3, (k) => k === order[0] || k === order[2]), [order[1], order[3], order[4]]);
check("a gap in the records is filled first", inFlight(snap, "m", 2, (k) => k === order[0]), order.slice(1, 3));
check("fewer left than N", inFlight(snap, "m", 4, (k) => !["m|b|descriptive|1", "m|b|descriptive|2"].includes(k)),
  ["m|b|descriptive|1", "m|b|descriptive|2"]);
check("nothing left", inFlight(snap, "m", 4, () => true), []);
check("keyed by model", inFlight(snap, "other", 1, none), ["other|a|no_model|1"]);

process.exit(failed ? 1 : 0);
