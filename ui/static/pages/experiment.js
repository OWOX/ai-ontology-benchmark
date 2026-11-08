// Spec: docs/specs/ui.md (Experiment)
// One experiment as a workspace: a score card and a progress bar across the top, then two columns. Left: header, Stop, and Continue, the settings
// read-only, the Cube panel, the Plan tree, Summary, full metrics, report, and Evaluate and Commit. Right: the terminal.
// Reads GET /api/experiments/<id>, GET /api/experiment/<id>/config, and the bundle; writes through POST /api/stop, /api/run, /api/evaluate,
// and /api/commit.
(function () {
  const h = UI.el;
  // Jobs of this experiment only: the log's job id is the experiment id.
  const mine = UI.mine;
  const snapRunning = (snap, pred) => !!snap && Object.entries(snap.jobs).some(([j, s]) => s === "running" && pred(j));

  function header(d) {
    const box = h("section", {}, h("h2", { text: d.id }),
      h("p", { class: "small" }, `Release ${d.release || "unknown"}. `));
    const src = UI.sourceLink(d.branch);
    if (src) { src.textContent = "branch"; box.lastChild.append(src, " "); }
    if (d.pushed === false) box.lastChild.append(h("span", { class: "muted", text: "running, not pushed" }));
    const served = Object.entries(d.served_models).map(([m, ids]) => `${m}: ${ids.join(", ") || "none"}`);
    if (served.length) box.append(h("p", { class: "small muted", text: "Served models. " + served.join("; ") }));
    if (d.error) box.append(h("p", { class: "msg err", text: d.error }));
    return box;
  }

  // The settings as the New Experiment form shows them, read-only: every puzzle and catalogue model, with the
  // experiment's own picked, and its parameters in disabled fields.
  // Two columns, as on New Experiment: the three budgets, then the rest.
  const PARAMS = [[["Request budget (USD)", (c) => c.budget.per_request_usd], ["Model budget (USD)", (c) => c.budget.per_model_usd],
    ["Experiment budget (USD)", (c) => c.budget.per_experiment_usd]],
  [["Attempts per input and setup", (c) => c.attempts], ["Retry cap", (c) => c.retry_cap], ["Max output tokens", (c) => c.max_output_tokens],
    ["Reasoning effort", (c) => c.reasoning_effort || "provider default"]]];

  function settings(d, bundle) {
    const c = d.config;
    if (!c) return [h("p", { class: "muted", text: "No config on the branch." })];
    const tick = (on) => { const b = h("input", { type: "checkbox", disabled: "" }); b.checked = on; return b; };
    // Only the experiment's own puzzles and AI models, in its config order.
    const cards = c.puzzles.map((name) => {
      const p = bundle.puzzles.find((x) => x.name === name);
      return h("div", { class: "card ro sel" }, p && p.n ? cubeNet(solvedState(p.n), { width: 96, height: 72 }) : null,
        h("div", { class: "name", text: name }), p ? h("div", { class: "muted small", text: `${p.input_count} inputs` }) : null);
    });
    const entries = d.model_entries;
    const providerOf = (m) => (entries.find((e) => e.name === m) || {}).provider || "";
    // Provider columns in the catalogue order, as on New Experiment.
    const order = bundle.providers.map((p) => p.name);
    const rank = (p) => (order.includes(p) ? order.indexOf(p) : order.length);
    const providers = [...new Set(c.models.map(providerOf))].sort((a, b) => rank(a) - rank(b));
    const cols = providers.map((name) => h("div", { class: "model-col" },
      h("label", { class: "provider-head" }, tick(true), h("span", { text: name })),
      ...c.models.filter((m) => providerOf(m) === name).map((m) => {
        const e = entries.find((x) => x.name === m);
        const label = h("label", { class: "model" }, tick(true), h("span", { text: m }));
        if (e) label.title = `${e.api_model_id || ""} ${JSON.stringify(e.params || {})}`.trim();
        return label;
      })));
    const fields = PARAMS.map((col) => h("div", { class: "grid" },
      ...col.map(([label, get]) => h("label", {}, label, h("input", { type: "text", disabled: "", value: String(get(c)) })))));
    return [h("section", { class: "step" }, h("h3", { text: "Puzzles" }), h("div", { class: "cards" }, ...cards)),
      h("section", { class: "step" }, h("h3", { text: "AI models" }), h("div", { class: "model-cols" }, ...cols)),
      h("section", { class: "step" }, h("h3", { text: "Parameters" }), h("div", { class: "params-cols" }, ...fields))];
  }

  function reportBox(d) {
    if (!d.report) return h("p", { class: "muted", text: "No report on the branch." });
    const md = h("div", { class: "md" });
    md.innerHTML = window.renderMarkdown(d.report.markdown, UI.mdBase(d.report.source));
    const src = UI.sourceLink(d.report.source);
    return h("div", {}, md, ...(src ? [src] : []));
  }

  async function openCommit(id, msg, onDone) {
    msg.className = "msg"; msg.textContent = "";
    const p = await UI.api("/api/commit/" + encodeURIComponent(id));
    const err = h("p", { class: "msg err" });
    const confirm = h("button", { type: "button", class: "primary", text: "Confirm" });
    const cancel = h("button", { type: "button", text: "Cancel" });
    const dlg = h("dialog", {}, h("h3", { text: "Commit results" }),
      h("p", {}, "Branch: ", h("code", { text: p.branch }), " from ", h("code", { text: String(p.base).slice(0, 10) })),
      h("p", { text: "Files:" }), h("ul", {}, ...p.files.map((f) => h("li", { text: f }))), h("pre", { text: p.diffstat }),
      err, h("div", { class: "actions" }, cancel, confirm));
    cancel.addEventListener("click", () => dlg.close());
    dlg.addEventListener("close", () => dlg.remove());
    confirm.addEventListener("click", async () => {
      confirm.disabled = true;
      try {
        const r = await UI.api("/api/commit", { method: "POST", body: { id } });
        dlg.close();
        msg.className = "msg ok";
        msg.replaceChildren(`Committed ${String(r.commit).slice(0, 10)} on ${r.branch}. `);
        if (/^https?:\/\//.test(r.pr_url)) msg.append(h("a", { href: r.pr_url, target: "_blank", rel: "noopener", text: "Open pull request" }));
        else msg.append(r.pr_url || "");
        onDone();
      } catch (e) { err.textContent = e.message; confirm.disabled = false; }
    });
    document.body.append(dlg);
    dlg.showModal();
  }

  const CARD_NOTE = "* computed by the UI from the raw records, for display only. Pooled over all puzzles and setups of the experiment, so not the per-puzzle and per-setup values of the report. Outcomes are re-validated under the experiment's release, so they can differ from the stored outcomes in the progress bar.";
  const CARD_COLUMNS = [["balanced_precision", "Balanced precision", "pct"], ["coverage", "Coverage", "pct"],
    ["hallucination_rate", "Hallucination", "pct"], ["reason_hallucination_rate", "Reason hallucination", "pct"],
    ["critical_thinking", "Critical thinking", "pct"], ["cost_usd", "Cost so far", "usd"], ["cost_efficiency", "Cost efficiency", "usd"]];
  const cardValue = (v, kind) => (typeof v !== "number" ? "n/a" : kind === "pct" ? ExpMetrics.pct(v) : UI.usd(v, { fixed: kind === "usd" && v < 1 ? 4 : 2 })) + " *";
  const spendBar = (label, spent, limit) => {
    const known = typeof spent === "number" && typeof limit === "number" && limit > 0;
    const part = known ? Math.min(100, (spent / limit) * 100) : 0;
    const fill = h("div", { class: "spend-fill" + (known && spent > limit ? " over" : "") });
    fill.style.width = part + "%";
    return h("div", { class: "spend-row" }, h("span", { class: "small", text: label }), h("div", { class: "spend" }, fill),
      h("span", { class: "small n", text: `${typeof spent === "number" ? UI.usd(spent, { fixed: 2 }) : "n/a"} of ${typeof limit === "number" ? UI.usd(limit, { fixed: 2 }) : "n/a"} *` }));
  };

  // The score card from GET /api/scorecard/<id>: one row per AI model, spend against each budget, elapsed, and time left.
  function scoreCard(d, defs) {
    const cells = (tag, values) => h("tr", {}, ...values.map((t, i) => h(tag, { class: i ? "n" : "", text: t })));
    const t = d.total;
    const time = (v) => (typeof v === "number" ? UI.fmtTime(v) : "n/a") + " *";
    return h("section", { class: "score-card" },
      h("h3", {}, "Score card ", d.live ? h("span", { class: "live", text: "live" }) : null),
      h("div", { class: "table-wrap" }, h("table", { class: "score-table", "data-table": "score-card" },
        h("thead", {}, h("tr", {}, ...["AI model", "Done", ...CARD_COLUMNS.map((c) => c[1])].map((t, i) =>
          h("th", { class: i ? "n" : "" }, t, ...Defs.info(defs, t))))),
        h("tbody", {}, ...d.models.map((m) => cells("td", [m.name, `${ExpMetrics.grouped(m.done)} of ${ExpMetrics.grouped(m.planned)}`,
          ...CARD_COLUMNS.map(([k, , kind]) => cardValue(m[k], kind))]))))),
      h("div", { class: "spend-rows" }, ...d.models.map((m) => spendBar(`${m.name} against the model budget`, m.cost_usd, t.per_model_usd)),
        spendBar("All AI models against the experiment budget", t.cost_usd, t.per_experiment_usd)),
      h("p", { class: "small", text: `Elapsed ${time(t.elapsed_s)}. Time left ${time(t.time_left_s)}.` }),
      h("p", { class: "muted small", text: CARD_NOTE }));
  }

  // A foldable block with an 18px heading. The returned element keeps its open state when its body is replaced.
  function block(title, body, open) {
    const det = h("details", { class: "blk" }, h("summary", { text: title }), body);
    det.open = !!open;
    return det;
  }

  UI.registerPage("experiment", {
    fresh: true,  // render() loads the detail itself, so the router skips the cached draw
    render(bundle, params, el) {
      const id = decodeURIComponent(params.parts[0]);
      const root = h("div", { class: "exp-detail" });
      const headBox = h("div"), bannerBox = h("div"), settingsBody = h("div"), cubeBody = h("div"), planBody = h("div");
      const resultsBox = h("div"), actions = h("div"), result = h("p", { class: "msg", role: "status" });
      const settingsBlock = block("Settings", settingsBody, true);
      const cardBox = h("div", { class: "score-box" });
      const bar = ProgressView.bar(Progress.COLORS, Progress.OUTCOMES);
      const termBox = h("div", { class: "ws-right" });
      root.append(cardBox, bar.node, h("div", { class: "workspace" },
        h("div", { class: "ws-left" }, headBox, bannerBox, settingsBlock, block("Cube", cubeBody, true), block("Plan", planBody, true),
          resultsBox, actions),
        termBox));
      el.append(root);
      const state = { detail: null, ctl: null, off: null, term: null, touched: false };
      settingsBlock.firstChild.addEventListener("click", () => { state.touched = true; });  // only a click by hand
      const evalRelease = h("select", { "aria-label": "Score under release" }, h("option", { value: "", text: "the experiment's release" }),
        ...bundle.releases.map((v) => h("option", { value: v, text: v })));
      const evaluate = h("button", { type: "button", text: "Evaluate" });
      const stop = h("button", { type: "button", class: "danger", text: "Stop" });
      const stopMsg = h("span", { class: "msg small", role: "status" });
      // Continue resumes a stopped run with the config saved on the branch, so the server answers `unchanged` and
      // `run` skips the attempts that already have a record. Parallel requests and the limit are not part of the config.
      const cont = h("button", { type: "button", class: "primary", text: "Continue" });
      const contParallel = h("input", { type: "number", min: "1", max: "16", step: "1", value: "4", class: "num-short", "aria-label": "Parallel requests" });
      const contLimit = h("input", { type: "text", inputmode: "numeric", class: "num-short", placeholder: "none", "aria-label": "Limit per model" });
      const contBox = h("span", { class: "exp-continue" }, cont, h("label", { class: "small" }, "Parallel requests ", contParallel),
        h("label", { class: "small" }, "Limit per model ", contLimit));
      const contNote = h("p", { class: "muted small", text: "Continue needs this experiment's results in this checkout: check out its branch first." });
      let starting = false;
      const commit = h("button", { type: "button", text: "Commit" });

      // The score card loads once, and again on the snapshot poll at most every 5 seconds while a run job of the
      // experiment is alive. It reads the job state the page already holds. When that state changes, and when the
      // last job ends, it loads again at once; a load asked for while one is in flight is queued, never dropped.
      const card = { busy: false, queued: false, last: 0, running: null };
      async function loadCard() {
        if (card.busy) { card.queued = true; return; }
        card.busy = true; card.last = Date.now();
        try {
          const d = await UI.api("/api/scorecard/" + encodeURIComponent(id));
          if (root.isConnected) Defs.holdRedraw(cardBox, () => { if (!root.isConnected) return; const back = Defs.keepFocus(cardBox); cardBox.replaceChildren(scoreCard(d, bundle.definitions)); back(); });
        } catch (e) { /* no branch yet, or a read error: the header shows it */ } finally { card.busy = false; }
        if (card.queued && root.isConnected) { card.queued = false; loadCard(); }
      }
      function cardSync() {
        if (!root.isConnected) return;
        const run = (j) => j.startsWith("run:");
        const running = mine(id, run) || snapRunning(state.ctl && state.ctl.snapshot(), run);
        if (running !== card.running) { card.running = running; loadCard(); }
        else if (running && Date.now() - card.last >= 5000) loadCard();
      }

      // Settings fold while a run job is alive and open otherwise, until the user folds or unfolds it by hand.
      // The job state can arrive after the page, so this runs again on every snapshot and job poll.
      function autoSettings() {
        if (state.touched || !state.detail) return;
        const run = (j) => j.startsWith("run:");
        settingsBlock.open = !(mine(id, run) || snapRunning(state.ctl && state.ctl.snapshot(), run));
      }

      function controls() {
        const snap = state.ctl && state.ctl.snapshot();
        const any = () => true, run = (j) => j.startsWith("run:"), evalJob = (j) => run(j) || j === "evaluate";
        const d = state.detail;
        evaluate.disabled = mine(id, evalJob) || snapRunning(snap, evalJob);
        const running = mine(id, run) || snapRunning(snap, run);
        stop.disabled = !running;
        // Shown once the experiment has attempts left and no run job is alive; the server's 409s stay the authority.
        const t = state.ctl ? state.ctl.totals() : { done: 0, planned: 0 };
        contBox.hidden = running || !snap || t.done >= t.planned;
        cont.disabled = starting || mine(id, evalJob) || snapRunning(snap, evalJob) || !(d && d.local_results);
        contNote.hidden = contBox.hidden || !d || d.local_results;
        // The server's 409s stay the authority; this only keeps the button honest.
        commit.disabled = mine(id, any) || snapRunning(snap, any) || !(d && d.local_results && d.local_report);
      }

      async function loadDetail() {
        try {
          const d = state.detail = await UI.api("/api/experiments/" + encodeURIComponent(id));
          if (!root.isConnected) return;
          // The settings and inputs come from the bundle, so it must be the experiment's own release.
          if (d.release && d.release !== bundle.release) { UI.go(`#/experiments/${encodeURIComponent(id)}?release=${encodeURIComponent(d.release)}`); return; }
          headBox.replaceChildren(header(d), h("div", { class: "actions exp-stop" }, stop, contBox, stopMsg), contNote);
          settingsBody.replaceChildren(...settings(d, bundle));
          autoSettings();
          Defs.holdRedraw(resultsBox, () => {
            if (!root.isConnected) return;
            const backToIcon = Defs.keepFocus(resultsBox);
            resultsBox.replaceChildren(block("Summary", ExpMetrics.summary(d, bundle.experiments, bundle.definitions), false),
              block("Full metrics", ExpMetrics.full(d, bundle.definitions), false), block("Report", reportBox(d), false));
            backToIcon();
          });
          actions.replaceChildren(...(d.local_results ? [block("Evaluate and commit",
            h("div", {}, h("div", { class: "actions by-field" }, h("label", { class: "small" }, "Score under release ", evalRelease), evaluate, commit), result), true)] : []));
          controls();
        } catch (e) {
          if (!root.isConnected) return;
          // A run that has started but not yet committed its branch: wait for it rather than show "not found".
          // The job states may be a poll behind (a page opened right after Run, or reloaded), so fetch them first.
          await UI.pollNow();
          if (!root.isConnected) return;
          if (UI.jobs.some((j) => j.id === id && j.job.startsWith("run:") && j.state === "running")) {
            headBox.replaceChildren(h("h2", { text: id }), h("p", { class: "muted", text: `Waiting for the run to create results/${id}…` }));
            setTimeout(loadDetail, 2000);
            return;
          }
          // Blame the run only when the server's branch watcher said it stopped first (API 7).
          const step = UI.lines.filter((l) => l.id === id && l.job === "branch").pop();
          const text = step && step.stream === "stderr" ? step.text : e.message;
          headBox.replaceChildren(h("h2", { text: id }), h("p", { class: "msg err", text }));
        }
      }

      evaluate.addEventListener("click", async () => {
        result.className = "msg"; result.textContent = "";
        try {
          await UI.api("/api/evaluate", { method: "POST", body: { id, release: evalRelease.value || null } });
          state.ctl.refresh();
        } catch (e) { result.className = "msg err"; result.textContent = e.message; }
      });
      stop.addEventListener("click", async () => {
        stopMsg.className = "msg small"; stopMsg.textContent = "";
        try {
          await UI.api("/api/stop", { method: "POST", body: { id } });
          stopMsg.className = "msg small ok";
          stopMsg.textContent = "Stop requested. A request in flight may be paid for and never recorded, so prefer a limit for small runs.";
        } catch (e) { stopMsg.className = "msg small err"; stopMsg.textContent = e.message; }
      });
      cont.addEventListener("click", async () => {
        stopMsg.className = "msg small"; stopMsg.textContent = "";
        const parallel = Number(contParallel.value.trim());
        const limitText = contLimit.value.trim(), limit = limitText === "" ? null : Number(limitText);
        try {
          if (!Number.isInteger(parallel) || parallel < 1 || parallel > 16) throw new Error("parallel must be a whole number from 1 to 16");
          if (limit !== null && (!Number.isInteger(limit) || limit < 1)) throw new Error("limit must be a whole number of at least 1");
          starting = true; controls();
          const form = await UI.api("/api/experiment/" + encodeURIComponent(id) + "/config");
          await UI.api("/api/run", { method: "POST", body: { form, limit, parallel } });
          stopMsg.className = "msg small ok"; stopMsg.textContent = "Continuing the run.";
          await UI.pollNow();
        } catch (e) { stopMsg.className = "msg small err"; stopMsg.textContent = e.message; }
        finally { starting = false; if (root.isConnected) controls(); }
      });
      commit.addEventListener("click", () => openCommit(id, result, loadDetail).catch((e) => { result.className = "msg err"; result.textContent = e.message; }));

      const onSnapshot = () => { controls(); autoSettings(); cardSync(); bar.update(state.ctl.totals()); if (state.term) state.term.sync(); };
      // The terminal replays the log history on mount, before the first snapshot: the host answers empty until then.
      const host = { records: () => (state.ctl ? state.ctl.records() : new Map()), pending: () => (state.ctl ? state.ctl.pending() : {}),
        inputs: () => (state.ctl ? state.ctl.inputs() : new Map()) };
      state.ctl = Progress.mount(planBody, id, { onSnapshot, bannerEl: bannerBox, onStep: (step) => state.term && state.term.focus(step) });
      state.term = Terminal.mount(termBox, id, host);
      cubeBody.append(state.ctl.panelNode);
      bar.update(state.ctl.totals());
      state.off = UI.onJobs((jobs, ended) => {
        if (!root.isConnected) { state.off(); state.term.destroy(); return; }
        if (ended && ended.length) { loadDetail(); state.ctl.refresh(); }  // a finished evaluate brings the report
        controls(); autoSettings(); cardSync();
      });
      loadDetail();
      loadCard();
    },
  });
})();
