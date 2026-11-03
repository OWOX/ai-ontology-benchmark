// Spec: docs/specs/ui.md (New Experiment, Banners, HTTP API 4 to 11)
// New Experiment: the form, Estimate, Dry run, and Run. Reads the bundle,
// GET /api/branches, /api/default-id, and /api/experiment/<id>/config; writes only through POST /api/estimate,
// /api/dry-run, and /api/run. Run answers once its jobs start, and the page then opens the experiment's page,
// which shows the settings, Progress, Stop, and the terminal.
(function () {
  const h = UI.el;
  const NO_KEY = "no API key: add it under Models";
  const NO_ACCOUNT = "no account id: add it under Models";
  const keyProblem = (r) => r === NO_KEY || r === NO_ACCOUNT;
  const NUMBERS = [["attempts", "Attempts per input and setup: sends the same input N times"],
    ["retry_cap", "Retry cap"], ["max_output_tokens", "Max output tokens"], ["per_request_usd", "Request budget (USD)"],
    ["per_model_usd", "Model budget (USD)"], ["per_experiment_usd", "Experiment budget (USD)"]];
  // The form survives a redraw of the page (a bundle reload after a job) and resets with the release.
  const S = { release: null, id: "", touched: false, branch: "", puzzles: [], models: [], vals: {}, limit: "", parallel: "4", result: null };
  let cleanup = null;
  let idSeq = 0;

  const mine = (id, pred) => UI.jobs.some((j) => j.id === id && j.state === "running" && pred(j.job));

  function reset(bundle) {
    const d = bundle.defaults;
    Object.assign(S, { release: bundle.release, id: "", touched: false, branch: "", puzzles: bundle.puzzles.map((p) => p.name), models: [], limit: "", parallel: "4", result: null,
      vals: { attempts: d.attempts, retry_cap: d.retry_cap, max_output_tokens: d.max_output_tokens, ...d.budget } });
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
      attempts: whole(v.attempts, "attempts"), retry_cap: whole(v.retry_cap, "retry_cap"),
      max_output_tokens: whole(v.max_output_tokens, "max_output_tokens"),
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
    return h("div", { class: "model-cols" }, ...bundle.providers.map((p) => {
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
      const problem = p.models.map((m) => m.disabled_reason).find(keyProblem);
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
        if (off && !keyProblem(m.disabled_reason)) label.append(h("span", { class: "reason", text: m.disabled_reason }));
        col.append(label);
      }
      sync();
      return col;
    }));
  }

  // Two columns: the three budgets, then the rest.
  function numberFields(bundle) {
    const field = ([key, label]) => {
      const input = h("input", { type: "text", inputmode: "decimal", "aria-label": label, value: String(S.vals[key]) });
      input.addEventListener("input", () => { S.vals[key] = input.value; });
      return h("label", {}, label, input);
    };
    const limit = (() => {
      const input = h("input", { type: "text", inputmode: "numeric", "aria-label": "Limit per model", value: S.limit });
      input.addEventListener("input", () => { S.limit = input.value; });
      return h("label", {}, "Limit per model (optional): stops each AI model after N attempts", input);
    })();
    const parallel = (() => {
      const input = h("input", { type: "text", inputmode: "numeric", "aria-label": "Parallel requests", value: S.parallel });
      input.addEventListener("input", () => { S.parallel = input.value; });
      // The definition is on main: linked when the bundle knows the repository, plain text otherwise.
      const term = bundle.repo && bundle.main_sha
        ? h("a", { href: `${bundle.repo}/blob/${bundle.main_sha}/docs/definitions.md#workflows`, target: "_blank", rel: "noopener", text: "Parallel requests" })
        : document.createTextNode("Parallel requests");
      return h("label", {}, h("span", {}, term, ": attempts in flight at once per AI model, 1 to 16. Only the speed changes, never what an attempt sends or records."), input);
    })();
    const budgets = NUMBERS.filter(([k]) => k.endsWith("_usd")), rest = NUMBERS.filter(([k]) => !k.endsWith("_usd"));
    return h("div", { class: "params-cols" }, h("div", { class: "grid" }, ...budgets.map(field)),
      h("div", { class: "grid" }, ...rest.map(field), limit, parallel));
  }

  UI.registerPage("new", {
    render(bundle, params, el) {
      if (cleanup) cleanup();
      if (S.release !== bundle.release) reset(bundle);
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
        ref.estimate.disabled = mine(id, (j) => j === "estimate");
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
          controls();
        } catch (e) { say(e.message, "err"); }
      }

      const choose = () => { refreshId(); };

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
          Object.assign(S, { id: value, touched: true, release: cfg.release, puzzles: cfg.puzzles, models: cfg.models.filter((n) => enabled.has(n)),
            vals: { attempts: cfg.attempts, retry_cap: cfg.retry_cap, max_output_tokens: cfg.max_output_tokens, ...cfg.budget } });
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

      // The output of Estimate or Dry run: that job's log lines for this experiment id, from the log history and
      // then as they arrive. Text only. A later press of either button starts the block afresh.
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
          if (dead) return;
          if (path === "run") {
            // Run stays disabled until the page moves on. The experiment page waits for results/<id> while a run job
            // is alive, so bring the job states in first.
            await UI.pollNow();
            // A bundle reload in that poll can redraw this page (dead), so check the route rather than the flag.
            if (!location.hash.startsWith("#/new")) return;
            UI.go("#/experiments/" + encodeURIComponent(form.id) + (bundle.release ? "?release=" + encodeURIComponent(bundle.release) : ""));
            return;
          }
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
          controls();
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
        for (const [key, text, fn] of [["estimate", "Estimate", () => send("estimate", "Estimate")],
          ["dry", "Dry run", () => send("dry-run", "Dry run")], ["run", "Run", () => send("run", "Run")]]) {
          ref[key] = h("button", { type: "button", text, class: key === "run" ? "primary" : "" });
          ref[key].addEventListener("click", fn);
        }
        formBox.replaceChildren(
          h("section", {}, h("h2", { text: "New Experiment" }), branchField()),
          h("section", { class: "step" }, h("h3", { text: "Puzzles" }), puzzleCards(bundle, choose)),
          h("section", { class: "step" }, h("h3", { text: "AI models" }), modelList(bundle, choose)),
          ref.section = h("section", { class: "step" }, h("h3", { text: "Parameters" }), numberFields(bundle),
            h("div", { class: "actions" }, ref.estimate, ref.dry, ref.run), msg));
        if (S.result) showResult(S.result.label, S.result.job, S.result.id, S.result.after);
        controls();
      }

      const offJobs = UI.onJobs(() => { if (!dead) controls(); });
      const onHash = () => { if (!location.hash.startsWith("#/new")) cleanup(); };
      window.addEventListener("hashchange", onHash);
      cleanup = () => {
        cleanup = null;
        dead = true;
        offJobs(); if (ref.off) ref.off(); window.removeEventListener("hashchange", onHash);
      };

      paint();
      refreshId();
    },
  });
})();
