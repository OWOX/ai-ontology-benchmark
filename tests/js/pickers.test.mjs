// Spec: docs/specs/ui.md (How to test)
// Checks UI.dropdown and UI.checkPicker from router.js on a stub DOM: the select, its label and value, and its handler;
// the picker's summary, the disabled last box, the values a toggle reports, and the reopen key. Exits 1 on any failure.
import { loadRouter } from "./load_router.mjs";

const { UI } = loadRouter();

let failed = 0;
function check(name, got, want) {
  if (JSON.stringify(got) !== JSON.stringify(want)) { failed++; console.error(`FAIL ${name}\n  got:  ${JSON.stringify(got)}\n  want: ${JSON.stringify(want)}`); }
}
const byTag = (root, tag) => root.find((n) => n.tag === tag);

// dropdown: a label holding the name and a select whose options are the given pairs.
{
  const seen = [];
  const label = UI.dropdown("Validity", "valid", UI.validityOptions("all"), (v) => seen.push(v));
  const select = byTag(label, "select")[0];
  check("dropdown: label text", label.textContent.startsWith("Validity "), true);
  check("dropdown: aria-label", select.attrs["aria-label"], "Validity");
  check("dropdown: options", byTag(select, "option").map((o) => [o.attrs.value, o.textContent]),
    [["all", "all inputs"], ["valid", "valid only"], ["invalid", "invalid only"]]);
  check("dropdown: initial value", select.value, "valid");
  select.value = "invalid"; select.fire("change");
  check("dropdown: handler gets the chosen value", seen, ["invalid"]);
}

// checkPicker
const OPTIONS = [["a", "Alpha"], ["b", "Beta"], ["c", "Gamma"]];
function picker(selected, state = { key: null }, onChange = () => {}) {
  const root = UI.checkPicker("Setups", OPTIONS, selected, onChange, state, "every setup");
  const details = byTag(root, "details")[0];
  return { root, details, summary: byTag(details, "summary")[0].textContent, boxes: byTag(details, "input") };
}
check("summary: none selected", picker([]).summary, "0 of 3");
check("summary: one selected shows its text", picker(["b"]).summary, "Beta");
check("summary: several selected", picker(["a", "c"]).summary, "2 of 3");
check("summary: all selected uses allText", picker(["a", "b", "c"]).summary, "every setup");

check("only box ticked is disabled", picker(["b"]).boxes.map((b) => [b.checked, b.disabled]), [[false, false], [true, true], [false, false]]);
check("two ticked, none disabled", picker(["a", "b"]).boxes.map((b) => b.disabled), [false, false, false]);

{
  const seen = [], state = { key: null };
  const { boxes, details } = picker(["a"], state, (v) => seen.push(v));
  check("closed before a toggle", details.open, false);
  boxes[2].checked = true; boxes[2].fire("change");
  check("ticking reports the values in option order", seen[0], ["a", "c"]);
  check("the toggled box is remembered", state.key, "Setups|c");
  const again = picker(["a", "c"], state);
  check("the redrawn picker opens", again.details.open, true);
  check("the toggled box takes focus", again.boxes.map((b) => !!b.focused), [false, false, true]);
  check("the key is consumed", state.key, null);
  check("the next draw stays closed", picker(["a", "c"], state).details.open, false);

  const other = { key: "Models|x" };
  check("another picker's key is left alone", [picker(["a"], other).details.open, other.key], [false, "Models|x"]);

  const clear = { key: null }, cleared = [];
  const p = picker(["a", "b"], clear, (v) => cleared.push(v));
  p.boxes[0].checked = false; p.boxes[0].fire("change");
  check("clearing reports the rest", cleared[0], ["b"]);
}

process.exit(failed ? 1 : 0);
