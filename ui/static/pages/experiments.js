// Spec: docs/specs/ui.md (Experiments)
// The Experiments list: one row per experiment, AI model, and puzzle in the chosen validity scope, from the
// bundle only. Filters and the sort live in the hash.
(function () {
  const h = UI.el;
  const NOTE = ExpMetrics.NOTE, pct = ExpMetrics.pct;
  const DIFFERS = "this experiment's settings for the AI model differ from config/models.toml";
  const RATES = ["success_rate", "hallucination_rate", "mismatch_detection_rate", "false_mismatch_rate", "malformed_output_rate"];
  const COLUMNS = [
    ["id", "Experiment id"], ["model", "AI model"], ["puzzle", "Puzzle"], ["release", "Release"], ["attempts", "Attempts"],
    ["success_rate", "Success rate"], ["hallucination_rate", "Hallucination rate"],
    ["mismatch_detection_rate", "Mismatch detection rate"], ["false_mismatch_rate", "False mismatch rate"],
    ["malformed_output_rate", "Malformed output rate"], ["infrastructure_failures", "Infrastructure failures"],
    ["total_tokens", "Total tokens"], ["cost_usd", "Cost"], ["report_version", "Report"],
  ];

  const num = (v) => (typeof v === "number" ? v.toLocaleString() : "n/a");
  const usd = (v) => (typeof v === "number" ? "$" + v.toFixed(2) : "n/a");

  function select(label, value, options, onChange) {
    const s = h("select", { "aria-label": label }, h("option", { value: "", text: "all" }),
      ...options.map((o) => h("option", { value: o, text: o })));
    s.value = value;
    s.addEventListener("change", () => onChange(s.value));
    return h("label", { class: "small" }, label + " ", s);
  }

  function compare(a, b) {  // empty values sort last in either direction (handled by the caller's sign)
    if (typeof a === "number" && typeof b === "number") return a - b;
    return String(a).localeCompare(String(b), undefined, { numeric: true });
  }

  function sorted(rows, col, dir) {
    if (!col) return rows;
    const sign = dir === "desc" ? -1 : 1;
    const empty = (v) => v === null || v === undefined;
    return rows.slice().sort((a, b) => (empty(a[col]) && empty(b[col]) ? 0 : empty(a[col]) ? 1 : empty(b[col]) ? -1
      : sign * compare(a[col], b[col])));
  }

  function line(r, q) {
    const computed = r.metrics_source === "computed";
    const mark = computed ? " *" : "";
    const model = h("td", {}, r.model);
    if (r.differs_from_catalogue) model.append(" ", h("span", { title: DIFFERS, text: "⚠️" }));
    const id = h("td", {}, h("a", { href: `#/experiments/${encodeURIComponent(r.id)}${q}`, text: r.id }));
    if (r.pushed === false) id.append(" ", h("span", { class: "muted small", text: "running, not pushed" }));
    const cells = [id, model, h("td", { text: r.puzzle || "" }), h("td", { text: r.release || "" })];
    if (r.error) return h("tr", {}, ...cells, h("td", { colspan: "10", class: "msg err", text: r.error }));
    cells.push(h("td", { text: num(r.attempts) }));
    for (const k of RATES) cells.push(h("td", { text: pct(r[k]) + (typeof r[k] === "number" ? mark : "") }));
    const star = (v) => (typeof v === "number" ? mark : "");
    cells.push(h("td", { text: num(r.infrastructure_failures) + star(r.infrastructure_failures) }),
      h("td", { text: num(r.total_tokens) + star(r.total_tokens) }), h("td", { text: usd(r.cost_usd) + star(r.cost_usd) }),
      h("td", { text: computed ? "*" : r.report_version || "" }));
    return h("tr", {}, ...cells);
  }

  UI.registerPage("experiments", {
    render(bundle, params, el) {
      const query = params.query, validity = query.validity || "all";
      const base = new URLSearchParams(query);
      const go = (changes) => {
        const q = new URLSearchParams(base);
        for (const [k, v] of Object.entries(changes)) { if (v) q.set(k, v); else q.delete(k); }
        UI.go("#/experiments" + (q.toString() ? "?" + q : ""));
      };
      const rel = params.release ? "?release=" + encodeURIComponent(params.release) : "";
      const all = bundle.experiments;
      const rows = all.filter((r) => (r.error || r.validity === validity)
        && (!query.model || r.model === query.model) && (!query.puzzle || r.puzzle === query.puzzle));
      const uniq = (k) => [...new Set(all.map((r) => r[k]).filter(Boolean))].sort();
      const filters = h("div", { class: "actions exp-filters" },
        select("AI model", query.model || "", uniq("model"), (v) => go({ model: v })),
        select("Puzzle", query.puzzle || "", uniq("puzzle"), (v) => go({ puzzle: v })),
        h("label", { class: "small" }, "Validity ", Object.assign(h("select", { "aria-label": "Validity" },
          ...[["all", "all inputs"], ["valid", "valid only"], ["invalid", "invalid only"]].map(([v, t]) => h("option", { value: v, text: t }))),
        { value: validity, onchange: (e) => go({ validity: e.target.value === "all" ? "" : e.target.value }) })));
      const head = h("tr", {}, ...COLUMNS.map(([k, t]) => {
        const on = query.sort === k;
        const th = h("th", { class: "sortable", "aria-sort": on ? (query.dir === "desc" ? "descending" : "ascending") : "none" },
          h("button", { type: "button", class: "linklike", text: t + (on ? (query.dir === "desc" ? " ▼" : " ▲") : "") }));
        th.firstChild.addEventListener("click", () => go({ sort: k, dir: on && query.dir !== "desc" ? "desc" : "" }));
        return th;
      }));
      const body = sorted(rows, query.sort, query.dir).map((r) => line(r, rel));
      el.append(h("h2", { text: "Experiments" }), filters);
      if (!body.length) el.append(h("p", { class: "muted", text: "No experiments for this release and filters." }));
      else el.append(h("div", { class: "table-wrap" }, h("table", { class: "exp-table" }, h("thead", {}, head), h("tbody", {}, ...body))));
      if (rows.some((r) => r.metrics_source === "computed" && !r.error)) el.append(h("p", { class: "muted small", text: NOTE }));
    },
  });
})();
