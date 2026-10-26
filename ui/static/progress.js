// Spec: docs/specs/ui.md (Progress, Arc colours, Polling)
// The Progress block shared by the Experiment page and New Experiment: Cube panel, legend, banners, and
// one accordion per AI model and puzzle with a ring per input. Reads GET /api/state/<id>; writes only its DOM.
// Interface: Progress.mount(el, experimentId, opts) -> {refresh(), destroy(), snapshot()} and Progress.COLORS.
// opts.onSnapshot(snap) runs after every applied snapshot. Mounting again replaces the previous mount.
(function () {
  const h = UI.el;
  // The one arc colour table: the legend, the rings, the counts, and the Cube panel all read it.
  const COLORS = {
    pending: "#d0d4da", in_progress: "#f2b705", success: "#2e9e5b", failure: "#d64545",
    hallucination: "#8e44ad", malformed_output: "#1a9bb0", infrastructure_failure: "#5d6d7e",
  };
  const OUTCOMES = ["success", "failure", "hallucination", "malformed_output", "infrastructure_failure"];
  const POLL_MS = 1500;
  const key = (model, input, setup, attempt) => `${model}|${input}|${setup}|${attempt}`;
  let current = null;

  function mount(el, id, opts) {
    if (current) current.destroy();
    const o = opts || {};
    const S = { snap: null, shape: "", jobs: {}, inputs: new Map(), records: new Map(), counts: new Map(),
                arcs: new Map(), pending: {}, fresh: [], lastErr: {}, puzzles: [], timer: null, dead: false,
                loading: false, runSig: "" };
    const running = (m) => S.jobs["run:" + m] === "running";
    const panel = CubePanel({
      id, input: (i) => S.inputs.get(i), pending: (m) => S.pending[m] || null,
      hasRecord: (m, i, s, a) => S.records.has(key(m, i, s, a)),
    });
    const status = h("p", { class: "muted small", text: "Loading progress." });
    const banners = h("div");
    const tree = h("div");
    el.replaceChildren(panel.node, ProgressView.legend(COLORS, OUTCOMES), banners, status, tree);

    const alive = () => Object.values(S.jobs).includes("running");
    const countFor = (m, p) => {
      if (!S.counts.has(m + "|" + p)) S.counts.set(m + "|" + p, { done: 0, out: {} });
      return S.counts.get(m + "|" + p);
    };
    const total = (p) => S.snap.inputs.filter((i) => i.puzzle === p).length * S.snap.setups.length * S.snap.attempts;

    function fill(box, done, all, out) {
      box.replaceChildren(h("span", { text: `${done}/${all}` }));
      for (const k of OUTCOMES) if (out[k]) box.append(ProgressView.chip(COLORS, k, out[k]));
    }

    function headers(model, puzzle) {
      const pick = (v) => tree.querySelector(`[data-counts="${CSS.escape(v)}"]`);
      const pb = pick(model + "|" + puzzle), mb = pick(model);
      if (pb) { const c = countFor(model, puzzle); fill(pb, c.done, total(puzzle), c.out); }
      if (!mb) return;
      let done = 0, all = 0; const out = {};
      for (const p of S.puzzles) {
        const c = countFor(model, p);
        done += c.done; all += total(p);
        for (const [k, n] of Object.entries(c.out)) out[k] = (out[k] || 0) + n;
      }
      fill(mb, done, all, out);
    }

    function arcState(k, model) {
      const rec = S.records.get(k);
      return rec ? rec.outcome : S.pending[model] === k ? "in_progress" : "pending";
    }

    function paint(k) {
      const path = S.arcs.get(k);
      if (!path) return;
      const [model, inputId, setup, attempt] = k.split("|");
      const state = arcState(k, model), rec = S.records.get(k);
      path.setAttribute("fill", COLORS[state] || COLORS.pending);
      path.classList.toggle("pulse", state === "in_progress");
      path.classList.toggle("done", !!rec);
      let t = `${setup}, attempt ${attempt}: ${state.replace("_", " ")}`;
      if (rec && S.inputs.get(inputId).validity !== "valid") t += `, mismatch: ${rec.mismatch ? "yes" : "no"}`;
      path.firstChild.textContent = t;
    }

    function ring(model, input) {
      const n = S.snap.setups.length * S.snap.attempts;
      const root = svg("svg", { viewBox: "0 0 100 100", width: 84, height: 84 });
      const gap = n > 1 ? Math.min(0.06, 0.3 * 2 * Math.PI / n) : 0;
      let idx = 0;
      for (const setup of S.snap.setups) {
        for (let a = 1; a <= S.snap.attempts; a++, idx++) {
          const a0 = -Math.PI / 2 + (idx / n) * 2 * Math.PI + gap / 2;
          const a1 = -Math.PI / 2 + ((idx + 1) / n) * 2 * Math.PI - gap / 2;
          const path = svg("path", { d: ProgressView.arcPath(50, 50, 38, 48, a0, a1), class: "arc" });
          path.append(svg("title"));
          const k = key(model, input.input_id, setup, a);
          S.arcs.set(k, path);
          path.addEventListener("click", () => panel.open(model, input.input_id, setup, a));
          root.append(path);
          paint(k);
        }
      }
      root.append(cubeNet(input.state, { x: 20, y: 29, width: 60, height: 45 }));
      return root;
    }

    function build() {
      tree.replaceChildren();
      for (const model of S.snap.models) {
        const mDet = h("details", {}, h("summary", {}, h("strong", { text: model }), h("span", { class: "counts", "data-counts": model })));
        for (const puzzle of S.puzzles) {
          const body = h("div", { class: "body" });
          const pDet = h("details", {}, h("summary", {}, h("span", { text: puzzle }),
            h("span", { class: "counts", "data-counts": `${model}|${puzzle}` })), body);
          let drawn = false;
          pDet.addEventListener("toggle", () => {  // rows render when the accordion first opens
            if (!pDet.open || drawn) return;
            drawn = true;
            for (const input of S.snap.inputs.filter((i) => i.puzzle === puzzle)) {
              body.append(h("div", { class: "irow" }, ring(model, input), h("div", { class: "meta" },
                h("div", { class: "id", text: input.input_id }),
                h("div", { text: `depth ${input.scramble_depth}, ${input.validity}` }))));
            }
          });
          mDet.append(pDet);
        }
        tree.append(mDet);
        S.puzzles.forEach((p) => headers(model, p));
      }
    }

    function add(rec) {
      const input = S.inputs.get(rec.input_id);
      if (!input) return;
      const k = key(rec.model, rec.input_id, rec.setup, rec.attempt_number);
      const c = countFor(rec.model, input.puzzle), old = S.records.get(k);
      if (old && old.outcome === rec.outcome) return;
      if (old) { c.done--; c.out[old.outcome]--; }
      else S.fresh.push(rec);
      S.records.set(k, rec);
      c.done++; c.out[rec.outcome] = (c.out[rec.outcome] || 0) + 1;
      paint(k);
      headers(rec.model, input.puzzle);
    }

    // The attempt a running model is on: the first without a record, in run's loop order. An inference.
    function firstPending(model) {
      for (const input of S.snap.inputs) for (const setup of S.snap.setups) {
        for (let a = 1; a <= S.snap.attempts; a++) {
          const k = key(model, input.input_id, setup, a);
          if (!S.records.has(k)) return k;
        }
      }
      return null;
    }

    const drawBanners = () => banners.replaceChildren(...ProgressView.banners(S.jobs,
      Object.fromEntries(Object.keys(S.jobs).map((j) => [j, S.lastErr[id + "\u0000" + j]]))));

    // A later snapshot only adds records, so open accordions stay open; a new shape rebuilds the tree.
    function apply(snap) {
      const shape = JSON.stringify([id, snap.release, snap.models, snap.attempts, snap.inputs.map((i) => i.input_id)]);
      const rebuild = shape !== S.shape;
      S.fresh = [];
      if (rebuild) {
        Object.assign(S, { shape, records: new Map(), counts: new Map(), arcs: new Map(), pending: {}, inputs: new Map() });
        S.puzzles = [...new Set(snap.inputs.map((i) => i.puzzle))];
        for (const i of snap.inputs) S.inputs.set(i.input_id, i);
      }
      S.snap = snap; S.jobs = { ...snap.jobs };
      if (rebuild) build();
      for (const r of snap.records) add(r);
      if (rebuild) { S.fresh = []; panel.reset(snap.models, running); }  // records already there are not replayed
      for (const m of snap.models) {
        const prev = S.pending[m];
        S.pending[m] = running(m) ? firstPending(m) : null;
        if (prev) paint(prev);
        if (S.pending[m]) paint(S.pending[m]);
      }
      status.textContent = snap.records.length ? "" : "No attempts recorded yet.";
      panel.live(S.fresh);
      drawBanners();
      if (o.onSnapshot) o.onSnapshot(snap);
    }

    // Poll every 1.5 s while a job of the experiment is alive; the poll that sees the last job end is the final one.
    // The snapshot is 404 until run's first branch commit: with any job running that reads as "starting".
    async function load() {
      if (!el.isConnected) { ctl.destroy(); return; }  // the page moved on
      if (S.dead || S.loading) return;
      S.loading = true;
      clearTimeout(S.timer); S.timer = null;
      let again = false;
      try {
        apply(await UI.api("/api/state/" + encodeURIComponent(id)));
        again = alive();
      } catch (e) {
        again = UI.jobs.some((j) => j.id === id && j.state === "running");
        status.textContent = again ? "Starting: waiting for the first results." : e.message;
      } finally { S.loading = false; }
      if (again && !S.dead) S.timer = setTimeout(load, POLL_MS);
    }

    const offJobs = UI.onJobs((jobs) => {  // a job that starts after a quiet period restarts the poll
      if (S.dead) return;
      const sig = jobs.filter((j) => j.id === id && j.state === "running").map((j) => j.job).join(",");
      if (sig !== S.runSig) { S.runSig = sig; if (sig && !S.timer) load(); }
    });
    const offLines = UI.onLines((ev) => {  // each stderr line redraws the banners
      if (S.dead || ev.stream !== "stderr" || ev.id !== id) return;
      S.lastErr[ev.id + "\u0000" + ev.job] = ev.text;
      drawBanners();
    });

    const ctl = {
      refresh: load, snapshot: () => S.snap,
      destroy() { S.dead = true; clearTimeout(S.timer); panel.destroy(); offJobs(); offLines(); if (current === ctl) current = null; },
    };
    current = ctl;
    load();
    return ctl;
  }

  window.Progress = { COLORS, OUTCOMES, mount };
})();
