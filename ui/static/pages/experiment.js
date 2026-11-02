// Spec: docs/specs/ui.md (Experiment)
// One experiment: header, Stop, the settings read-only, Summary, full metrics, report, Progress, and Evaluate and Commit.
// Reads GET /api/experiments/<id> and the bundle; writes through POST /api/stop, /api/evaluate, and /api/commit.
(function () {
  const h = UI.el;
  // Jobs of this experiment only: the log's job id is the experiment id.
  const mine = (id, pred) => UI.jobs.some((j) => j.id === id && j.state === "running" && pred(j.job));
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
  const PARAMS = [["Attempts per input and setup", (c) => c.attempts], ["Retry cap", (c) => c.retry_cap],
    ["Max output tokens", (c) => c.max_output_tokens], ["Request budget (USD)", (c) => c.budget.per_request_usd],
    ["Model budget (USD)", (c) => c.budget.per_model_usd], ["Experiment budget (USD)", (c) => c.budget.per_experiment_usd]];

  function settings(d, bundle) {
    const c = d.config;
    if (!c) return [h("p", { class: "muted", text: "No config on the branch." })];
    const tick = (on, mixed) => { const b = h("input", { type: "checkbox", disabled: "" }); b.checked = on; b.indeterminate = !!mixed; return b; };
    const names = [...new Set([...bundle.puzzles.map((p) => p.name), ...c.puzzles])];
    const cards = names.map((name) => {
      const p = bundle.puzzles.find((x) => x.name === name);
      const on = c.puzzles.includes(name);
      return h("div", { class: "card ro" + (on ? " sel" : " off") }, p && p.n ? cubeNet(solvedState(p.n), { width: 96, height: 72 }) : null,
        h("div", { class: "name", text: name }), p ? h("div", { class: "muted small", text: `${p.input_count} inputs` }) : null);
    });
    const entries = d.model_entries;
    const providers = [...new Set([...bundle.providers.map((p) => p.name), ...entries.map((e) => e.provider)])];
    const cols = providers.map((name) => {
      const catalogue = (bundle.providers.find((p) => p.name === name) || { models: [] }).models.map((m) => m.name);
      const models = [...new Set([...catalogue, ...entries.filter((e) => e.provider === name).map((e) => e.name)])];
      const n = models.filter((m) => c.models.includes(m)).length;
      return h("div", { class: "model-col" }, h("label", { class: "provider-head" }, tick(n > 0 && n === models.length, n > 0 && n < models.length), h("span", { text: name })),
        ...models.map((m) => {
          const e = entries.find((x) => x.name === m);
          const label = h("label", { class: "model" + (c.models.includes(m) ? "" : " off") }, tick(c.models.includes(m)), h("span", { text: m }));
          if (e) label.title = `${e.api_model_id || ""} ${JSON.stringify(e.params || {})}`.trim();
          return label;
        }));
    });
    const fields = PARAMS.map(([label, get]) => h("label", {}, label, h("input", { type: "text", disabled: "", value: String(get(c)) })));
    return [h("section", { class: "step" }, h("h3", { text: "Puzzles" }), h("div", { class: "cards" }, ...cards)),
      h("section", { class: "step" }, h("h3", { text: "AI models" }), h("div", { class: "model-cols" }, ...cols)),
      h("section", { class: "step" }, h("h3", { text: "Parameters" }), h("div", { class: "grid" }, ...fields))];
  }

  function reportBox(d) {
    if (!d.report) return h("p", { class: "muted", text: "No report on the branch." });
    const md = h("div", { class: "md" });
    md.innerHTML = window.renderMarkdown(d.report.markdown, d.report.source ? d.report.source.replace(/[^/]*$/, "") : "");
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

  function section(title, body, folded) {
    if (!folded) return h("section", {}, h("h3", { text: title }), body);
    return h("details", {}, h("summary", { text: title }), body);
  }

  UI.registerPage("experiment", {
    render(bundle, params, el) {
      const id = decodeURIComponent(params.parts[0]);
      const root = h("div", { class: "exp-detail" });
      const top = h("div"), progress = h("div"), actions = h("section"), result = h("p", { class: "msg", role: "status" });
      root.append(top, section("Progress", progress), actions);
      el.append(root);
      const state = { detail: null, ctl: null, off: null };
      const evalRelease = h("select", { "aria-label": "Score under release" }, h("option", { value: "", text: "the experiment's release" }),
        ...bundle.releases.map((v) => h("option", { value: v, text: v })));
      const evaluate = h("button", { type: "button", text: "Evaluate" });
      const stop = h("button", { type: "button", class: "danger", text: "Stop" });
      const stopMsg = h("span", { class: "msg small", role: "status" });
      const commit = h("button", { type: "button", text: "Commit" });

      function controls() {
        const snap = state.ctl && state.ctl.snapshot();
        const any = () => true, run = (j) => j.startsWith("run:"), evalJob = (j) => run(j) || j === "evaluate";
        const d = state.detail;
        evaluate.disabled = mine(id, evalJob) || snapRunning(snap, evalJob);
        stop.disabled = !(mine(id, run) || snapRunning(snap, run));
        // The server's 409s stay the authority; this only keeps the button honest.
        commit.disabled = mine(id, any) || snapRunning(snap, any) || !(d && d.local_results && d.local_report);
      }

      async function loadDetail() {
        try {
          const d = state.detail = await UI.api("/api/experiments/" + encodeURIComponent(id));
          if (!root.isConnected) return;
          // The settings and inputs come from the bundle, so it must be the experiment's own release.
          if (d.release && d.release !== bundle.release) { UI.go(`#/experiments/${encodeURIComponent(id)}?release=${encodeURIComponent(d.release)}`); return; }
          top.replaceChildren(header(d), h("div", { class: "actions exp-stop" }, stop, stopMsg), ...settings(d, bundle),
            section("Summary", ExpMetrics.summary(d, bundle.experiments)), section("Full metrics", ExpMetrics.full(d), true),
            section("Report", reportBox(d)));
          actions.replaceChildren(...(d.local_results ? [h("h3", { text: "Evaluate and commit" }),
            h("div", { class: "actions" }, h("label", { class: "small" }, "Score under release ", evalRelease), evaluate, commit), result] : []));
          controls();
        } catch (e) {
          if (!root.isConnected) return;
          // A run that has started but not yet committed its branch: wait for it rather than show "not found".
          if (UI.jobs.some((j) => j.id === id && j.state === "running")) {
            top.replaceChildren(h("h2", { text: id }), h("p", { class: "muted", text: `Waiting for the run to create results/${id}…` }));
            setTimeout(loadDetail, 2000);
            return;
          }
          top.replaceChildren(h("h2", { text: id }), h("p", { class: "msg err", text: e.message }));
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
      commit.addEventListener("click", () => openCommit(id, result, loadDetail).catch((e) => { result.className = "msg err"; result.textContent = e.message; }));

      state.ctl = Progress.mount(progress, id, { onSnapshot: controls });
      state.off = UI.onJobs((jobs, ended) => {
        if (!root.isConnected) { state.off(); return; }
        if (ended && ended.length) { loadDetail(); state.ctl.refresh(); }  // a finished evaluate brings the report
        controls();
      });
      loadDetail();
    },
  });
})();
