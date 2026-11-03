// Spec: docs/specs/ui.md (Terminal)
// The Experiment page's terminal: the job log of one experiment, and one block per attempt with its input
// (the prompt) and its output (the raw response), loaded from GET /api/attempt on first unfold.
// Interface: Terminal.mount(el, experimentId, host) -> {sync(), focus(step), destroy()}, where
// host = {records(): Map, pending(): {model: [key]}, inputs(): Map}. Keys are model|input|setup|attempt.
// Reads UI.lines and UI.onLines; writes only its DOM. Raw text is set with textContent, never as markup.
(function () {
  const h = UI.el;
  // run's plain progress line: [k/N] <model> <puzzle> <input id> <setup> #<attempt> <outcome> | ...
  const RUN_LINE = /^\[\d+\/\d+\] (\S+) (\S+) (\S+) (\S+) #(\d+) (\S+) \|/;
  const MAX_CHILDREN = 3000;
  const key = (model, input, setup, attempt) => `${model}|${input}|${setup}|${attempt}`;
  const reduced = () => !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  function mount(el, id, host) {
    const T = { blocks: new Map(), seen: new Set(), synced: false, dead: false };
    const clear = h("button", { type: "button", class: "small", text: "Clear" });
    const note = h("span", { class: "wterm-note", role: "status" });
    const body = h("div", { class: "wterm-body", tabindex: "0" });
    const node = h("div", { class: "wterm" }, h("div", { class: "term-bar" }, h("strong", { text: "Terminal" }), note, clear), body);
    el.replaceChildren(node);

    // Runs fn, then follows the bottom when the view was at the bottom before.
    function stick(fn) {
      const at = body.scrollHeight - body.scrollTop - body.clientHeight < 24;
      fn();
      while (body.childElementCount > MAX_CHILDREN) {
        const first = body.firstElementChild;
        if (first._block) T.blocks.delete(first._block.key);
        first.remove();
      }
      if (at) body.scrollTop = body.scrollHeight;
    }

    function setHead(b, text, state) {
      const sw = h("i");
      sw.style.background = Progress.COLORS[state] || Progress.COLORS.pending;
      b.head.replaceChildren(sw, h("span", { class: "tl", text }), ...(b.sending ? [h("span", { class: "sending", text: "sending…" })] : []));
      b.el.dataset.state = state;
    }

    // One attempt's block. Created once per key, whichever of a log line, a record, or the in-flight inference comes first.
    function block(model, input, setup, attempt, puzzle) {
      const k = key(model, input, setup, attempt);
      if (T.blocks.has(k)) return T.blocks.get(k);
      const head = h("summary", {});
      const mk = (name) => {
        const pre = h("pre", { class: "io", text: "" });
        return { pre, det: h("details", { class: "io-det", "data-io": name }, h("summary", { text: name }), pre) };
      };
      const inp = mk("input"), out = mk("output");
      const el = h("details", { class: "att" }, head, inp.det, out.det);
      const b = { key: k, model, input, setup, attempt: Number(attempt), puzzle: puzzle || "", el, head, inp, out, sending: false, tries: 0, text: "", state: "pending", loaded: null };
      el._block = b;
      for (const part of [inp, out]) part.det.addEventListener("toggle", () => { if (part.det.open) ensure(b); });
      T.blocks.set(k, b);
      T.seen.add(k);
      return b;
    }

    // The puzzle of a block: from its run line, else looked up when asked, because the host may not know the inputs yet.
    const puzzleOf = (b) => b.puzzle || (b.puzzle = (host.inputs().get(b.input) || {}).puzzle || "");

    // Fetches the attempt once, and again after its record lands if the output was not there yet.
    async function ensure(b) {
      const have = host.records().has(b.key);
      if (b.loaded && (b.loaded.record || !have)) return;
      if (b.loaded && ++b.tries > 3) return;  // the snapshot has the record but the API does not: stop asking
      b.inp.pre.textContent = b.inp.pre.textContent || "Loading…";
      const q = new URLSearchParams({ model: b.model, input: b.input, setup: b.setup, attempt: String(b.attempt) });
      const ask = b.loading = UI.api(`/api/attempt/${encodeURIComponent(id)}?${q}`);
      try {
        const d = await ask;
        if (b.loading !== ask) return;
        b.loaded = d;
        b.inp.pre.textContent = d.prompt;
        b.out.pre.textContent = d.record
          ? (d.raw_response === null || d.raw_response === "" ? "(empty response)" : d.raw_response)
          : "No output yet. The request is still in flight.";
      } catch (e) {
        if (b.loading !== ask) return;
        b.inp.pre.textContent = b.out.pre.textContent = e.message;
      }
    }

    function describe(rec) {
      const input = host.inputs().get(rec.input_id);
      return `${rec.model} ${input ? input.puzzle : ""} ${rec.input_id} ${rec.setup} #${rec.attempt_number} ${rec.outcome}`;
    }

    // A record landed (or was already there): fill the header unless a log line already did, and refresh a loaded output.
    function applyRecord(b, rec) {
      b.sending = false;
      if (!b.fromLine) { b.text = describe(rec); }
      b.state = rec.outcome;
      setHead(b, b.text, b.state);
      if (b.out.det.open || b.inp.det.open) ensure(b);
    }

    function addLine(ev) {
      const m = ev.stream === "stdout" && ev.job.startsWith("run:") ? RUN_LINE.exec(ev.text) : null;
      if (m) {
        const [, model, puzzle, input, setup, attempt, outcome] = m;
        const fresh = !T.blocks.has(key(model, input, setup, attempt));
        const b = block(model, input, setup, attempt, puzzle);
        b.puzzle = puzzle;
        b.fromLine = true; b.sending = false; b.text = ev.text; b.state = outcome;
        setHead(b, b.text, b.state);
        if (fresh) body.append(b.el);
        if (b.out.det.open || b.inp.det.open) ensure(b);
        return;
      }
      const cls = ev.stream === "cmd" ? "cmd" : ev.stream === "stderr" ? "err" : "";
      body.append(h("div", { class: "tline " + cls }, h("span", { class: "tag", text: `[${ev.job}] ` }),
        (ev.stream === "cmd" ? "$ " : "") + ev.text));
    }

    // Applies the host's records and in-flight attempts. The first call places the attempts the log never showed
    // (a server restart, a pushed experiment) before the live lines, oldest first; later ones follow arrival order.
    function sync() {
      if (T.dead) return;
      stick(() => {
        const records = [...host.records().values()];
        const unseen = records.filter((r) => !T.seen.has(key(r.model, r.input_id, r.setup, r.attempt_number)));
        if (!T.synced) unseen.sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || "")));
        const early = [];
        for (const rec of unseen) {
          const b = block(rec.model, rec.input_id, rec.setup, rec.attempt_number);
          applyRecord(b, rec);
          if (T.synced) body.append(b.el); else early.push(b.el);
        }
        if (early.length) body.prepend(...early);
        for (const rec of records) {
          const b = T.blocks.get(key(rec.model, rec.input_id, rec.setup, rec.attempt_number));
          if (b && (b.sending || b.state !== rec.outcome || (b.loaded && !b.loaded.record))) applyRecord(b, rec);
        }
        const pending = new Set(Object.values(host.pending()).flat());
        for (const b of [...T.blocks.values()]) {
          if (b.sending && !pending.has(b.key)) { b.el.remove(); T.blocks.delete(b.key); T.seen.delete(b.key); }
        }
        for (const k of pending) {
          if (T.seen.has(k)) continue;
          const [model, input, setup, attempt] = k.split("|");
          const b = block(model, input, setup, attempt);
          b.sending = true; b.text = `${model} ${puzzleOf(b)} ${input} ${setup} #${attempt}`; b.state = "in_progress";
          setHead(b, b.text, b.state);
          body.append(b.el);
        }
        T.synced = true;
      });
    }

    const match = (b, step) => (!step.puzzle || puzzleOf(b) === step.puzzle) && ["model", "input", "setup"].every((f) => !step[f] || b[f] === step[f])
      && (!step.attempt || b.attempt === step.attempt);
    function flash(b) {
      b.el.classList.remove("hl");
      void b.el.offsetWidth;  // restart the animation
      b.el.classList.add("hl");
      setTimeout(() => b.el.classList.remove("hl"), 1600);
    }

    // A plan step was clicked: show the first attempt block under it, and for a whole attempt unfold input and output.
    function focus(step) {
      const leaf = step.setup && step.attempt;
      const k = leaf ? key(step.model, step.input, step.setup, step.attempt) : "";
      let b = leaf ? T.blocks.get(k) : [...body.querySelectorAll("details.att")].map((n) => n._block).find((x) => match(x, step));
      note.textContent = "";
      if (!b && leaf) {  // a leaf with no block (after Clear, or not reached): show it as it stands
        stick(() => {
          b = block(step.model, step.input, step.setup, step.attempt, step.puzzle);
          const rec = host.records().get(k);
          if (rec) applyRecord(b, rec);
          else if (Object.values(host.pending()).flat().includes(k)) {
            b.sending = true; b.text = `${step.model} ${puzzleOf(b)} ${step.input} ${step.setup} #${step.attempt}`;
            setHead(b, b.text, "in_progress");
          } else {
            b.text = `${step.model} ${puzzleOf(b)} ${step.input} ${step.setup} #${step.attempt} not started`;
            setHead(b, b.text, "pending");
          }
          body.append(b.el);
        });
      }
      if (!b) { note.textContent = "no output for this step yet"; return; }
      if (leaf) for (const d of [b.el, b.inp.det, b.out.det]) d.open = true;
      const behavior = reduced() ? "auto" : "smooth";
      node.scrollIntoView({ block: "nearest", behavior });
      body.scrollTo({ top: Math.max(0, b.el.offsetTop - 8), behavior });
      flash(b);
    }

    clear.addEventListener("click", () => {
      body.replaceChildren(); T.blocks.clear(); note.textContent = "";
      // Only attempts with a record stay seen: one still sending gets its block back when its record lands.
      for (const k of [...T.seen]) if (!host.records().has(k)) T.seen.delete(k);
    });
    const off = UI.onLines((ev) => { if (!T.dead && ev.id === id) stick(() => addLine(ev)); });
    stick(() => { for (const ev of UI.lines) if (ev.id === id) addLine(ev); });
    return { node, sync, focus, destroy() { T.dead = true; off(); } };
  }

  window.Terminal = { mount };
})();
