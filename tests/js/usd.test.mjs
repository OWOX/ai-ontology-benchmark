// Spec: docs/specs/ui.md (How to test)
// Checks UI.usdWhole, UI.estimateHint, and UI.usd against what each page printed before they shared it: the Experiments, Benchmarks, Models, and New
// Experiment screens each pass their own options. Exits 1 on any failure.
import { loadRouter } from "./load_router.mjs";

const { UI } = loadRouter();

let failed = 0;
function check(name, got, want) {
  if (got !== want) { failed++; console.error(`FAIL ${name}\n  got:  ${got}\n  want: ${want}`); }
}
const cases = (page, opts, rows) => { for (const [value, want] of rows) check(`${page}: ${String(value)}`, UI.usd(value, opts), want); };

// Experiments: a number to 2 places with toFixed, n/a for anything else. NaN and Infinity are numbers.
cases("experiments", { fixed: 2 }, [
  [0, "$0.00"], [0.0042, "$0.00"], [1.5, "$1.50"], [12.345, "$12.35"], [1234567.891, "$1234567.89"], [-3.5, "$-3.50"],
  [1e21, "$1e+21"], [null, "n/a"], [undefined, "n/a"], [NaN, "$NaN"], [Infinity, "$Infinity"], ["3.2", "n/a"],
]);

// Benchmarks: cost per success, always a number, to 2 places with toFixed and no grouping.
cases("benchmarks", { fixed: 2 }, [
  [0, "$0.00"], [0.0042, "$0.00"], [1.5, "$1.50"], [12.345, "$12.35"], [1234567.891, "$1234567.89"], [-3.5, "$-3.50"],
]);

// Models: the browser's own locale. The pytest wrapper runs this script with LC_ALL=de_DE.UTF-8, so a fixed en-GB
// would show here as "1,234,567.891" instead of "1.234.567,891".
if (Intl.NumberFormat().resolvedOptions().locale !== "de-DE") { failed++; console.error("FAIL run with LC_ALL=de_DE.UTF-8"); }
cases("models", { locale: "browser", maxDecimals: 4 }, [
  [0, "$0,00"], [0.0042, "$0,0042"], [1.5, "$1,50"], [12.345, "$12,345"], [1234567.891, "$1.234.567,891"], [-3.5, "$-3,50"],
  [0.00005, "$0,0001"], ["0.0042", "$0,0042"], ["2.5", "$2,50"], [NaN, "$NaN"], [Infinity, "$∞"], [-Infinity, "$-∞"],
]);

// New Experiment: en-GB, 2 places (4 below one), and the amount as printed for inf, nan, and amounts too small for 4 places.
cases("new", { verbatim: true, maxBelowOne: 4 }, [
  [0, "$0.00"], [0.0042, "$0.0042"], [1.5, "$1.50"], [12.345, "$12.35"], [1234567.891, "$1,234,567.89"], [-3.5, "$-3.50"],
  [0.00005, "$0.0001"], [1e21, "$1,000,000,000,000,000,000,000.00"], ["0.0042", "$0.0042"], ["1e-05", "$1e-05"],
  ["inf", "$inf"], ["nan", "$nan"], ["0", "$0.00"], ["2.50", "$2.50"], ["1234.5", "$1,234.50"], ["0.99999", "$1.00"], [NaN, "$NaN"],
]);


// Estimate table: whole dollars, "<$1" for a value above 0 and below $0.50, n/a for anything but a finite number.
for (const [value, want] of [
  [0, "$0"], [0.0001, "<$1"], [0.49, "<$1"], [0.5, "$1"], [0.99, "$1"], [616.2, "$616"], [1177.6, "$1,178"], [1234567.4, "$1,234,567"],
  [null, "n/a"], [undefined, "n/a"], [NaN, "n/a"], [Infinity, "n/a"], ["3", "n/a"],
]) check(`usdWhole: ${String(value)}`, UI.usdWhole(value), want);

// The hint the Estimation block shows when it cannot estimate.
for (const [puzzles, models, want] of [
  [0, 0, "Select at least one puzzle and one AI model to see the estimate."],
  [3, 0, "Select at least one AI model to see the estimate."],
  [0, 2, "Select at least one puzzle to see the estimate."],
  [1, 1, ""],
]) check(`estimateHint: ${puzzles}, ${models}`, UI.estimateHint(puzzles, models), want);

process.exit(failed ? 1 : 0);
