// Spec: docs/specs/ui.md (Experiment)
// One experiment: header, Summary, config, full metrics, report, Progress, and Evaluate and Commit.
// Reads GET /api/experiments/<id> and the bundle; writes through POST /api/evaluate and POST /api/commit.
(function () {
  const h = UI.el;
  const anyAlive = (snap) => UI.jobs.some((j) => j.state === "running") || (snap && Object.values(snap.jobs).includes("running"));
  const runAlive = (snap) => UI.jobs.some((j) => j.state === "running" && j.job.startsWith("run:"))
    || (snap && Object.entries(snap.jobs).some(([j, s]) => j.startsWith("run:") && s === "running"));

  function header(d, bundle) {
    const box = h("section", {}, h("h2", { text: d.id }),
      h("p", { class: "small" }, `Release ${d.release || "unknown"}. `));
    const src = UI.sourceLink(d.branch);
    if (src) { src.textContent = "branch"; box.lastChild.append(src, " "); }
    if (!d.pushed || d.running) box.lastChild.append(h("span", { class: "muted", text: "running, not pushed" }));
    const served = Object.entries(d.served_models).map(([m, ids]) => `${m}: ${ids.join(", ") || "none"}`);
    if (served.length) box.append(h("p", { class: "small muted", text: "Served models. " + served.join("; ") }));
    if (d.error) box.append(h("p", { class: "msg err", text: d.error }));
    return box;
  }

  function config(d) {
    const c = d.config;
    if (!c) return h("p", { class: "muted", text: "No config on the branch." });
    const entry = (n) => d.model_entries.find((m) => m.name === n) || { name: n };
    const models = c.models.map((n) => {
      const e = entry(n);
      return h("li", {}, h("code", { text: n }), ` ${e.api_model_id || ""} `, h("code", { text: JSON.stringify(e.params || {}) }));
    });
    const b = c.budget;
    return h("div", {},
      h("p", { class: "small", text: `Puzzles: ${c.puzzles.join(", ")}` }), h("ul", {}, ...models),
      h("p", { class: "small", text: `Attempts ${c.attempts}, retry cap ${c.retry_cap}, max output tokens ${c.max_output_tokens}. `
        + `Budgets: request $${b.per_request_usd}, model $${b.per_model_usd}, experiment $${b.per_experiment_usd}.` }));
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
      const commit = h("button", { type: "button", text: "Commit" });

      function controls() {
        const snap = state.ctl && state.ctl.snapshot();
        evaluate.disabled = !!runAlive(snap);
        commit.disabled = !!anyAlive(snap) || !(state.detail && state.detail.report);
      }

      async function loadDetail() {
        try {
          const d = state.detail = await UI.api("/api/experiments/" + encodeURIComponent(id));
          if (!root.isConnected) return;
          top.replaceChildren(header(d, bundle), section("Summary", ExpMetrics.summary(d, bundle.experiments)),
            section("Config", config(d)), section("Full metrics", ExpMetrics.full(d), true),
            section("Report", reportBox(d)));
          actions.replaceChildren(...(d.local_results ? [h("h3", { text: "Evaluate and commit" }),
            h("div", { class: "actions" }, h("label", { class: "small" }, "Score under release ", evalRelease), evaluate, commit), result] : []));
          controls();
        } catch (e) { top.replaceChildren(h("h2", { text: id }), h("p", { class: "msg err", text: e.message })); }
      }

      evaluate.addEventListener("click", async () => {
        result.className = "msg"; result.textContent = "";
        try {
          await UI.api("/api/evaluate", { method: "POST", body: { id, release: evalRelease.value || null } });
          state.ctl.refresh();
        } catch (e) { result.className = "msg err"; result.textContent = e.message; }
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
