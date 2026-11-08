// Spec: docs/specs/ui.md (Experiment 2 and 4, Experiments 4)
// Number formats and the Summary and full metrics tables of the Experiment page, from the experiment JSON.
// Reads only the rows it is given and builds DOM.
(function () {
  const h = UI.el;
  const NOTE = "* computed from the raw records by the UI for display. No report is committed for this experiment, so these are not official numbers.";
  const SUMMARY_NOTE = "* pooled from the report's rows. The interval is a Wilson score interval over attempts, for display only, not the report's bootstrap interval over inputs.";
  const RATES = [["precision", "Precision"], ["coverage", "Coverage"], ["hallucination_rate", "Hallucination"],
    ["mismatch_detection_rate", "Mismatch detection"], ["false_mismatch_rate", "False mismatch"],
    ["malformed_output_rate", "Malformed output"], ["truncated_rate", "Truncated"],
    ["abstention_rate", "Abstention"], ["format_error_rate", "Format error"]];

  const pct = (v) => (typeof v === "number" ? (v * 100).toFixed(1) + "%" : "n/a");
  const grouped = (v) => (typeof v === "number" ? v.toLocaleString() : "n/a");

  // `41.0% (30.2–52.9) n=60`; a rate that is n/a keeps its n.
  function rate(row, name, mark) {
    const v = row[name], n = ` n=${row[name + "_n"]}`;
    if (typeof v !== "number") return "n/a" + n;
    const lo = row[name + "_low"], hi = row[name + "_high"];
    const span = typeof lo === "number" && typeof hi === "number" ? `${(lo * 100).toFixed(1)}–${(hi * 100).toFixed(1)}` : "n/a";
    return `${pct(v)} (${span})${n}${mark}`;
  }

  // key names the table for Defs.keepFocus, so a redraw can find it again.
  function table(key, head, rows, defs) {
    return h("div", { class: "table-wrap" }, h("table", { "data-table": key }, h("thead", {}, h("tr", {}, ...head.map((t) => h("th", {}, t, ...Defs.info(defs, t))))),
      h("tbody", {}, ...rows.map((cells) => h("tr", {}, ...cells.map((c) => h("td", { text: String(c) })))))));
  }

  // One row per AI model, setup, and validity label; then tokens and cost per AI model from the list rows.
  function summary(detail, listRows, defs) {
    const computed = detail.metrics_source === "computed";
    const mark = " *";  // computed rows and rows pooled from a report CSV are both display-only
    if (!detail.summary_rows.length) return h("p", { class: "muted", text: "No attempts to summarize yet." });
    const box = h("div");
    box.append(table("summary", ["AI model", "Setup", "Validity", "Attempts", ...RATES.map((r) => r[1])],
      detail.summary_rows.map((r) => [r.model, r.setup, r.validity, r.attempts, ...RATES.map(([k]) => rate(r, k, mark))]), defs));
    const models = [...new Set(detail.summary_rows.map((r) => r.model))];
    const own = listRows.filter((r) => r.id === detail.id && r.validity === "all" && !r.error);
    box.append(table("cost", ["AI model", "Total tokens", "Cost"], models.map((m) => {
      const rows = own.filter((r) => r.model === m);
      const sum = (k) => (rows.length && rows.every((r) => typeof r[k] === "number") ? rows.reduce((a, r) => a + r[k], 0) : null);
      return [m, grouped(sum("total_tokens")), sum("cost_usd") === null ? "n/a" : UI.usd(sum("cost_usd"), { fixed: 2 })];
    }), defs));
    box.append(h("p", { class: "muted small", text: computed ? NOTE : SUMMARY_NOTE }));
    return box;
  }

  // One row per puzzle, setup, AI model, scramble depth, and validity label.
  function full(detail, defs) {
    const mark = detail.metrics_source === "computed" ? " *" : "";
    const box = h("div");
    box.append(table("metrics", ["Puzzle", "Setup", "AI model", "Depth", "Validity", "Attempts", ...RATES.map((r) => r[1])],
      detail.metric_rows.map((r) => [r.puzzle, r.setup, r.model, r.scramble_depth, r.validity, r.attempts,
        ...RATES.map(([k]) => rate(r, k, mark))]), defs));
    if (mark) box.append(h("p", { class: "muted small", text: NOTE }));
    return box;
  }

  window.ExpMetrics = { NOTE, SUMMARY_NOTE, pct, grouped, summary, full };
})();
