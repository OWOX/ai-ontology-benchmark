// Spec: docs/specs/ui.md (New Experiment, Banners, HTTP API 4 to 11)
// New Experiment: the form, the live estimate, Dry run, and Run. Reads the bundle,
// GET /api/branches, /api/default-id, and /api/experiment/<id>/config; asks POST /api/estimate/live for the estimate
// and writes only through POST /api/dry-run and /api/run. Run answers once its jobs start, and the page then opens the experiment's page,
// which shows the settings, Progress, Stop, and the terminal.
(function () {
  const h = UI.el;
  // The provider's key info decides, as on the Models page: an unconfigured key with a source other than "missing"
  // is a token whose account id is missing. The wording is shown here and is the same as ui/bundle.py's reasons.
  function keyProblem(p) {
    if (!p.key || p.key.configured) return null;
    return p.key.source === "missing" ? "no API key: add it under Models" : "no account id: add it under Models";
  }
  const NUMBERS = [["retry_cap", "Retry cap"], ["max_output_tokens", "Max output tokens"], ["per_request_usd", "Request budget (USD)"],
    ["per_model_usd", "Model budget (USD)"], ["per_experiment_usd", "Experiment budget (USD)"]];
  // The form survives a redraw of the page (a bundle reload after a job) and resets with the release.
  const S = { release: null, id: "", touched: false, branch: "", puzzles: [], models: [], vals: {}, limit: "", parallel: "4", perDepth: null, perDepthLoaded: null, estimate: null, pending: false, result: null };
  let cleanup = null;
  let idSeq = 0;
  const mine = UI.mine;

  // A bundle cached in the browser from before the field existed has no default, and the fresh bundle of the same
  // release never calls reset() again. So the effort is filled here whenever it is unset: "" is a loaded experiment
  // saved without one and stays "provider default".
  function fillEffort(vals, defaults) {
    if (vals.reasoning_effort === undefined) vals.reasoning_effort = (defaults && defaults.reasoning_effort) || "medium";
  }

  function reset(bundle) {
    const d = bundle.defaults;
    Object.assign(S, { release: bundle.release, id: "", touched: false, branch: "", puzzles: bundle.puzzles.map((p) => p.name), models: [], limit: "", parallel: "4", perDepth: null, perDepthLoaded: null, estimate: null, pending: false, result: null,
      vals: { attempts: d.attempts, retry_cap: d.retry_cap, max_output_tokens: d.max_output_tokens, reasoning_effort: d.reasoning_effort, ...d.budget } });
  }

  function whole(v, name) {
    const n = Number(String(v).trim());
    if (String(v).trim() === "" || !Number.isInteger(n)) throw new Error(`${name} must be a whole number`);
    return n;
  }
  function amount(v, name) {
    const n = Number(String(v).trim());
    if (String(v).trim() === "" || !Number.isFinite(n)) throw new Error(`${name} must be a number`);
    return n;
  }

  function readForm(bundle) {
    const id = S.id.trim();
    if (!id) throw new Error("id: enter an experiment id");
    if (!S.puzzles.length) throw new Error("puzzles: select at least one puzzle");
    if (!S.models.length) throw new Error("models: select at least one AI model");
    const v = S.vals;
    return {
      id, release: bundle.release,
      puzzles: bundle.puzzles.map((p) => p.name).filter((n) => S.puzzles.includes(n)),
      models: bundle.providers.flatMap((p) => p.models).filter((m) => !m.disabled_reason).map((m) => m.name).filter((n) => S.models.includes(n)),
      attempts: whole(v.attempts, "attempts"), inputs_per_depth: S.perDepth, retry_cap: whole(v.retry_cap, "retry_cap"),
      max_output_tokens: whole(v.max_output_tokens, "max_output_tokens"),
      reasoning_effort: v.reasoning_effort || null,
      budget: { per_request_usd: amount(v.per_request_usd, "per_request_usd"), per_model_usd: amount(v.per_model_usd, "per_model_usd"),
        per_experiment_usd: amount(v.per_experiment_usd, "per_experiment_usd") },
    };
  }

  // Not part of the experiment config: it goes beside `limit` in the run request and becomes `run --parallel`.
  function readParallel() {
    const n = Number(S.parallel.trim());
    if (S.parallel.trim() === "" || !Number.isInteger(n) || n < 1 || n > 16) throw new Error("parallel must be a whole number from 1 to 16");
    return n;
  }

  function readLimit() {
    if (S.limit.trim() === "") return null;
    const n = Number(S.limit.trim());
    if (!Number.isInteger(n) || n < 1) throw new Error("limit must be a whole number of at least 1");
    return n;
  }

  // Valid inputs per puzzle and scramble depth: the bundle's, else the most any chosen puzzle holds per depth.
  function perDepthMax(bundle) {
    if (bundle.scramble_count) return bundle.scramble_count;
    return Math.max(1, ...bundle.puzzles.map((p) => Math.floor((p.valid || 1) / Math.max(1, (p.depths || [1]).length))));
  }

  // The Inputs per depth slider and the form. The top of the slider means every input, which is null. A loaded
  // value at or above the top shows as "all" but stays what the form sends until the slider is moved, so a resumed
  // config is byte-identical.
  function perDepthPosition(perDepth, top) { return perDepth === null || perDepth >= top ? top : perDepth; }
  // `loaded` is the value a loaded branch came with (null for none): when it is at or above the top, the top maps back to it.
  function perDepthFromSlider(n, top, loaded) { return n >= top ? (loaded !== null && loaded !== undefined && loaded >= top ? loaded : null) : n; }

  // Hands out numbered requests and says whether one is still the newest, so a late answer can be dropped.
  function newestOnly() {
    let last = 0;
    return { next: () => ++last, isNewest: (ticket) => ticket === last };
  }

  // A range slider with its value shown beside it. `show` turns the number into the text beside the slider.
  function slider(label, min, max, value, show, onInput, icon = []) {
    const input = h("input", { type: "range", min: String(min), max: String(max), step: "1", "aria-label": label });
    input.value = String(Math.min(max, Math.max(min, value)));
    const out = h("output", { class: "slider-value", text: show(Number(input.value)) });
    input.setAttribute("aria-valuetext", out.textContent);
    input.addEventListener("input", () => {
      out.textContent = show(Number(input.value));
      input.setAttribute("aria-valuetext", out.textContent);
      onInput(Number(input.value));
    });
    return h("label", {}, h("span", {}, label, ...icon), h("span", { class: "slider" }, input, out));
  }

  function puzzleCards(bundle, onChange) {
    return h("div", { class: "cards" }, ...bundle.puzzles.map((p) => {
      const card = h("button", { type: "button", class: "card", "aria-pressed": "false" },
        p.n ? cubeNet(solvedState(p.n), { width: 96, height: 72 }) : null,
        h("div", { class: "name", text: p.name }), h("div", { class: "muted small", text: `${p.input_count} inputs` }));
      const paint = () => { const on = S.puzzles.includes(p.name); card.classList.toggle("sel", on); card.setAttribute("aria-pressed", String(on)); };
      card.addEventListener("click", () => {
        S.puzzles = S.puzzles.includes(p.name) ? S.puzzles.filter((n) => n !== p.name) : [...S.puzzles, p.name];
        paint(); onChange();
      });
      paint();
      return card;
    }));
  }

  // One column per provider. The header's checkbox selects or clears every enabled model of the provider.
  function modelList(bundle, onChange) {
    const rel = bundle.release ? "?release=" + encodeURIComponent(bundle.release) : "";
    return h("div", { class: "model-cols" }, ...bundle.providers.filter((p) => p.models.length).map((p) => {
      const enabled = p.models.filter((m) => !m.disabled_reason).map((m) => m.name);
      const all = h("input", { type: "checkbox", "aria-label": `All ${p.name} models` });
      all.disabled = !enabled.length;
      const boxes = [];
      const sync = () => {
        const n = enabled.filter((name) => S.models.includes(name)).length;
        all.checked = n > 0 && n === enabled.length;
        all.indeterminate = n > 0 && n < enabled.length;
        for (const [name, box] of boxes) box.checked = S.models.includes(name);
      };
      all.addEventListener("change", () => {
        S.models = all.checked ? [...S.models.filter((n) => !enabled.includes(n)), ...enabled] : S.models.filter((n) => !enabled.includes(n));
        sync(); onChange();
      });
      const head = h("label", { class: "provider-head" }, all, h("span", { text: p.name }));
      // A missing key shows as a warning sign after the provider name, linking to Models; the reason is its tooltip.
      const problem = keyProblem(p);
      const tipId = "key-tip-" + p.name;
      const warn = problem ? h("span", { class: "tip-wrap" },
        h("a", { class: "key-warn tip-src", href: "#/models" + rel, "aria-label": `${p.name}: ${problem}`, "aria-describedby": tipId, text: "⚠️" }),
        h("span", { class: "tip-fixed", id: tipId, role: "tooltip", text: problem[0].toUpperCase() + problem.slice(1) })) : null;
      if (warn) UI.tipOn(warn.firstChild);
      const col = h("div", { class: "model-col" }, h("div", { class: "provider-row" }, head, warn));
      for (const m of p.models) {
        const off = !!m.disabled_reason;
        const box = h("input", { type: "checkbox" });
        box.disabled = off;
        if (!off) boxes.push([m.name, box]);
        box.addEventListener("change", () => {
          S.models = box.checked ? [...S.models, m.name] : S.models.filter((n) => n !== m.name);
          sync(); onChange();
        });
        const label = h("label", { class: "model" + (off ? " off" : "") }, box, h("span", { text: m.name }));
        if (off && (!problem || m.disabled_reason !== problem)) label.append(h("span", { class: "reason", text: m.disabled_reason }));
        col.append(label);
      }
      sync();
      return col;
    }));
  }

  // Two columns: the three budgets, then the rest.
  function numberFields(bundle, changed) {
    const field = ([key, label]) => {
      const input = h("input", { type: "text", inputmode: "decimal", "aria-label": label, value: String(S.vals[key]) });
      input.addEventListener("input", () => { S.vals[key] = input.value; changed(); });
      return h("label", {}, h("span", {}, label, ...Defs.info(bundle.definitions, label)), input);
    };
    // low, medium, or high; "provider default" only appears for a loaded experiment that was saved without one.
    const effort = (() => {
      const select = h("select", { "aria-label": "Reasoning effort" });
      const options = S.vals.reasoning_effort === "" ? ["", "low", "medium", "high"] : ["low", "medium", "high"];
      for (const v of options) select.append(h("option", { value: v, text: v || "provider default" }));
      select.value = S.vals.reasoning_effort || "";
      select.addEventListener("change", () => { S.vals.reasoning_effort = select.value; changed(); });
      return h("label", {}, h("span", {}, "Reasoning effort", ...Defs.info(bundle.definitions, "Reasoning effort"), ": sent to every system-2 model"), select);
    })();
    const limit = (() => {
      const input = h("input", { type: "text", inputmode: "numeric", "aria-label": "Limit per model", value: S.limit });
      input.addEventListener("input", () => { S.limit = input.value; });
      return h("label", {}, "Limit per model (optional): stops each AI model after N attempts", input);
    })();
    const attempts = slider("Attempts per input and setup: sends the same input N times", 1, Math.max(10, Number(S.vals.attempts) || 0), Number(S.vals.attempts) || 1,
      String, (n) => { S.vals.attempts = String(n); changed(); }, Defs.info(bundle.definitions, "Attempts per input and setup"));
    const top = perDepthMax(bundle);
    const perDepth = slider("Inputs per depth: valid inputs per puzzle and scramble depth", 1, top, perDepthPosition(S.perDepth, top),
      (n) => n >= top ? "all" : String(n), (n) => { S.perDepth = perDepthFromSlider(n, top, S.perDepthLoaded); changed(); }, Defs.info(bundle.definitions, "Inputs per depth"));
    const parallel = (() => {
      const box = slider("Parallel requests", 1, 16, Number(S.parallel) || 4, String, (n) => { S.parallel = String(n); changed(); });
      // The definition is on main: linked when the bundle knows the repository, plain text otherwise. The slider's
      // aria-label keeps the plain name.
      const term = bundle.repo && bundle.main_sha
        ? h("a", { href: `${bundle.repo}/blob/${bundle.main_sha}/docs/definitions.md#workflows`, target: "_blank", rel: "noopener", text: "Parallel requests" })
        : document.createTextNode("Parallel requests");
      box.firstChild.replaceWith(h("span", {}, term, ...Defs.info(bundle.definitions, "Parallel requests"), ": attempts in flight at once per AI model. Only the speed changes, never what an attempt sends or records."));
      return box;
    })();
    const budgets = NUMBERS.filter(([k]) => k.endsWith("_usd")), rest = NUMBERS.filter(([k]) => !k.endsWith("_usd"));
    return h("div", { class: "params-cols" }, h("div", { class: "grid" }, ...budgets.map(field)),
      h("div", { class: "grid" }, attempts, perDepth, ...rest.map(field), effort, limit, parallel));
  }

  UI.registerPage("new", {
    render(bundle, params, el) {
      if (cleanup) cleanup();
      if (S.release !== bundle.release) reset(bundle);
      fillEffort(S.vals, bundle.defaults);
      const formBox = h("div");
      el.append(h("div", { class: "newexp" }, formBox));
      const ref = {};
      let dead = false, starting = false;

      const msg = h("p", { class: "msg", role: "status" });
      const say = (text, kind) => { msg.className = "msg" + (kind ? " " + kind : ""); msg.textContent = text; };

      function controls() {
        if (!ref.run) return;
        const id = S.id.trim();
        const run = (j) => j.startsWith("run:"), busy = (j) => run(j) || j === "evaluate";
        ref.run.disabled = starting || mine(id, busy);
        ref.dry.disabled = mine(id, (j) => j === "dry-run");
      }

      let branches = [], pickSeq = 0, loading = false;
      const branchNote = () => S.branch ? "Existing branch: its config is loaded, and Run resumes it."
        : S.touched && branches.includes(S.id) ? "This branch exists. Press Enter or leave the field to load it."
        : S.touched ? "Edited by hand. Clear the field to get the suggestion back."
          : "Suggested from the chosen puzzles and AI models. Edit it, or pick an existing branch to load it.";

      async function refreshId() {
        if (S.touched || S.branch) return;
        const mine_ = ++idSeq;
        const order = (list, chosen) => list.filter((n) => chosen.includes(n));
        const models = order(bundle.providers.flatMap((p) => p.models.map((m) => m.name)), S.models);
        const q = new URLSearchParams({ models: models.join(","), puzzles: order(bundle.puzzles.map((p) => p.name), S.puzzles).join(",") });
        try {
          const r = await UI.api("/api/default-id?" + q);
          if (mine_ !== idSeq || S.touched || S.branch || dead) return;
          S.id = r.id; dropStaleResult();
          if (ref.id) ref.id.value = S.id;
          if (ref.note) ref.note.textContent = branchNote();
          controls(); schedule();
        } catch (e) { say(e.message, "err"); }
      }

      const choose = () => { refreshId(); schedule(); };

      async function pickBranch(value) {
        say("");
        // A later pick or a keystroke in the branch field supersedes a load still in flight.
        const seq = ++pickSeq;
        S.branch = value;
        loading = true;
        try {
          const cfg = await UI.api("/api/experiment/" + encodeURIComponent(value) + "/config");
          if (dead || seq !== pickSeq) return;
          loading = false;
          const all = bundle.providers.flatMap((p) => p.models);
          const enabled = new Set(all.filter((m) => !m.disabled_reason).map((m) => m.name));
          const dropped = cfg.models.filter((n) => !enabled.has(n)).map((n) => {
            const m = all.find((x) => x.name === n);
            return `${n} is disabled: ${m ? m.disabled_reason : "not in the catalogue"}; resuming needs it enabled`;
          });
          Object.assign(S, { id: value, touched: true, release: cfg.release, puzzles: cfg.puzzles, models: cfg.models.filter((n) => enabled.has(n)), perDepth: cfg.inputs_per_depth === undefined ? null : cfg.inputs_per_depth,
            perDepthLoaded: cfg.inputs_per_depth === undefined ? null : cfg.inputs_per_depth,
            vals: { attempts: cfg.attempts, retry_cap: cfg.retry_cap, max_output_tokens: cfg.max_output_tokens, reasoning_effort: cfg.reasoning_effort || "", ...cfg.budget } });
          if (cfg.release !== bundle.release) { UI.go("#/new?release=" + encodeURIComponent(cfg.release)); return; }
          paint();
          const page = h("a", { href: "#/experiments/" + encodeURIComponent(value) + "?release=" + encodeURIComponent(cfg.release), text: "Open its page" });
          msg.className = "msg " + (dropped.length ? "err" : "ok");
          msg.replaceChildren(`Loaded ${value}. ${dropped.length ? dropped.join(". ") + ". " : ""}`, page);
        } catch (e) {
          if (seq !== pickSeq) return;
          loading = false; S.branch = "";
          if (ref.note) ref.note.textContent = branchNote();
          say(e.message, "err");
        }
      }

      // The live estimate: asked of the server 250 ms after the last change, with an answer older than the newest
      // request dropped. Its errors show in the card, never in the form's message.
      const usd = (v) => UI.usd(v, { verbatim: true, maxBelowOne: 4 });
      const count = (v) => Number(v).toLocaleString("en-GB");
      let timer = null;
      const asks = newestOnly();
      // The formula line is one element for the life of the page, so its live region is announced as a change in
      // place. The table below it dims while a new answer is awaited, and "Estimating…" joins the formula line, so
      // nothing moves.
      function drawCard() {
        if (!ref.card) return;
        const e = S.estimate;
        ref.card.hidden = !(S.puzzles.length && S.models.length);
        if (ref.card.hidden) return;
        const wait = S.pending ? "Estimating…" : "";
        ref.body.classList.toggle("pending", S.pending);
        if (!e) { ref.formula.textContent = wait; ref.body.replaceChildren(); return; }
        if (e.error) {
          ref.formula.textContent = wait;
          ref.body.replaceChildren(h("p", { class: "msg err", role: "alert", text: e.error }));
          return;
        }
        const d = e.data, c = d.counts, budget = e.budget;
        const formula = `${count(c.inputs)} inputs × ${c.models} AI models × ${c.setups} setups × ${e.attempts} attempts = ${count(c.planned)} attempts`
          + (c.done ? `, ${count(c.done)} done, ${count(c.to_run)} to run` : "");
        ref.formula.textContent = wait ? `${formula}. ${wait}` : formula;
        const cells = (tag, values) => h("tr", {}, ...values.map(([text, cls, title], i) =>
          h(tag, { class: (i ? "n " : "") + (cls || ""), text, ...(title ? { title } : {}) })));
        const over = (flag, reason) => flag ? ["over", reason] : [];
        const REQUEST_OVER = "The longest worst-case request exceeds the request budget: the run refuses it.";
        const MODEL_OVER = "Spent plus the worst case exceeds the model budget: the run stops when spending reaches it.";
        const EXPERIMENT_OVER = "Spent plus the worst case exceeds the experiment budget: the run stops when spending reaches it.";
        const rows = d.models.map((m) => cells("td", [[m.name], [count(m.attempts)], [usd(m.worst_case_usd), ...over(m.over, m.max_request_usd > d.per_request_usd ? REQUEST_OVER : MODEL_OVER)], [usd(m.spent_usd)],
          [usd(m.per_model_usd)], m.median_latency_s === null ? ["no timing data yet", "muted"] : [`${m.median_latency_s.toFixed(1)} s (n = ${count(m.latency_n)})`],
          m.time_s === null ? ["no timing data yet", "muted"] : [UI.fmtTime(m.time_s)]]));
        const t = d.total;
        const total = cells("th", [["Total"], [count(t.attempts)], [usd(t.worst_case_usd), ...over(t.over, EXPERIMENT_OVER)], [usd(t.spent_usd)], [usd(t.per_experiment_usd)], [""],
          t.time_s === null ? ["partial: no timing data for some AI models", "muted"] : [UI.fmtTime(t.time_s) + (d.timing === "partial" ? " (partial)" : "")]]);
        const backToIcon = Defs.keepFocus(ref.body);
        ref.body.replaceChildren(
          h("div", { class: "estimate" }, h("table", { class: "estimate-table", "data-table": "estimate" },
            h("thead", {}, h("tr", {}, ...["AI model", "Attempts to run", "Worst case", "Spent", "Model budget", "Median latency", "Time"].map((t, i) =>
              h("th", { class: i ? "n" : "" }, t, ...Defs.info(bundle.definitions, t))))),
            h("tbody", {}, ...rows), h("tfoot", {}, total))),
          h("p", { class: "muted small", text: `Experiment budget is in the Total row. Request budget: ${usd(d.per_request_usd)}. Time runs the AI models side by side, ${budget.parallel} requests at once each.` }));
        backToIcon();
      }
      function schedule() {
        clearTimeout(timer);
        const seq = asks.next();
        if (!(S.puzzles.length && S.models.length)) { S.estimate = null; S.pending = false; drawCard(); return; }
        S.pending = true; drawCard();
        const settle = (value) => { if (asks.isNewest(seq) && !dead) { S.estimate = value; S.pending = false; drawCard(); } };
        timer = setTimeout(async () => {
          let form, parallel;
          try { form = readForm(bundle); parallel = readParallel(); } catch (err) { settle({ error: err.message }); return; }
          try {
            const data = await UI.api("/api/estimate/live", { method: "POST", body: { form, parallel } });
            settle({ data, attempts: form.attempts, budget: { parallel } });
          } catch (err) { settle({ error: err.message }); }
        }, 250);
      }

      // The output of Dry run: that job's log lines for this experiment id, from the log history and
      // then as they arrive. Text only.
      // A later press of the button starts the block afresh.
      // What it shows is kept in S, so a redraw of the page draws it again from the log history.
      function showResult(label, job, id, after) {
        S.result = { label, job, id, after };
        if (ref.off) ref.off();
        if (!ref.result) { ref.result = h("div", { class: "job-result" }); ref.section.append(ref.result); }
        const box = h("pre", { class: "terminal", role: "log", "aria-label": `${label} output` });
        ref.result.replaceChildren(h("h4", { text: `${label} output` }), box);
        const add = (ev) => {
          if (ev.id !== id || ev.job !== job || ev.seq <= after) return;
          const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
          const line = h("span", { class: ev.stream === "cmd" ? "cmd" : ev.stream === "stderr" ? "err" : "" });
          line.append((ev.stream === "cmd" ? "$ " : "") + ev.text + "\n");
          box.append(line);
          if (atBottom) box.scrollTop = box.scrollHeight;
        };
        UI.lines.forEach(add);
        ref.off = UI.onLines(add);
      }

      // The output belongs to one experiment id: it goes when the id changes, by typing, a new suggestion, or a loaded branch.
      function dropStaleResult() {
        if (!S.result || S.result.id === S.id.trim()) return;
        S.result = null;
        if (ref.off) { ref.off(); ref.off = null; }
        if (ref.result) { ref.result.remove(); ref.result = null; }
      }

      async function send(path, label) {
        say("");
        const after = UI.lines.length ? UI.lines[UI.lines.length - 1].seq : 0;
        try {
          const form = readForm(bundle);
          const body = path === "run" ? { form, limit: readLimit(), parallel: readParallel() } : { form };
          if (path === "run") { starting = true; controls(); say("Starting the run…"); }
          let r;
          try { r = await UI.api("/api/" + path, { method: "POST", body }); } catch (e) {
            if (path === "run") { starting = false; if (!dead) controls(); }
            throw e;
          }
          if (path === "run") {
            // A redraw (↻, or a bundle reload) makes this page dead without leaving it, and the run has started, so
            // the route decides, not the flag. Run stays disabled until the page moves on. The experiment page waits
            // for results/<id> while a run job is alive, so bring the job states in first.
            if (!location.hash.startsWith("#/new")) return;
            await UI.pollNow();
            if (!location.hash.startsWith("#/new")) return;
            UI.go("#/experiments/" + encodeURIComponent(form.id) + (bundle.release ? "?release=" + encodeURIComponent(bundle.release) : ""));
            return;
          }
          if (dead) return;
          say(`${label} started. Experiment ${r.status}.`, "ok");
          showResult(label, path, form.id, after);
        } catch (e) { say(e.message, "err"); }
      }

      // The branch field: the suggested id until edited by hand, with every existing branch offered. An id
      // that names an existing branch loads it once the edit is done (Enter, leaving the field, or picking a
      // suggestion), never mid-typing; clearing the field brings the suggestion back.
      function branchField() {
        const list = h("datalist", { id: "branch-list" });
        UI.api("/api/branches").then((rows) => {
          branches = rows.map((b) => b.id);
          list.replaceChildren(...branches.map((id) => h("option", { value: id })));
          if (ref.note && !dead) ref.note.textContent = branchNote();
        }).catch((e) => say(e.message, "err"));
        ref.id = h("input", { type: "text", list: "branch-list", "aria-label": "Branch", value: S.id, spellcheck: "false" });
        ref.id.addEventListener("input", () => {
          // A keystroke drops a load in flight, so the form is no longer that branch's until it loads again.
          if (loading) { S.branch = ""; loading = false; }
          pickSeq++;
          if (ref.id.value === "") {
            Object.assign(S, { id: "", touched: false, branch: "" });
            refreshId();
          } else {
            S.id = ref.id.value.trim(); S.touched = true;
            if (S.branch && S.id !== S.branch) S.branch = "";
          }
          dropStaleResult();
          ref.note.textContent = branchNote();
          controls(); schedule();
        });
        ref.id.addEventListener("change", () => {
          const value = ref.id.value.trim();
          if (branches.includes(value) && value !== S.branch) pickBranch(value);
        });
        ref.note = h("p", { class: "muted small", text: branchNote() });
        return h("div", { class: "branch-field" }, h("label", { class: "small" }, "Branch",
          h("span", { class: "branch-input" }, h("span", { class: "prefix", text: "results/" }), ref.id)), list, ref.note);
      }

      function paint() {
        ref.result = null;
        dropStaleResult();
        for (const [key, text, fn] of [["dry", "Dry run", () => send("dry-run", "Dry run")], ["run", "Run", () => send("run", "Run")]]) {
          ref[key] = h("button", { type: "button", text, class: key === "run" ? "primary" : "" });
          ref[key].addEventListener("click", fn);
        }
        formBox.replaceChildren(
          h("section", {}, h("h2", { text: "New Experiment" }), branchField()),
          h("section", { class: "step" }, h("h3", {}, "Puzzles", ...Defs.info(bundle.definitions, "Puzzles")), puzzleCards(bundle, choose)),
          h("section", { class: "step" }, h("h3", {}, "AI models", ...Defs.info(bundle.definitions, "AI models")), modelList(bundle, choose)),
          ref.section = h("section", { class: "step" }, h("h3", { text: "Parameters" }), numberFields(bundle, schedule),
            ref.card = h("div", { class: "estimate-card" }, ref.formula = h("p", { class: "estimate-formula", "aria-live": "polite" }), ref.body = h("div")), h("div", { class: "actions" }, ref.dry, ref.run), msg));
        if (S.result) showResult(S.result.label, S.result.job, S.result.id, S.result.after);
        controls();
        drawCard(); schedule();
      }

      const offJobs = UI.onJobs(() => { if (!dead) controls(); });
      const onHash = () => { if (!location.hash.startsWith("#/new")) cleanup(); };
      window.addEventListener("hashchange", onHash);
      cleanup = () => {
        cleanup = null;
        dead = true;
        clearTimeout(timer); offJobs(); if (ref.off) ref.off(); window.removeEventListener("hashchange", onHash);
      };

      paint();
      refreshId();
    },
  });
})();
