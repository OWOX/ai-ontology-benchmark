// Spec: docs/specs/ui.md (About)
// The README from main, rendered, and the Project box: status (/api/project), install, tests, release, push.
(function () {
  const h = UI.el;

  let box = null;  // the live Project box, if the About page is showing
  let project = null;
  const draft = { bump: "patch", note: "" };  // the release fields, kept across a redraw such as ↻

  function busy() { return UI.jobs.some((j) => j.state === "running"); }

  function paint() {
    if (!box || !box.isConnected || !project) return;
    const p = project;
    const pk = Object.entries(p.packages).map(([k, v]) => `${k} ${v ? "ok" : "missing"}`).join(", ");
    box.querySelector(".status").textContent = `Branch ${p.branch}, ${p.clean ? "clean" : "changes"}. ${pk}. gh ${p.gh ? "found" : "missing"}.`;
    const why = p.branch === "main" ? "on main" : p.branch === "HEAD" ? "detached HEAD"
      : !p.clean ? "working tree has changes: commit them first" : "";
    box.querySelector(".state").textContent = `Latest release ${p.latest_release || "none"} on ${p.branch}.${why ? " " + why + "." : ""}`;
    const b = busy();
    box.querySelector(".install").disabled = b;
    box.querySelector(".tests").disabled = b;
    box.querySelector(".release").disabled = !!why || b;
    box.querySelector(".push").disabled = p.branch === "main" || p.branch === "HEAD" || b;
  }

  async function loadProject() {
    try { project = await UI.api("/api/project"); paint(); }
    catch (e) { say(e.message, "err"); }
  }

  function say(text, kind) {
    if (!box) return;
    const m = box.querySelector(".msg");
    m.textContent = text || ""; m.className = "msg" + (kind ? " " + kind : "");
  }

  async function start(path, body, text) {
    try { await UI.api(path, { method: "POST", body: body || {} }); say(text, "ok"); return true; }
    catch (e) { say(e.message, "err"); return false; }
  }

  async function push() {
    say("Pushing...");
    try {
      const r = await UI.api("/api/push", { method: "POST", body: {} });
      const m = box.querySelector(".msg");
      m.className = "msg ok";
      m.replaceChildren(`Pushed ${r.branch}. `);
      if (/^https?:\/\//.test(r.pr_url)) m.append(h("a", { href: r.pr_url, target: "_blank", rel: "noopener", text: "Open pull request" }));
      await Promise.all([loadProject(), UI.reload(false)]);
    } catch (e) { say(e.message, "err"); }
  }

  async function release() {
    const note = box.querySelector(".note").value.trim();
    if (!note) return say("note: enter a release note", "err");
    // A started release clears the kept fields, so the redraw after it can't offer the same release again.
    if (await start("/api/release", { bump: box.querySelector(".bump").value, note }, "Release started, see the terminal.")) {
      Object.assign(draft, { bump: "patch", note: "" });
    }
  }

  function buildBox() {
    const btn = (cls, text, fn, extra) => { const b = h("button", { type: "button", class: cls + (extra || ""), text }); b.addEventListener("click", fn); return b; };
    const bump = h("select", { class: "bump" }, ...["patch", "minor", "major"].map((v) => h("option", { text: v })));
    const note = h("input", { type: "text", class: "note", placeholder: "Note", autocomplete: "off" });
    bump.value = draft.bump; note.value = draft.note;
    bump.addEventListener("change", () => { draft.bump = bump.value; });
    note.addEventListener("input", () => { draft.note = note.value; });
    return h("section", { class: "step project" }, h("h3", { text: "Project" }),
      h("p", { class: "muted small status" }),
      h("div", { class: "actions" },
        btn("install", "Install dependencies", () => start("/api/install", {}, "Install started, see the terminal.")),
        btn("tests", "Run tests", () => start("/api/tests", {}, "Tests started, see the terminal."))),
      h("div", { class: "actions" }, h("label", { class: "inline" }, "Bump ", bump),
        note,
        btn("release", "Release", release, " primary")),
      h("p", { class: "muted small state" }),
      h("div", { class: "actions" }, btn("push", "Push and open PR", push)),
      h("p", { class: "msg", role: "status" }));
  }

  UI.registerPage("about", {
    render(bundle, params, el) {
      el.append(h("h2", { text: "About" }));
      const doc = h("div", { class: "md" });
      doc.innerHTML = window.renderMarkdown(bundle.about.markdown, UI.mdBase(bundle.about.source));
      el.append(doc);
      const src = UI.sourceLink(bundle.about.source);
      if (src) el.append(h("p", { class: "small" }, src));
      box = buildBox();
      el.append(box);
      paint();
      loadProject();
    },
  });

  // A job that ends changes the project (branch, tags, tree), so read its status again.
  UI.onJobs((jobs, ended) => {
    if (ended.some((n) => ["install", "release", "push"].includes(n))) loadProject();
    else paint();
  });
})();
