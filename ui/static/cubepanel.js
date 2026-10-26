// Spec: docs/specs/ui.md (Cube panel)
// The Cube panel: plays one attempt on the 3D view and the net. The server sends every frame
// (GET /api/replay), so the page never holds the move group. Live mode follows the newest record of the
// chosen model. Reads the replay API and writes only its own DOM. progress.js drives it (see Progress).
(function () {
  const h = UI.el;
  const BASE_STEP_MS = 300;
  const REPLAY_GAP_MS = 600;  // pause between a finished replay and the queued one

  // host: {id, input(inputId), hasRecord(model, inputId, setup, attempt), pending(model) -> key | null}
  window.CubePanel = function (host) {
    const P = { live: true, model: "", data: null, input: null, frame: 0, playing: false, timer: null,
                speed: 1, seq: 0, shown: "", info: null, queue: null, gap: null, last: null };
    const COLORS = () => window.Progress.COLORS;
    const live = h("input", { type: "checkbox", checked: "" });
    const model = h("select", { "aria-label": "Model to follow", hidden: "" });
    const views = h("div", { class: "cube-views" });
    const moves = h("div", { class: "cube-moves" });
    const info = h("div", { class: "cube-info" });
    const back = h("button", { type: "button", class: "small", text: "Step back", disabled: "" });
    const play = h("button", { type: "button", class: "small", text: "Play", disabled: "" });
    const fwd = h("button", { type: "button", class: "small", text: "Step forward", disabled: "" });
    const speed = h("select", {}, ...["0.5", "1", "2", "4"].map((v) => h("option", { value: v, text: v + "x" })));
    speed.value = "1";
    const node = h("div", { class: "cube-panel" },
      h("div", { class: "cube-head" }, h("strong", { text: "Cube" }), h("label", {}, live, " Live"), model),
      views, moves, info,
      h("div", { class: "cube-ctl" }, back, play, fwd, h("label", {}, "Speed ", speed)));

    const can = (puzzle, state) => /^(\d+)x\1$/.test(puzzle) && cubeSize(state) > 0;
    const stop = () => { clearTimeout(P.timer); P.playing = false; };
    // Forget the queued record and any pending pause, and drop a load still in flight.
    const drop = () => { stop(); clearTimeout(P.gap); P.gap = null; P.queue = null; P.seq++; };

    function draw() {
      const state = P.data ? P.data.frames[P.frame] : P.input ? P.input.state : null;
      const puzzle = P.data ? P.data.puzzle : P.input ? P.input.puzzle : "";
      node.classList.toggle("waiting", !P.data && !!P.input);
      for (const b of [back, play, fwd]) b.disabled = !P.data;
      play.textContent = P.playing ? "Pause" : "Play";
      moves.replaceChildren();
      info.style.color = "";
      if (state === null) {
        views.replaceChildren(h("span", { class: "muted", text: "Run an experiment or click an arc to see its cube." }));
        info.textContent = "";
        return;
      }
      if (!can(puzzle, state)) {
        views.replaceChildren(h("span", { class: "muted", text: `no drawing for ${puzzle}` }));
        info.textContent = "";
        return;
      }
      const m = P.data && P.frame > 0 ? P.data.moves[P.frame - 1] : null;
      // The flash is CSS and stops under reduced motion; the thicker outline stays.
      views.replaceChildren(cubeIso(state, cubeSize(state), m ? m[0] : null, { height: 200 }), cubeNet(state, { width: 240 }));
      if (!P.data) { info.textContent = `waiting for ${P.model}`; return; }
      P.data.moves.forEach((mv, i) => {
        const bad = i === P.data.stopped_at;
        const chip = h("span", { class: "mv" + (i === P.frame - 1 ? " cur" : "") + (bad ? " bad" : ""), text: mv });
        if (bad) chip.style.color = COLORS().hallucination;
        moves.append(chip, " ");
      });
      if (!P.data.moves.length) moves.append(h("span", { class: "muted", text: "no moves" }));
      const i = P.info || {};
      const outcome = h("span", { class: "outcome", text: P.data.outcome.replace("_", " ") });
      outcome.style.color = COLORS()[P.data.outcome] || "inherit";
      info.replaceChildren(outcome, ` · ${i.input_id} · ${i.setup} · attempt ${i.attempt}`
        + (P.data.stopped_at !== null ? ` · stopped at impossible move ${P.data.moves[P.data.stopped_at]}` : ""));
    }

    // A replay error shows in the panel's own line.
    function fail(e) { stop(); draw(); info.textContent = e.message; info.style.color = COLORS().failure; }

    // Playback reached its last frame: pause, then start the queued record, if Live is on and one waits.
    function ended() {
      if (!P.live || !P.queue || P.gap) return;
      P.gap = setTimeout(() => {
        const r = P.queue;
        P.gap = null; P.queue = null;
        if (P.live && r) load(r.model, r.input_id, r.setup, r.attempt_number).catch(fail);
      }, REPLAY_GAP_MS);
    }

    function step(delta) {
      if (!P.data) return;
      P.frame = Math.max(0, Math.min(P.data.frames.length - 1, P.frame + delta));
      const last = P.frame === P.data.frames.length - 1;
      if (last) stop();
      draw();
      if (last) ended();
    }

    function startPlay() {
      stop();
      if (!P.data) return;
      if (P.frame >= P.data.frames.length - 1) P.frame = 0;
      P.playing = true;
      draw();
      const tick = () => {
        if (!P.playing) return;
        step(1);
        if (P.playing) P.timer = setTimeout(tick, BASE_STEP_MS / P.speed);
      };
      P.timer = setTimeout(tick, BASE_STEP_MS / P.speed);
    }

    async function load(m, inputId, setup, attempt) {
      const seq = ++P.seq;
      const q = new URLSearchParams({ model: m, input_id: inputId, setup, attempt });
      const data = await UI.api(`/api/replay/${encodeURIComponent(host.id)}?${q}`);
      if (seq !== P.seq) return;  // a newer request took over
      stop();
      Object.assign(P, { data, input: null, frame: 0, shown: "", info: { input_id: inputId, setup, attempt } });
      startPlay();
    }

    live.addEventListener("change", () => { P.live = live.checked; P.shown = ""; if (!P.live) drop(); api.live([]); });
    play.addEventListener("click", () => (P.playing ? (stop(), draw()) : startPlay()));
    back.addEventListener("click", () => { stop(); step(-1); });
    fwd.addEventListener("click", () => { stop(); step(1); });
    speed.addEventListener("change", () => { P.speed = Number(speed.value); if (P.playing) startPlay(); });
    model.addEventListener("change", () => {
      Object.assign(P, { model: model.value, data: null, input: null, shown: "", last: null });
      drop(); draw(); api.live([]);
    });

    const api = {
      node,
      // Back to empty for a (re)built progress tree: records already there are not replayed.
      reset(models, running) {
        drop();
        Object.assign(P, { data: null, input: null, frame: 0, playing: false, shown: "", info: null, last: null });
        if (!models.includes(P.model)) P.model = models.find((m) => running(m)) || models[0] || "";
        model.replaceChildren(...models.map((m) => h("option", { value: m, text: m })));
        model.value = P.model;
        model.hidden = models.length < 2;
        draw();
      },
      // A click on an arc with a record replays it and turns Live off.
      open(m, inputId, setup, attempt) {
        if (!host.hasRecord(m, inputId, setup, attempt)) return;
        P.live = false; live.checked = false;
        drop();
        P.model = m; model.value = m;
        load(m, inputId, setup, attempt).catch(fail);
      },
      // Called after every snapshot with the records new in it: play the newest of the followed model,
      // or show the attempt in flight.
      live(fresh) {
        if (!P.live) return;
        const rec = fresh.filter((r) => r.model === P.model).pop();
        if (rec) {
          if (P.playing || P.gap) P.queue = rec;  // a queue of one: only the newest unplayed record waits
          else load(rec.model, rec.input_id, rec.setup, rec.attempt_number).catch(fail);
          return;
        }
        const key = host.pending(P.model);
        if (!key && P.input) {  // the run ended with no final record: drop the waiting state
          P.input = null; P.shown = "";
          P.data = P.last ? P.last.data : null; P.info = P.last ? P.last.info : null;
          P.frame = P.data ? P.data.frames.length - 1 : 0;
          draw();
        }
        if (!key || P.playing || P.gap || P.queue || P.shown === key) return;
        P.shown = key; P.seq++;
        if (P.data) P.last = { data: P.data, info: P.info };
        P.data = null; P.info = null;
        P.input = host.input(key.split("|")[1]);
        draw();
      },
      destroy() { drop(); },
    };
    draw();
    return api;
  };
})();
