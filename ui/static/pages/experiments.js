// Spec: docs/specs/ui.md (Experiments)
// The Experiments list: one row per experiment, AI model, and puzzle in the chosen validity scope, from the
// bundle only. Filters, hidden columns, and the sort live in the hash.
(function () {
  const h = UI.el;
  const NOTE = ExpMetrics.NOTE, pct = ExpMetrics.pct;
  const DIFFERS = "this experiment's settings for the AI model differ from config/models.toml";
  const RATES = ["success_rate", "hallucination_rate", "mismatch_detection_rate", "false_mismatch_rate", "malformed_output_rate",
    "truncated_rate", "abstention_rate", "format_error_rate"];
  const COLUMNS = [
    ["id", "Experiment id"], ["started_at", "Started"], ["model", "AI model"], ["puzzle", "Puzzle"], ["release", "Release"], ["attempts", "Attempts"],
    ["success_rate", "Success rate"], ["hallucination_rate", "Hallucination rate"],
    ["mismatch_detection_rate", "Mismatch detection rate"], ["false_mismatch_rate", "False mismatch rate"],
    ["malformed_output_rate", "Malformed output rate"], ["truncated_rate", "Truncation rate"],
    ["abstention_rate", "Abstention rate"], ["format_error_rate", "Format error rate"], ["infrastructure_failures", "Infrastructure failures"],
    ["total_tokens", "Total tokens"], ["cost_usd", "Cost"], ["report_version", "Report"],
  ];
  // Hidden when the hash has no `hide` key. `hide=none` in the hash shows every column.
  const DEFAULT_HIDDEN = ["release", "false_mismatch_rate", "malformed_output_rate", "infrastructure_failures",
    "total_tokens", "report_version"];

  const num = (v) => (typeof v === "number" ? v.toLocaleString() : "n/a");
  const usd = (v) => (typeof v === "number" ? "$" + v.toFixed(2) : "n/a");

  function started(iso) {  // "2026, Nov 4 14:30" in the browser's time zone
    if (!iso) return "";
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(iso)).map((x) => [x.type, x.value]));
    return `${p.year}, ${p.month} ${p.day} ${p.hour}:${p.minute}`;
  }

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

  function line(r, q, shown) {
    const computed = r.metrics_source === "computed";
    const mark = computed ? " *" : "";
    const star = (v) => (typeof v === "number" ? mark : "");
    const model = h("td", {}, r.model);
    if (r.differs_from_catalogue) model.append(" ", h("span", { title: DIFFERS, text: "⚠️" }));
    const id = h("td", {}, h("a", { href: `#/experiments/${encodeURIComponent(r.id)}${q}`, text: r.id }));
    if (r.pushed === false) id.append(" ", h("span", { class: "muted small", text: "running, not pushed" }));
    const cells = { id, model, started_at: h("td", { text: started(r.started_at) }), puzzle: h("td", { text: r.puzzle || "" }), release: h("td", { text: r.release || "" }) };
    const lead = shown.filter((k) => k in cells);
    if (r.error) {
      const rest = shown.length - lead.length;
      if (!rest) cells[lead[lead.length - 1]].append(" ", h("span", { class: "msg err", text: r.error }));
      return h("tr", {}, ...lead.map((k) => cells[k]), rest ? h("td", { colspan: String(rest), class: "msg err", text: r.error }) : null);
    }
    cells.attempts = h("td", { text: num(r.attempts) });
    for (const k of RATES) cells[k] = h("td", { text: pct(r[k]) + star(r[k]) });
    cells.infrastructure_failures = h("td", { text: num(r.infrastructure_failures) + star(r.infrastructure_failures) });
    cells.total_tokens = h("td", { text: num(r.total_tokens) + star(r.total_tokens) });
    cells.cost_usd = h("td", { text: usd(r.cost_usd) + star(r.cost_usd) });
    cells.report_version = h("td", { text: computed ? "*" : r.report_version || "" });
    return h("tr", {}, ...shown.map((k) => cells[k]));
  }

  // A dropdown of checkboxes, one per column. The experiment id always shows, because it is the row's link.
  // A toggle re-renders the page, so the new picker opens again to let several columns change in a row.
  let reopen = null;  // the key of the checkbox just toggled
  function columnPicker(hidden, onChange) {
    const boxes = COLUMNS.map(([k, t]) => {
      const box = h("input", { type: "checkbox" });
      box.checked = !hidden.has(k);
      box.disabled = k === "id";
      box.addEventListener("change", () => {
        const off = COLUMNS.map(([c]) => c).filter((c) => c !== k ? hidden.has(c) : !box.checked);
        reopen = k;
        onChange(off.join(",") || "none");
      });
      return h("label", {}, box, " " + t);
    });
    const count = COLUMNS.length - hidden.size;
    const picker = h("details", { class: "col-picker" },
      h("summary", { text: count === COLUMNS.length ? "all" : `${count} of ${COLUMNS.length}` }),
      h("div", { class: "col-menu" }, ...boxes));
    if (reopen) {
      picker.open = true;
      const box = boxes[COLUMNS.findIndex(([k]) => k === reopen)].firstChild;
      requestAnimationFrame(() => box.focus());
    }
    reopen = null;
    return h("div", { class: "small" }, "Columns", picker);  // not a label: a click would reach the first checkbox
  }

  document.addEventListener("click", (e) => {  // a click outside the open column picker closes it
    for (const d of document.querySelectorAll("details.col-picker[open]")) if (!d.contains(e.target)) d.open = false;
  });

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
      const hidden = new Set((query.hide === undefined ? DEFAULT_HIDDEN : query.hide.split(",")).filter((k) => k && k !== "id" && COLUMNS.some(([c]) => c === k)));
      const shown = COLUMNS.map(([k]) => k).filter((k) => !hidden.has(k));
      const filters = h("div", { class: "actions exp-filters" },
        select("AI model", query.model || "", uniq("model"), (v) => go({ model: v })),
        select("Puzzle", query.puzzle || "", uniq("puzzle"), (v) => go({ puzzle: v })),
        h("label", { class: "small" }, "Validity ", Object.assign(h("select", { "aria-label": "Validity" },
          ...[["all", "all inputs"], ["valid", "valid only"], ["invalid", "invalid only"]].map(([v, t]) => h("option", { value: v, text: t }))),
        { value: validity, onchange: (e) => go({ validity: e.target.value === "all" ? "" : e.target.value }) })),
        columnPicker(hidden, (v) => go({ hide: v })));
      const head = h("tr", {}, ...COLUMNS.filter(([k]) => !hidden.has(k)).map(([k, t]) => {
        const on = query.sort === k;
        const th = h("th", { class: "sortable", "aria-sort": on ? (query.dir === "desc" ? "descending" : "ascending") : "none" },
          h("button", { type: "button", class: "linklike", text: t + (on ? (query.dir === "desc" ? "\u00a0▼" : "\u00a0▲") : "") }));
        th.firstChild.addEventListener("click", () => go({ sort: k, dir: on && query.dir !== "desc" ? "desc" : "" }));
        return th;
      }));
      const body = sorted(rows, hidden.has(query.sort) ? "" : query.sort, query.dir).map((r) => line(r, rel, shown));
      el.append(h("h2", { text: "Experiments" }), filters);
      if (!body.length) el.append(h("p", { class: "muted", text: "No experiments for this release and filters." }));
      else el.append(h("div", { class: "table-wrap" }, h("table", { class: "exp-table" }, h("thead", {}, head), h("tbody", {}, ...body))));
      if (rows.some((r) => r.metrics_source === "computed" && !r.error)) el.append(h("p", { class: "muted small", text: NOTE }));
    },
  });
})();
