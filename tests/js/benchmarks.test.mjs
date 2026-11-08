// Spec: docs/specs/ui.md (Benchmarks 1 and 2, How to test 31)
// Loads ui/static/pages/benchmarks.js in a bare context and checks which cell is coloured under each tier and which
// models a request asks for. Exits 1 on any failure.
import fs from "node:fs";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const file = fileURLToPath(new URL("../../ui/static/pages/benchmarks.js", import.meta.url));
const window = {};
const UI = { el: () => null, registerPage: () => {}, jobs: [], validityOptions: () => [], onJobs: () => () => {} };
vm.runInNewContext(fs.readFileSync(file, "utf8"), { window, UI, document: { addEventListener: () => {} } });
const { verdict, chosenModels, selectionFromQuery, headerState, toggleProvider, toggleModel, summaryText, paramsFromSelection } = window.Benchmarks;

let failed = 0;
function check(name, got, want) {
  if (JSON.stringify(got) !== JSON.stringify(want)) { failed++; console.error(`FAIL ${name}\n  got:  ${JSON.stringify(got)}\n  want: ${JSON.stringify(want)}`); }
}
const side = (model, extra) => ({ model, against: "b", p_value: 0.004, p_holm: 0.008, inputs_paired: 20, agrees: true, ...extra });
const row = (best, worst, tested = true) => ({ tested, best: best && [].concat(best), worst: worst && [].concat(worst) });
const who = (vs) => vs.length ? vs.map((v) => v.model).join(",") : null;
const tip = (vs) => vs[0].tip;

// Under a tier: coloured only when p_holm is below the threshold and the sign test agrees.
const sig = row(side("a"), side("c", { p_holm: 0.04 }));
check("significant: below 0.05 and agrees", who(verdict(sig, "best", "significant")), "a");
check("significant: 0.04 is below 0.05", who(verdict(sig, "worst", "significant")), "c");
check("strong: 0.008 is below 0.01", who(verdict(sig, "best", "strong")), "a");
check("strong: 0.04 is not below 0.01", who(verdict(sig, "worst", "strong")), null);
check("weak: 0.04 is below 0.10", who(verdict(sig, "worst", "weak")), "c");
check("p_holm on the threshold is not below it", who(verdict(row(side("a", { p_holm: 0.05 }), null), "best", "significant")), null);
check("not agreeing is never coloured", who(verdict(row(side("a", { agrees: false }), null), "best", "weak")), null);
check("missing p_holm is never coloured", who(verdict(row(side("a", { p_holm: null }), null), "best", "weak")), null);
check("an untested row is never coloured under a tier", who(verdict(row({ model: "a", against: null }, null, false), "best", "weak")), null);
check("no side, no verdict", who(verdict(row(null, null), "best", "all")), null);

// Under All: best and worst are always coloured, even when the test is weak, disagrees, or is missing.
check("all: not significant, not agreeing", who(verdict(row(side("a", { p_holm: 0.9, agrees: false }), null), "best", "all")), "a");
check("all: untested row", who(verdict(row({ model: "a" }, { model: "c" }, false), "worst", "all")), "c");
check("all: best tip without a test", tip(verdict(row({ model: "a" }, null, false), "best", "all")), "Best in this row.");
check("all: worst tip without a test", tip(verdict(row(null, { model: "c" }, false), "worst", "all")), "Worst in this row.");
check("a tie at the top colours every tied model", who(verdict(row([side("a"), side("d")], null), "best", "significant")), "a,d");
check("a tie is gated per model", who(verdict(row([side("a"), side("d", { p_holm: 0.2 })], null), "best", "significant")), "a");
check("tip names the test", tip(verdict(sig, "best", "all")), "Better than b: p = 0.004 (Holm 0.008), 20 inputs paired.");

