// Spec: docs/specs/ui.md (New Experiment, Banners, HTTP API 4 to 11)
// New Experiment: the form, Estimate, Dry run, Run, Stop, and Progress for the id. Reads the bundle,
// GET /api/branches, /api/default-id, and /api/experiment/<id>/config; writes only through POST /api/estimate,
// /api/dry-run, /api/run, and /api/stop. The terminal stays where it is: this page restyles it to the right.
(function () {
  const h = UI.el;
  const NO_KEY = "no API key: add it under Models";
  const NUMBERS = [["attempts", "Attempts per input and setup: sends the same input N times"],
    ["retry_cap", "Retry cap"], ["max_output_tokens", "Max output tokens"], ["per_request_usd", "Request budget (USD)"],
    ["per_model_usd", "Model budget (USD)"], ["per_experiment_usd", "Experiment budget (USD)"]];
  // The form survives a redraw of the page (a bundle reload after a job) and resets with the release.
  const S = { release: null, id: "", touched: false, branch: "", puzzles: [], models: [], vals: {}, limit: "", progId: "" };
  let cleanup = null;
  let idSeq = 0;

  const mine = (id, pred) => UI.jobs.some((j) => j.id === id && j.state === "running" && pred(j.job));

  function reset(bundle) {
    const d = bundle.defaults;
    Object.assign(S, { release: bundle.release, id: "", touched: false, branch: "", puzzles: [], models: [], limit: "", progId: "",
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

  function modelList(bundle, onChange) {
    const rel = bundle.release ? "?release=" + encodeURIComponent(bundle.release) : "";
    return h("div", {}, ...bundle.providers.map((p) => {
      const head = h("div", { class: "provider-head" }, h("span", { text: p.name }));
      if (p.models.some((m) => m.disabled_reason === NO_KEY)) {
        head.append(h("span", { class: "reason" }, "⚠️ ", h("a", { href: "#/models" + rel, text: NO_KEY })));
      }
      return h("div", { class: "provider" }, head, ...p.models.map((m) => {
        const off = !!m.disabled_reason;
        const box = h("input", { type: "checkbox" });
        box.disabled = off;
        box.checked = !off && S.models.includes(m.name);
        box.addEventListener("change", () => {
          S.models = box.checked ? [...S.models, m.name] : S.models.filter((n) => n !== m.name);
          onChange();
        });
        const label = h("label", { class: "model" + (off ? " off" : "") }, box, h("span", { text: m.name }));
        if (off && m.disabled_reason !== NO_KEY) label.append(h("span", { class: "reason", text: m.disabled_reason }));
        return label;
      }));
    }));
  }

  function numberFields() {
    return h("div", { class: "grid" }, ...NUMBERS.map(([key, label]) => {
      const input = h("input", { type: "text", inputmode: "decimal", "aria-label": label, value: String(S.vals[key]) });
      input.addEventListener("input", () => { S.vals[key] = input.value; });
      return h("label", {}, label, input);
    }), (() => {
      const input = h("input", { type: "text", inputmode: "numeric", "aria-label": "Limit per model", value: S.limit });
      input.addEventListener("input", () => { S.limit = input.value; });
      return h("label", {}, "Limit per model (optional): stops each AI model after N attempts", input);
    })());
  }

  UI.registerPage("new", {
    render(bundle, params, el) {
      if (cleanup) cleanup();
      if (S.release !== bundle.release) reset(bundle);
      const page = el.parentNode, term = document.getElementById("termbox");
      const wasOpen = term ? term.open : false;
      page.classList.add("newpage");
      if (term) term.open = true;
      const formBox = h("div"), progBox = h("section", {}, h("h3", { text: "Progress" }));
      const progMount = h("div");
      progBox.append(progMount);
      el.append(h("div", { class: "newexp" }, formBox, progBox));
      const ref = {};
      let ctl = null, dead = false;

      const msg = h("p", { class: "msg", role: "status" });
      const say = (text, kind) => { msg.className = "msg" + (kind ? " " + kind : ""); msg.textContent = text; };

      function controls() {
        if (!ref.run) return;
        const id = S.id.trim();
        const run = (j) => j.startsWith("run:"), busy = (j) => run(j) || j === "evaluate";
        ref.run.disabled = mine(id, busy);
        ref.estimate.disabled = mine(id, (j) => j === "estimate");
        ref.dry.disabled = mine(id, (j) => j === "dry-run");
        ref.stop.disabled = !mine(id, run);
      }

      function startProgress(id) {
        S.progId = id;
        if (ctl && ctl.id === id) { ctl.refresh(); return; }
        if (ctl) ctl.destroy();
        ctl = Progress.mount(progMount, id, { onSnapshot: controls });
        ctl.id = id;
      }

      function newOption() { return `New: ${S.id || "(choose puzzles and AI models)"}`; }

      async function refreshId() {
        if (S.touched || S.branch) return;
        const mine_ = ++idSeq;
        const order = (list, chosen) => list.filter((n) => chosen.includes(n));
        const models = order(bundle.providers.flatMap((p) => p.models.map((m) => m.name)), S.models);
        const q = new URLSearchParams({ models: models.join(","), puzzles: order(bundle.puzzles.map((p) => p.name), S.puzzles).join(",") });
        try {
          const r = await UI.api("/api/default-id?" + q);
          if (mine_ !== idSeq || S.touched || S.branch || dead) return;
          S.id = r.id;
          if (ref.id) ref.id.value = S.id;
          if (ref.newOpt) ref.newOpt.textContent = newOption();
          controls();
        } catch (e) { say(e.message, "err"); }
      }

      const choose = () => { refreshId(); };

      async function pickBranch(value) {
        say("");
        S.branch = value;
        if (!value) { S.touched = false; await refreshId(); if (!dead) paint(); return; }
        try {
          const cfg = await UI.api("/api/experiment/" + encodeURIComponent(value) + "/config");
          if (dead) return;
          const all = bundle.providers.flatMap((p) => p.models);
          const enabled = new Set(all.filter((m) => !m.disabled_reason).map((m) => m.name));
          const dropped = cfg.models.filter((n) => !enabled.has(n)).map((n) => {
            const m = all.find((x) => x.name === n);
            return `${n} is disabled: ${m ? m.disabled_reason : "not in the catalogue"}; resuming needs it enabled`;
          });
          Object.assign(S, { id: value, touched: true, release: cfg.release, puzzles: cfg.puzzles, models: cfg.models.filter((n) => enabled.has(n)),
            vals: { attempts: cfg.attempts, retry_cap: cfg.retry_cap, max_output_tokens: cfg.max_output_tokens, ...cfg.budget }, progId: value });
          if (cfg.release !== bundle.release) { UI.go("#/new?release=" + encodeURIComponent(cfg.release)); return; }
          paint();
          startProgress(value);
          if (dropped.length) say(`Loaded ${value}. ${dropped.join(". ")}.`, "err");
          else say(`Loaded ${value}.`, "ok");
        } catch (e) { say(e.message, "err"); }
      }

      async function send(path, label) {
        say("");
        try {
          const form = readForm(bundle);
          const body = path === "run" ? { form, limit: readLimit() } : { form };
          const r = await UI.api("/api/" + path, { method: "POST", body });
          if (dead) return;
          say(`${label} started. Experiment ${r.status}. See the terminal.`, "ok");
          if (path === "run") startProgress(form.id);
        } catch (e) { say(e.message, "err"); }
      }

      async function stop() {
        say("");
        try {
          await UI.api("/api/stop", { method: "POST", body: { id: S.id.trim() } });
          say("Stop requested. A request in flight may be paid for and never recorded, so prefer a limit for small runs.", "ok");
        } catch (e) { say(e.message, "err"); }
      }

      function paint() {
        const branch = h("select", { "aria-label": "Branch" });
        ref.newOpt = h("option", { value: "", text: newOption() });
        branch.append(ref.newOpt);
        branch.value = S.branch;
        UI.api("/api/branches").then((list) => {
          if (!branch.isConnected) return;
          branch.append(...list.map((b) => h("option", { value: b.id, text: b.id })));
          branch.value = S.branch;
        }).catch((e) => say(e.message, "err"));
        branch.addEventListener("change", () => pickBranch(branch.value));
        ref.id = h("input", { type: "text", "aria-label": "Experiment id", value: S.id });
        ref.id.addEventListener("input", () => { S.id = ref.id.value; S.touched = true; ref.newOpt.textContent = newOption(); controls(); });
        for (const [key, text, fn] of [["estimate", "Estimate", () => send("estimate", "Estimate")],
          ["dry", "Dry run", () => send("dry-run", "Dry run")], ["run", "Run", () => send("run", "Run")], ["stop", "Stop", stop]]) {
          ref[key] = h("button", { type: "button", text, class: key === "run" ? "primary" : key === "stop" ? "danger" : "" });
          ref[key].addEventListener("click", fn);
        }
        formBox.replaceChildren(
          h("section", {}, h("h2", { text: "New Experiment" }), h("label", { class: "small" }, "Branch ", branch),
            h("label", { class: "small" }, " Experiment id ", ref.id)),
          h("section", {}, h("h3", { text: "Puzzles" }), puzzleCards(bundle, choose)),
          h("section", {}, h("h3", { text: "AI models" }), modelList(bundle, choose)),
          h("section", {}, h("h3", { text: "Parameters" }), numberFields(),
            h("div", { class: "actions" }, ref.estimate, ref.dry, ref.run, ref.stop), msg));
        controls();
      }

      const offJobs = UI.onJobs(() => { if (!dead) controls(); });
      const onHash = () => { if (!location.hash.startsWith("#/new")) cleanup(); };
      window.addEventListener("hashchange", onHash);
      cleanup = () => {
        cleanup = null;
        dead = true;
        offJobs(); window.removeEventListener("hashchange", onHash);
        if (ctl) ctl.destroy();
        page.classList.remove("newpage");
        if (term) term.open = wasOpen;
      };

      paint();
      refreshId();
      if (S.progId) startProgress(S.progId);
    },
  });
})();
