// Spec: docs/specs/ui.md (Benchmarks, HTTP API 25)
// The Benchmarks page: AI models compared across experiments, from GET /api/benchmarks. It loads its own data
// and ignores the menu's release. Release, provider, model, puzzle, setup, and validity changes send a request;
// significance and metrics changes only redraw. Every choice that differs from its default lives in the hash.
(function () {
  const h = UI.el;
  const SVG = "http://www.w3.org/2000/svg";
  const METRICS = [
    ["success_rate", "Success rate"], ["hallucination_rate", "Hallucination rate"],
    ["mismatch_detection_rate", "Mismatch detection rate"], ["false_mismatch_rate", "False mismatch rate"],
    ["malformed_output_rate", "Malformed output rate"], ["efficiency", "Efficiency"], ["consistency", "Consistency"],
    ["latency_per_attempt_s", "Latency per attempt"], ["tokens_per_attempt", "Tokens per attempt"],
    ["cost_per_success", "Cost per success"],
  ];
  const DEFAULT_METRICS = METRICS.slice(0, 3).map((m) => m[0]);
  const LABEL = Object.fromEntries(METRICS);
  const RATES = METRICS.slice(0, 5).map((m) => m[0]);
  const SETUPS = [["no_model", "no model"], ["descriptive", "descriptive"], ["prescriptive", "prescriptive"]];
  const VALIDITY = [["all", "all inputs"], ["valid", "valid only"], ["invalid", "invalid only"]];
  const SIG = [["all", "All (no test)"], ["weak", "Weak (p < 0.10)"], ["significant", "Significant (p < 0.05)"], ["strong", "Strong (p < 0.01)"]];
  const THRESHOLD = { weak: 0.10, significant: 0.05, strong: 0.01 };
  const UNTESTED_NOTE = "Efficiency, consistency, latency, tokens, and cost have no significance test, so they are coloured only under All.";

  const list = (s) => (s || "").split(",").filter(Boolean);
  const pct = (v, d) => (v * 100).toFixed(d === undefined ? 1 : d) + "%";
  const FORMAT = {
    efficiency: (v) => v.toFixed(2), consistency: (v) => v.toFixed(2),
    latency_per_attempt_s: (v) => v.toFixed(1) + " s", tokens_per_attempt: (v) => Math.round(v).toLocaleString("en-GB"),
    cost_per_success: (v) => "$" + v.toFixed(2),
  };
  const fmt = (metric, v) => (RATES.includes(metric) ? pct(v) : FORMAT[metric](v));
  const pval = (p) => (p < 0.001 ? "<0.001" : p.toFixed(3));

  // The last response and its options, so the keys of the next request can be worked out before it arrives.
  let opts = null;
  const cache = new Map();
  let seq = 0;
  let reopen = null;  // "<picker>|<value>" of the checkbox just toggled

  document.addEventListener("click", (e) => {  // a click outside an open picker closes it
    for (const d of document.querySelectorAll("details.col-picker[open]")) if (!d.contains(e.target)) d.open = false;
  });

  // The choices of the hash, with their defaults.
  function choices(params, bundle) {
    const q = params.query;
    const newest = (bundle.releases || [])[0];
    return {
      releases: list(q.releases).length ? list(q.releases) : newest ? [newest] : [],
      providers: list(q.providers), models: list(q.models), puzzles: list(q.puzzles), setups: list(q.setups),
      validity: VALIDITY.some(([v]) => v === q.validity) ? q.validity : "all",
      sig: SIG.some(([v]) => v === q.sig) ? q.sig : "significant",
      metrics: METRICS.map((m) => m[0]).filter((m) => list(q.metrics).includes(m)).length
        ? METRICS.map((m) => m[0]).filter((m) => list(q.metrics).includes(m)) : DEFAULT_METRICS,
    };
  }

  // The models to ask for: the chosen ones among the chosen providers. null means every model.
  function chosenModels(c, options) {
    if (!options) return c.models.length && !c.providers.length ? c.models : null;
    const providers = options.providers.filter((p) => !c.providers.length || c.providers.includes(p.name));
    const inProviders = providers.flatMap((p) => p.models);
    const names = c.models.length ? inProviders.filter((m) => c.models.includes(m)) : inProviders;
    const all = options.providers.flatMap((p) => p.models);
    return names.length === all.length ? null : names;
  }

  function requestFor(c, options) {
    const models = chosenModels(c, options);
    if (models && !models.length) return null;
    const q = new URLSearchParams();
    if (c.releases.length) q.set("releases", c.releases.join(","));
    if (models) q.set("models", models.join(","));
    if (c.puzzles.length) q.set("puzzles", c.puzzles.join(","));
    if (c.setups.length) q.set("setups", c.setups.join(","));
    if (c.validity !== "all") q.set("validity", c.validity);
    return "/api/benchmarks?" + q;
  }

  async function load(path, stamp) {
    const key = stamp + path;
    if (!cache.has(key)) {
      const data = await UI.api(path);
      if (cache.size >= 20) cache.delete(cache.keys().next().value);
      cache.set(key, data);
    }
    return cache.get(key);
  }

  // A dropdown of checkboxes with the column picker's look. The last ticked box can't be cleared.
  function picker(name, options, selected, onChange, allText) {
    const boxes = options.map(([value, text]) => {
      const box = h("input", { type: "checkbox" });
      box.checked = selected.includes(value);
      box.disabled = box.checked && selected.length === 1;
      box.addEventListener("change", () => {
        reopen = name + "|" + value;
        onChange(options.map((o) => o[0]).filter((o) => (o === value ? box.checked : selected.includes(o))));
      });
      return h("label", {}, box, " " + text);
    });
    const summary = selected.length === options.length ? (allText || "all")
      : selected.length === 1 ? (options.find((o) => o[0] === selected[0]) || [0, selected[0]])[1] : `${selected.length} of ${options.length}`;
    const pick = h("details", { class: "col-picker" }, h("summary", { text: summary }), h("div", { class: "col-menu" }, ...boxes));
    if (reopen && reopen.startsWith(name + "|")) {
      pick.open = true;
      const at = options.findIndex(([v]) => v === reopen.slice(name.length + 1));
      if (at >= 0) requestAnimationFrame(() => boxes[at].firstChild.focus());
      reopen = null;
    }
    return h("div", { class: "small" }, name, pick);  // not a label: a click would reach the first checkbox
  }

  function dropdown(name, value, options, onChange) {
    const s = h("select", { "aria-label": name }, ...options.map(([v, t]) => h("option", { value: v, text: t })));
    s.value = value;
    s.addEventListener("change", () => onChange(s.value));
    return h("label", { class: "small" }, name + " ", s);
  }

  // Which cell of a row is coloured, and the sentence for its tooltip.
  function verdict(row, side, sig) {
    const v = row[side];
    if (!v) return null;
    if (sig !== "all") {
      if (!row.tested || typeof v.p_holm !== "number" || !(v.p_holm < THRESHOLD[sig])) return null;
    }
    const other = side === "best" ? "Better" : "Worse";
    if (!v.against) return { model: v.model, side, tip: `${side === "best" ? "Best" : "Worst"} in this row.` };
    const p = typeof v.p_value === "number" ? `p = ${pval(v.p_value)}${typeof v.p_holm === "number" ? ` (Holm ${pval(v.p_holm)})` : ""}` : "no test";
    return { model: v.model, side, tip: `${other} than ${v.against}: ${p}, ${v.inputs_paired} inputs paired.` };
  }

  function cellTip(metric, cell, mark) {
    const parts = [];
    if (mark) parts.push(mark.tip);
    if (RATES.includes(metric) && typeof cell.value === "number" && typeof cell.low === "number") {
      parts.push(`95% interval ${pct(cell.low)} to ${pct(cell.high)}, n=${cell.n}.`);
    }
    return parts.join(" ");
  }

  function svg(tag, attrs, ...kids) {
    const n = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, String(v));
    for (const kid of kids) if (kid != null) n.append(kid);
    return n;
  }
  const svgText = (attrs, text) => { const t = svg("text", attrs); t.textContent = text; return t; };

  // One small chart: a bar per AI model, neutral unless the row's winner or loser, a Wilson whisker on rates.
  function chart(row, models, marks) {
    const rate = RATES.includes(row.metric);
    const slot = 30, gap = 10, left = 62, top = 18, plot = 110, bottom = 84;
    let x = left, prev = null;
    const spots = models.map((m) => {
      if (prev !== null && prev !== m.provider) x += gap;
      prev = m.provider;
      const at = x;
      x += slot;
      return at;
    });
    const width = x + 6, height = top + plot + bottom;
    const cells = models.map((m) => row.cells[m.name]);
    const values = cells.filter((c) => c && typeof c.value === "number").map((c) => c.value);
    const high = rate ? 1 : Math.max(...values, 0) * 1.1 || 1;
    const y = (v) => top + plot - (v / high) * plot;
    const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img",
      "aria-label": `${row.puzzle}, ${LABEL[row.metric]}, one bar per AI model` });
    if (rate) {
      for (const v of [0, 0.5, 1]) {
        root.append(svg("line", { class: v ? "grid-line" : "axis", x1: left, x2: width - 4, y1: y(v), y2: y(v) }),
          svgText({ class: "tick", x: left - 4, y: y(v) + 3, "text-anchor": "end" }, pct(v, 0)));
      }
    } else {
      root.append(svg("line", { class: "axis", x1: left, x2: width - 4, y1: y(0), y2: y(0) }));
    }
    models.forEach((m, i) => {
      const cell = cells[i];
      const cx = spots[i] + slot / 2;
      root.append(svgText({ class: "name", transform: `rotate(-35 ${cx} ${top + plot + 10})`, x: cx, y: top + plot + 10,
        "text-anchor": "end" }, m.name));
      if (!cell || typeof cell.value !== "number") return;
      const mark = marks[m.name];
      const bar = svg("rect", { class: "bar" + (mark ? " " + mark.cls : ""), x: spots[i] + 4, width: slot - 8,
        y: y(cell.value), height: Math.max(0, y(0) - y(cell.value)), rx: 2 });
      const tip = `${m.name}: ${fmt(row.metric, cell.value)}. ${cellTip(row.metric, cell, mark && mark.verdict)}`;
      bar.append(svg("title", {}, document.createTextNode(tip)));
      root.append(bar);
      let label = y(cell.value) - 3;
      if (rate && typeof cell.low === "number") {
        root.append(svg("line", { class: "whisker", x1: cx, x2: cx, y1: y(cell.low), y2: y(cell.high) }),
          svg("line", { class: "whisker", x1: cx - 3, x2: cx + 3, y1: y(cell.low), y2: y(cell.low) }),
          svg("line", { class: "whisker", x1: cx - 3, x2: cx + 3, y1: y(cell.high), y2: y(cell.high) }));
        label = Math.min(label, y(cell.high) - 3);
      }
      root.append(svgText({ class: "val", x: cx, y: Math.max(10, label), "text-anchor": "middle" },
        rate ? pct(cell.value, 0) : fmt(row.metric, cell.value)));
    });
    return h("div", { class: "bench-chart" }, h("h4", { text: `${row.puzzle} · ${LABEL[row.metric]}` }), root);
  }

  function table(rows, models, marksOf) {
    const providers = [];
    for (const m of models) {
      const last = providers[providers.length - 1];
      if (last && last.name === m.provider) last.span += 1; else providers.push({ name: m.provider, span: 1 });
    }
    const head = [
      h("tr", {}, h("th", { rowspan: "2", colspan: "2", text: "Puzzle and metric" }),
        ...providers.map((p) => h("th", { class: "center", colspan: String(p.span), text: p.name }))),
      h("tr", {}, ...models.map((m) => h("th", { text: m.name }))),
    ];
    const body = [];
    for (const row of rows) {
      const first = rows.findIndex((r) => r.puzzle === row.puzzle) === rows.indexOf(row);
      const marks = marksOf(row);
      const tds = models.map((m) => {
        const cell = row.cells[m.name];
        if (!cell) return h("td");
        const mark = marks[m.name];
        const td = h("td", { class: mark ? mark.cls : "", text: typeof cell.value !== "number" ? "n/a"
          : RATES.includes(row.metric) ? `${pct(cell.value)} n=${cell.n}` : fmt(row.metric, cell.value) });
        const tip = cellTip(row.metric, cell, mark && mark.verdict);
        if (tip) td.title = tip;
        return td;
      });
      body.push(h("tr", {}, first ? h("th", { rowspan: String(rows.filter((r) => r.puzzle === row.puzzle).length), text: row.puzzle }) : null,
        h("th", { text: LABEL[row.metric] }), ...tds));
    }
    return h("div", { class: "table-wrap" }, h("table", { class: "exp-table bench-table" }, h("thead", {}, ...head), h("tbody", {}, ...body)));
  }

  function show(el, data, c, toolbar) {
    const models = data.models.filter((m) => {
      const names = chosenModels(c, data.options);
      return !names || names.includes(m.name);
    });
    const rows = data.rows.filter((r) => c.metrics.includes(r.metric))
      .sort((a, b) => data.rows.findIndex((r) => r.puzzle === a.puzzle) - data.rows.findIndex((r) => r.puzzle === b.puzzle)
        || METRICS.findIndex((m) => m[0] === a.metric) - METRICS.findIndex((m) => m[0] === b.metric));
    el.replaceChildren(toolbar);
    if (!rows.length || !models.length) {
      el.append(h("p", { class: "muted", text: "No experiments for this choice." }));
    } else {
      const marksOf = (row) => {
        const out = {};
        for (const side of ["best", "worst"]) {
          const v = verdict(row, side, c.sig);
          if (v) out[v.model] = { cls: side === "best" ? "win" : "lose", verdict: v };
        }
        return out;
      };
      el.append(h("div", { class: "bench-grid" }, ...rows.filter((r) => models.some((m) => r.cells[m.name] && typeof r.cells[m.name].value === "number"))
        .map((r) => chart(r, models, marksOf(r)))), table(rows, models, marksOf));
      if (c.sig !== "all" && rows.some((r) => !r.tested)) el.append(h("p", { class: "muted small", text: UNTESTED_NOTE }));
    }
    el.append(h("p", { class: "muted small", text: `Computed from the raw records by the UI for display, over ${data.experiments.length} experiment${data.experiments.length === 1 ? "" : "s"}. `
      + "Official numbers are in each experiment's report." }));
    for (const s of data.skipped || []) el.append(h("p", { class: "muted small", text: `${s.id}: ${s.error}` }));
  }

  UI.registerPage("benchmarks", {
    render(bundle, params, el) {
      const c = choices(params, bundle);
      const stamp = String(bundle.fetched_at || "");
      const go = (changes) => {
        const q = new URLSearchParams(params.query);
        q.delete("release");
        for (const [k, v] of Object.entries(changes)) { if (v) q.set(k, v); else q.delete(k); }
        UI.go("#/benchmarks" + (q.toString() ? "?" + q : ""));
      };
      // A list is kept only when it is not everything, or, for releases, not just the newest.
      const keep = (all) => (v) => (v.length === all.length ? "" : v.join(","));
      const toolbar = () => {
        const o = opts || { providers: [], puzzles: [] };
        const providers = o.providers.map((p) => p.name);
        const shownProviders = c.providers.length ? providers.filter((p) => c.providers.includes(p)) : providers;
        const modelOptions = o.providers.filter((p) => shownProviders.includes(p.name)).flatMap((p) => p.models);
        const picked = c.models.length ? modelOptions.filter((m) => c.models.includes(m)) : modelOptions;
        const releases = bundle.releases || [];
        const bar = h("div", { class: "actions exp-filters" },
          picker("Releases", releases.map((r) => [r, r]), c.releases.filter((r) => releases.includes(r)),
            (v) => go({ releases: v.length === 1 && v[0] === releases[0] ? "" : v.join(",") }), "all"),
          picker("AI providers", providers.map((p) => [p, p]), shownProviders, (v) => go({ providers: keep(providers)(v), models: "" })),
          picker("AI models", modelOptions.map((m) => [m, m]), picked.length ? picked : modelOptions, (v) => go({ models: keep(modelOptions)(v) })),
          picker("Puzzles", o.puzzles.map((p) => [p, p]), c.puzzles.length ? c.puzzles.filter((p) => o.puzzles.includes(p)) : o.puzzles,
            (v) => go({ puzzles: keep(o.puzzles)(v) })),
          picker("Setups", SETUPS, c.setups.length ? c.setups : SETUPS.map((s) => s[0]), (v) => go({ setups: keep(SETUPS)(v) })),
          dropdown("Validity", c.validity, VALIDITY, (v) => go({ validity: v === "all" ? "" : v })),
          dropdown("Significance", c.sig, SIG, (v) => go({ sig: v === "significant" ? "" : v })),
          picker("Metrics", METRICS, c.metrics, (v) => go({ metrics: v.join(",") === DEFAULT_METRICS.join(",") ? "" : v.join(",") }), "all"));
        return bar;
      };
      const path = requestFor(c, opts);
      const mine = ++seq;
      el.append(h("h2", { text: "Benchmarks" }));
      const body = h("div", {});
      el.append(body);
      const cached = path && cache.get(stamp + path);
      if (cached) {
        opts = cached.options;
        // The path came from the options of an earlier response, so it holds only when this one agrees.
        if (requestFor(c, opts) === path) { show(body, cached, c, toolbar()); return; }
      }
      body.append(toolbar(), h("p", { class: "muted", text: "Loading…" }));
      (async () => {
        try {
          let data = path ? await load(path, stamp) : null;
          // The provider and model choices need the options, which only a response holds.
          if (data && mine === seq) {
            opts = data.options;
            const again = requestFor(c, opts);
            if (again !== path) data = again ? await load(again, stamp) : { ...data, rows: [], models: [], experiments: [] };
          } else if (!data && opts && mine === seq) {
            data = { options: opts, rows: [], models: [], experiments: [], skipped: [] };
          }
          if (mine !== seq || !body.isConnected) return;
          if (data) { opts = data.options; show(body, data, c, toolbar()); }
        } catch (e) {
          if (mine === seq && body.isConnected) body.replaceChildren(toolbar(), h("p", { class: "msg err", text: e.message }));
        }
      })();
    },
  });
})();
