// Spec: docs/specs/ui.md (Progress, Arc colours, Polling)
// The Plan of the Experiment page: a legend and a tree of foldable nodes (puzzle, AI model, input with its ring, attempt),
// the job banners, and the data the Cube panel and the terminal read. Reads GET /api/state/<id>; writes only its DOM.
// Interface: Progress.mount(el, experimentId, opts) -> {refresh(), destroy(), snapshot(), panelNode, records(), pending() ->
// {model: [key]}, inputs(), totals()} and Progress.COLORS, Progress.OUTCOMES. opts: onSnapshot(snap) after every applied snapshot,
// onStep(step) on a click of a node, arc, or leaf, bannerEl for the banners. Mounting again replaces the previous mount.
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
                inputCounts: new Map(), arcs: new Map(), leaves: new Map(), nodes: new Map(), userSet: new Map(),
                autoOpened: new Set(), pending: {}, fresh: [], lastErr: {}, puzzles: [], timer: null, dead: false,
                loading: false, runSig: "" };
    const running = (m) => S.jobs["run:" + m] === "running";
    const panel = CubePanel({
      id, input: (i) => S.inputs.get(i), pending: (m) => (S.pending[m] || [])[0] || null,
      hasRecord: (m, i, s, a) => S.records.has(key(m, i, s, a)),
    });
    const status = h("p", { class: "muted small", text: "Loading progress." });
    const banners = h("div");
    const tree = h("div", { class: "plan-tree" });
    el.replaceChildren(ProgressView.legend(COLORS, OUTCOMES), status, tree);
    if (o.bannerEl) o.bannerEl.replaceChildren(banners); else el.prepend(banners);

    const alive = () => Object.values(S.jobs).includes("running");
    const countFor = (m, p) => {
      if (!S.counts.has(m + "|" + p)) S.counts.set(m + "|" + p, { done: 0, out: {} });
      return S.counts.get(m + "|" + p);
    };
    const inputCount = (m, i) => {
      if (!S.inputCounts.has(m + "|" + i)) S.inputCounts.set(m + "|" + i, { done: 0, out: {} });
      return S.inputCounts.get(m + "|" + i);
    };
    const perInput = () => S.snap.setups.length * S.snap.attempts;
    const inputsOf = (p) => S.snap.inputs.filter((i) => i.puzzle === p);

    function fill(box, done, all, out) {
      box.replaceChildren(h("span", { text: `${done}/${all}` }));
      for (const k of OUTCOMES) if (out[k]) box.append(ProgressView.chip(COLORS, k, out[k]));
    }

    // Plan nodes: id -> {det, mark, counts, kind, puzzle, model, input}. Ids are p:<puzzle>, m:<puzzle>|<model>,
    // and i:<puzzle>|<model>|<input>. `userSet` remembers a fold or unfold by hand, which auto-opening respects.
    const nodeId = (kind, ...parts) => `${kind}:${parts.join("|")}`;
    const nodeNumbers = (n) => {
      if (n.kind === "i") return [inputCount(n.model, n.input.input_id), perInput()];
      const per = inputsOf(n.puzzle).length * perInput();
      if (n.kind === "m") return [countFor(n.model, n.puzzle), per];
      const sum = { done: 0, out: {} };
      for (const m of S.snap.models) {
        const c = countFor(m, n.puzzle);
        sum.done += c.done;
        for (const [k, v] of Object.entries(c.out)) sum.out[k] = (sum.out[k] || 0) + v;
      }
      return [sum, per * S.snap.models.length];
    };
    const holdsPending = (n) => Object.entries(S.pending).some(([m, keys]) => keys.some((k) => {
      const input = S.inputs.get(k.split("|")[1]);
      if (input.puzzle !== n.puzzle) return false;
      if (n.kind === "p") return true;
      if (m !== n.model) return false;
      return n.kind === "m" || input.input_id === n.input.input_id;
    }));
    const MARKS = { done: "✓", run: "●", todo: "○" };

    function refreshNode(n) {
      const [c, all] = nodeNumbers(n);
      const status = holdsPending(n) ? "run" : c.done >= all && all > 0 ? "done" : "todo";
      n.det.dataset.status = status;
      n.mark.textContent = MARKS[status];
      n.badge.hidden = status !== "run";
      fill(n.counts, c.done, all, c.out);
    }
    const refreshNodes = () => S.nodes.forEach(refreshNode);

    function setOpen(det, v) {
      if (det.open === v) return;
      det._prog = v;
      det.open = v;
    }

    // One foldable node. `drawBody(body)` runs once, when the node first opens.
    function node(kind, parts, label, drawBody, extra) {
      const id = nodeId(kind, ...parts);
      const mark = h("span", { class: "mark" }), badge = h("span", { class: "run-badge", text: "in progress", hidden: "" });
      const counts = h("span", { class: "counts" });
      const body = h("div", { class: "body" });
      const det = h("details", { class: "pn pn-" + kind }, h("summary", {}, mark, label, badge, counts), body);
      const n = Object.assign({ id, kind, det, mark, badge, counts, body, drawn: false }, extra);
      n.draw = () => { if (!n.drawn) { n.drawn = true; drawBody(body); } };
      det.addEventListener("toggle", () => {
        if (det._prog === det.open) det._prog = undefined;
        else S.userSet.set(id, det.open);
        if (det.open) n.draw();
      });
      det.firstChild.addEventListener("click", () => o.onStep && o.onStep(stepOf(n)));
      S.nodes.set(id, n);
      refreshNode(n);
      return n;
    }
    const stepOf = (n) => ({ puzzle: n.puzzle, model: n.model, input: n.input && n.input.input_id });

    function arcState(k, model) {
      const rec = S.records.get(k);
      return rec ? rec.outcome : (S.pending[model] || []).includes(k) ? "in_progress" : "pending";
    }

    function paint(k) {
      const path = S.arcs.get(k), leaf = S.leaves.get(k);
      if (!path && !leaf) return;
      const [model, inputId, setup, attempt] = k.split("|");
      const state = arcState(k, model), rec = S.records.get(k);
      const colour = COLORS[state] || COLORS.pending;
      if (path) {
        path.setAttribute("fill", colour);
        path.classList.toggle("pulse", state === "in_progress");
        path.classList.toggle("done", !!rec);
        let t = `${setup}, attempt ${attempt}: ${state.replace("_", " ")}`;
        if (rec && S.inputs.get(inputId).validity !== "valid") t += `, mismatch: ${rec.mismatch ? "yes" : "no"}`;
        path.firstChild.textContent = t;
      }
      if (leaf) {
        leaf.sw.style.background = colour;
        leaf.text.textContent = state.replace("_", " ");
        leaf.leaf.dataset.state = state;
      }
    }

    function ring(model, input) {
      const n = perInput();
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
          path.addEventListener("click", (ev) => {
            ev.stopPropagation(); ev.preventDefault();  // the ring sits in a summary: no fold
            panel.open(model, input.input_id, setup, a);
            if (o.onStep) o.onStep({ puzzle: input.puzzle, model, input: input.input_id, setup, attempt: a });
          });
          root.append(path);
          paint(k);
        }
      }
      root.append(cubeNet(input.state, { x: 20, y: 29, width: 60, height: 45 }));
      return root;
    }

    function leaves(body, model, input) {
      for (const setup of S.snap.setups) {
        for (let a = 1; a <= S.snap.attempts; a++) {
          const k = key(model, input.input_id, setup, a);
          const sw = h("i"), text = h("span", { class: "lt" });
          const leaf = h("div", { class: "leaf", tabindex: "0", role: "button" }, sw, h("span", { text: `${setup} #${a}` }), text);
          const go = () => o.onStep && o.onStep({ puzzle: input.puzzle, model, input: input.input_id, setup, attempt: a });
          leaf.addEventListener("click", go);
          leaf.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); go(); } });
          S.leaves.set(k, { leaf, sw, text });
          body.append(leaf);
          paint(k);
        }
      }
    }

    function inputNode(puzzle, model, input) {
      const label = h("span", { class: "irow" }, ring(model, input), h("span", { class: "meta" },
        h("span", { class: "id", text: input.input_id }), h("span", { text: `depth ${input.scramble_depth}, ${input.validity}` })));
      return node("i", [puzzle, model, input.input_id], label, (body) => leaves(body, model, input), { puzzle, model, input });
    }

    function modelNode(puzzle, model) {
      return node("m", [puzzle, model], h("strong", { text: model }), (body) => {
        for (const input of inputsOf(puzzle)) body.append(inputNode(puzzle, model, input).det);
      }, { puzzle, model });
    }

    function build() {
      tree.replaceChildren();
      S.nodes = new Map(); S.leaves = new Map();
      for (const puzzle of S.puzzles) {
        const p = node("p", [puzzle], h("strong", { text: puzzle }), (body) => {
          for (const model of S.snap.models) body.append(modelNode(puzzle, model).det);
        }, { puzzle });
        tree.append(p.det);
      }
    }

    // Opens the nodes down to an input, drawing the lazy bodies on the way, unless the user folded one by hand.
    function reveal(puzzle, model, inputId, auto) {
      const path = [nodeId("p", puzzle), nodeId("m", puzzle, model), nodeId("i", puzzle, model, inputId)];
      for (const id of path) {
        const n = S.nodes.get(id);
        if (!n) return null;
        if (S.userSet.get(id) === false && auto) return null;
        if (!n.det.open) { setOpen(n.det, true); if (auto) S.autoOpened.add(id); }
        n.draw();
      }
      return S.nodes.get(path[2]);
    }

    function add(rec) {
      const input = S.inputs.get(rec.input_id);
      if (!input) return;
      const k = key(rec.model, rec.input_id, rec.setup, rec.attempt_number);
      const cs = [countFor(rec.model, input.puzzle), inputCount(rec.model, rec.input_id)], old = S.records.get(k);
      if (old && old.outcome === rec.outcome) return;
      if (old) for (const c of cs) { c.done--; c.out[old.outcome]--; }
      else S.fresh.push(rec);
      S.records.set(k, rec);
      for (const c of cs) { c.done++; c.out[rec.outcome] = (c.out[rec.outcome] || 0) + 1; }
      paint(k);
    }

    const inFlight = (model) => Progress.inFlight(S.snap, model, (S.snap.parallel || {})[model] || 1, (k) => S.records.has(k));

    const drawBanners = () => banners.replaceChildren(...ProgressView.banners(S.jobs,
      Object.fromEntries(Object.keys(S.jobs).map((j) => [j, S.lastErr[id + "\u0000" + j]]))));

    // The node holding each in-flight attempt opens itself unless the user folded it by hand. An input node that
    // opened itself and no longer holds the in-flight attempt folds again, unless the user touched it.
    function followPending() {
      for (const [m, keys] of Object.entries(S.pending)) {
        for (const k of keys) {
          const input = S.inputs.get(k.split("|")[1]);
          reveal(input.puzzle, m, input.input_id, true);
        }
      }
      for (const id of [...S.autoOpened]) {
        const n = S.nodes.get(id);
        if (!n || n.kind !== "i" || S.userSet.has(id)) continue;
        if (!holdsPending(n)) { setOpen(n.det, false); S.autoOpened.delete(id); }
      }
    }

    // A later snapshot only adds records, so open nodes stay open; a new shape rebuilds the tree.
    function apply(snap) {
      const shape = JSON.stringify([id, snap.release, snap.models, snap.attempts, snap.inputs.map((i) => i.input_id)]);
      const rebuild = shape !== S.shape;
      S.fresh = [];
      if (rebuild) {
        Object.assign(S, { shape, records: new Map(), counts: new Map(), inputCounts: new Map(), arcs: new Map(),
          leaves: new Map(), nodes: new Map(), userSet: new Map(), autoOpened: new Set(), pending: {}, inputs: new Map() });
        S.puzzles = [...new Set(snap.inputs.map((i) => i.puzzle))];
        for (const i of snap.inputs) S.inputs.set(i.input_id, i);
      }
      S.snap = snap; S.jobs = { ...snap.jobs };
      if (rebuild) build();
      for (const r of snap.records) add(r);
      if (rebuild) { S.fresh = []; panel.reset(snap.models, running); }  // records already there are not replayed
      for (const m of snap.models) {
        const prev = S.pending[m] || [];
        S.pending[m] = running(m) ? inFlight(m) : [];
        for (const k of prev) paint(k);
        for (const k of S.pending[m]) paint(k);
      }
      followPending();
      refreshNodes();
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
      refresh: load, snapshot: () => S.snap, panelNode: panel.node,
      records: () => S.records, pending: () => S.pending, inputs: () => S.inputs,
      // Done and planned attempts over all models, with the count per outcome.
      totals() {
        const out = {}; let done = 0;
        for (const r of S.records.values()) { done++; out[r.outcome] = (out[r.outcome] || 0) + 1; }
        const planned = S.snap ? S.snap.inputs.length * S.snap.models.length * perInput() : 0;
        return { done, planned, out };
      },
      destroy() { S.dead = true; clearTimeout(S.timer); panel.destroy(); offJobs(); offLines(); if (current === ctl) current = null; },
    };
    current = ctl;
    load();
    return ctl;
  }

  // The attempts a running model has in flight: the first `parallel` attempts without a record, in run's loop order
  // (input in release order, then setup, then attempt number). An inference, as `run` doesn't report them.
  function inFlight(snap, model, parallel, hasRecord) {
    const out = [];
    for (const input of snap.inputs) for (const setup of snap.setups) {
      for (let a = 1; a <= snap.attempts; a++) {
        const k = key(model, input.input_id, setup, a);
        if (hasRecord(k)) continue;
        out.push(k);
        if (out.length >= parallel) return out;
      }
    }
    return out;
  }

  window.Progress = { COLORS, OUTCOMES, mount, inFlight };
})();