// Models to ask for: the chosen ones among the chosen providers, and null for no filter.
const options = { providers: [{ name: "anthropic", models: ["claude-a", "claude-b"] }, { name: "openai", models: ["gpt-a"] }] };
const pick = (c) => chosenModels({ providers: [], models: [], ...c }, options);
check("nothing chosen is no filter", pick({}), null);
check("one provider", pick({ providers: ["openai"] }), ["gpt-a"]);
check("models among all providers", pick({ models: ["claude-b", "gpt-a"] }), ["claude-b", "gpt-a"]);
check("every model chosen is no filter", pick({ models: ["claude-a", "claude-b", "gpt-a"] }), null);
check("stale models that match none are no filter", pick({ models: ["gone"] }), null);
check("stale models under a provider mean that provider", pick({ providers: ["openai"], models: ["claude-a"] }), ["gpt-a"]);
check("a stale name beside a live one is ignored", pick({ models: ["gone", "claude-a"] }), ["claude-a"]);
check("without options, models alone are kept", chosenModels({ providers: [], models: ["x"] }, null), ["x"]);
check("without options, providers mean no list", chosenModels({ providers: ["openai"], models: ["x"] }, null), null);

// The AI models dropdown: one selection of model names, grouped by provider.
const o3 = { providers: [{ name: "anthropic", models: ["claude-a", "claude-b"] }, { name: "openai", models: ["gpt-a"] }] };
const [anth, oai] = o3.providers;
const from = (c) => selectionFromQuery({ providers: [], models: [], ...c }, o3);
check("header: none", headerState(anth, ["gpt-a"]), "none");
check("header: mixed", headerState(anth, ["claude-b"]), "mixed");
check("header: all", headerState(anth, ["claude-a", "claude-b", "gpt-a"]), "all");
check("toggle: mixed selects all of the provider", toggleProvider(o3, ["claude-b"], "anthropic"), ["claude-a", "claude-b"]);
check("toggle: none selects all, keeping others", toggleProvider(o3, ["gpt-a"], "anthropic"), ["claude-a", "claude-b", "gpt-a"]);
check("toggle: all clears the provider only", toggleProvider(o3, ["claude-a", "claude-b", "gpt-a"], "anthropic"), ["gpt-a"]);
check("toggle model", toggleModel(o3, ["gpt-a"], "claude-b", true), ["claude-b", "gpt-a"]);
check("summary: all", summaryText(o3, ["claude-a", "claude-b", "gpt-a"]), "all");
check("summary: one whole provider", summaryText(o3, ["gpt-a"]), "openai");
check("summary: one whole provider, two models", summaryText(o3, ["claude-a", "claude-b"]), "anthropic");
check("summary: part of a provider", summaryText(o3, ["claude-a"]), "1 of 3");
check("summary: a whole provider and another model", summaryText(o3, ["claude-a", "claude-b", "gpt-a"].slice(0, 2).concat([])), "anthropic");
check("summary: k of n", summaryText({ providers: [anth, oai, { name: "g", models: ["g-a"] }] }, ["claude-a", "claude-b", "g-a"]), "3 of 4");
check("params: all selected", paramsFromSelection(o3, ["claude-a", "claude-b", "gpt-a"]), { providers: ["anthropic", "openai"], models: null });
check("params: one provider", paramsFromSelection(o3, ["gpt-a"]), { providers: ["openai"], models: ["gpt-a"] });
check("params: part of two providers", paramsFromSelection(o3, ["claude-b", "gpt-a"]), { providers: ["anthropic", "openai"], models: ["claude-b", "gpt-a"] });
check("params match the old request", paramsFromSelection(o3, from({ providers: ["openai"] })).models, chosenModels({ providers: ["openai"], models: [] }, o3));
check("old hash: nothing is all", from({}), ["claude-a", "claude-b", "gpt-a"]);
check("old hash: providers alone", from({ providers: ["anthropic"] }), ["claude-a", "claude-b"]);
check("old hash: providers with models", from({ providers: ["anthropic"], models: ["claude-b", "gpt-a"] }), ["claude-b"]);
check("new hash: models alone", from({ models: ["gpt-a", "claude-a"] }), ["claude-a", "gpt-a"]);
check("old hash: stale models mean the providers", from({ providers: ["openai"], models: ["gone"] }), ["gpt-a"]);

if (failed) process.exit(1);
