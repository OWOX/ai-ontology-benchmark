// Spec: docs/specs/ui.md (Bundle 6, Benchmarks, Definition icons)
// The (i) icon with a definition tooltip, shared by every page. The definitions come from the bundle's
// `definitions`, never from a copy here. TERMS is the one table from a UI label (or a field name) to the bold term
// of docs/definitions.md that defines it. A label with no term, or a term the bundle lacks, gets no icon.
(function () {
  const h = UI.el;
  const TERMS = {
    // New Experiment
    "Puzzles": "Puzzle", "AI models": "AI model",
    "Request budget (USD)": "Request budget", "Model budget (USD)": "Model budget", "Experiment budget (USD)": "Experiment budget",
    "Attempts per input and setup": "Attempt", "Inputs per depth": "Inputs per depth", "Retry cap": "Retry cap",
    "Reasoning effort": "Reasoning effort", "Parallel requests": "Parallel requests",
    // the live estimate table
    "Attempts to run": "Attempt", "Worst case": "Worst-case request cost", "Spent": "Cost", "Model budget": "Model budget",
    "Median latency": "Latency",
    // the score card, the Experiments list, and the Summary and Full metrics tables
    "Balanced precision": "Balanced precision", "Coverage": "Coverage", "Hallucination": "Hallucination rate",
    "Hallucination rate": "Hallucination rate", "Reason hallucination": "Reason hallucination rate",
    "Critical thinking": "Critical thinking", "Cost so far": "Cost", "Cost": "Cost", "Cost efficiency": "Cost efficiency",
    "Precision": "Precision", "Mismatch detection": "Mismatch detection rate", "Mismatch detection rate": "Mismatch detection rate",
    "False mismatch": "False mismatch rate", "False mismatch rate": "False mismatch rate",
    "Malformed output": "Malformed output rate", "Malformed output rate": "Malformed output rate",
    "Truncated": "Truncation rate", "Truncation rate": "Truncation rate",
    "Abstention": "Abstention rate", "Abstention rate": "Abstention rate",
    "Format error": "Format error rate", "Format error rate": "Format error rate",
  };
  let seq = 0;

  // The icon and its panel after a term, as nodes to append (empty when the bundle has no definition for it). The
  // icon links to the term's section when the definition has a source.
  function infoTerm(defs, term) {
    const def = defs && defs.terms && defs.terms[term];
    if (!def || !def.text) return [];
    const id = "def-" + ++seq;
    const icon = h(def.source ? "a" : "span", { class: "info tip-src", "aria-label": "definition", "aria-describedby": id, text: "i",
      ...(def.source ? { href: def.source, target: "_blank", rel: "noopener" } : { tabindex: "0" }) });
    UI.tipOn(icon);
    // A mouse click blurs the link, so its panel does not stay at a stale place once GitHub opens in another tab.
    // A keyboard Enter (detail 0) keeps the focus.
    icon.addEventListener("click", (e) => { if (e.detail) icon.blur(); });
    return [" ", h("span", { class: "tip-wrap" }, icon, h("span", { class: "tip-fixed", id, role: "tooltip", text: def.text }))];
  }

  // The same for a UI label, through TERMS.
  const info = (defs, label) => (TERMS[label] ? infoTerm(defs, TERMS[label]) : []);

  window.Defs = { TERMS, infoTerm, info };
})();
