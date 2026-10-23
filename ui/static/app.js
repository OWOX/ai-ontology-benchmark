"use strict";

// ---- Constants: every colour lives here ----------------------------------
const COLORS = {
  pending: "#d0d4da",
  in_progress: "#f2b705",
  success: "#2e9e5b",
  failure: "#d64545",
  hallucination: "#8e44ad",
  malformed_output: "#1a9bb0",
  infrastructure_failure: "#5d6d7e",
};
const OUTCOMES = ["success", "failure", "hallucination", "malformed_output", "infrastructure_failure"];
const STICKERS = { U: "#ffffff", R: "#d62d20", F: "#1f9d55", D: "#f5d90a", L: "#f08a1c", B: "#2155c4" };
const FACE_ORDER = "URFDLB";
const NET_POS = { U: [1, 0], L: [0, 1], F: [1, 1], R: [2, 1], B: [3, 1], D: [1, 2] };
const PROVIDER_ORDER = ["anthropic", "openai", "google", "fake"];
const PROVIDER_COLORS = { anthropic: "#c96442", openai: "#0f8f6f", google: "#3b78e7", fake: "#7f8c8d" };
const UNKNOWN_PROVIDER_COLOR = "#9aa0a6";
const SVGNS = "http://www.w3.org/2000/svg";

// ---- Application state -----------------------------------------------------
const S = {
  token: "",
  cat: null,
  puzzles: new Set(),      // selected puzzle names
  models: new Set(),       // selected model names
  id: null,                // experiment id shown in progress
  snap: null,              // last /api/state snapshot
  inputs: new Map(),       // input_id -> input
  records: new Map(),      // key -> record
  counts: new Map(),       // "model|puzzle" -> {done, total, out: {}}
  shape: "",               // identity of the rendered progress tree
  puzzleList: [],          // puzzles of the loaded experiment, in release order
  jobs: {},                // job -> state, for the loaded experiment
  anyAlive: false,         // any job of any experiment is running
  logAfter: 0,             // highest terminal line seq seen
  statePoll: null,         // timer of the snapshot poll
  lastErr: {},             // job -> last stderr line
  arcs: new Map(),         // key -> path element
  lastArc: {},             // model -> key painted as in progress
  project: null,           // last /api/project
  logTimer: null,          // timer of the log poll
  projRunning: new Set(),  // job names running at the last log poll
};
const STATE_POLL_MS = 1500;
const LOG_POLL_MS = { busy: 1000, idle: 5000 };

// ---- Small DOM helpers -----------------------------------------------------
const $ = (id) => document.getElementById(id);

function el(tag, props, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const kid of kids) if (kid != null) node.append(kid);
  return node;
}

function svg(tag, attrs) {
  const node = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
  return node;
}

function say(id, text, kind) {
  const node = $(id);
  node.textContent = text || "";
  node.className = "msg" + (kind ? " " + kind : "");
}

// ---- HTTP ------------------------------------------------------------------
async function api(method, path, body) {
  const headers = {};
  const opts = { method, headers };
  if (method === "POST" || path.startsWith("/api/commit/") || path === "/api/secrets") headers["X-Token"] = S.token;
  if (method === "POST") {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body || {});
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { /* non-JSON body */ }
  if (!res.ok) throw new Error((data && data.error) || `${method} ${path} failed (${res.status})`);
  return data;
}

// ---- Cube net --------------------------------------------------------------
function solvedState(n) {
  return [...FACE_ORDER].map((f) => f.repeat(n * n)).join("");
}

// Returns an <svg> of a cube net for a 6*n*n state; sized by viewBox, 4x3 faces.
function cubeNet(state, attrs) {
  const n = Math.round(Math.sqrt(state.length / 6));
  const root = svg("svg", { viewBox: "0 0 4 3", ...attrs });
  if (n < 1 || 6 * n * n !== state.length) return root;
  const cell = 1 / n;
  const pad = 0.012;
  [...FACE_ORDER].forEach((face, fi) => {
    const [fx, fy] = NET_POS[face];
    for (let i = 0; i < n * n; i++) {
      const ch = state[fi * n * n + i];
      root.append(svg("rect", {
        x: fx + (i % n) * cell + pad, y: fy + Math.floor(i / n) * cell + pad,
        width: cell - 2 * pad, height: cell - 2 * pad,
        fill: STICKERS[ch] || "#999", stroke: "#2a2f38", "stroke-width": 0.02,
      }));
    }
  });
  return root;
}

// ---- Ring of arcs ----------------------------------------------------------
function arcPath(cx, cy, r0, r1, a0, a1) {
  const pt = (r, a) => `${(cx + r * Math.cos(a)).toFixed(2)} ${(cy + r * Math.sin(a)).toFixed(2)}`;
  const large = a1 - a0 > Math.PI ? 1 : 0;
  return `M ${pt(r1, a0)} A ${r1} ${r1} 0 ${large} 1 ${pt(r1, a1)} L ${pt(r0, a1)} A ${r0} ${r0} 0 ${large} 0 ${pt(r0, a0)} Z`;
}

function recKey(model, inputId, setup, attempt) {
  return `${model}|${inputId}|${setup}|${attempt}`;
}

function arcState(key, model) {
  const rec = S.records.get(key);
  if (rec) return rec.outcome;
  return S.lastArc[model] === key ? "in_progress" : "pending";
}

function arcTitle(key, model, setup, attempt, input) {
  const rec = S.records.get(key);
  const state = arcState(key, model);
  let t = `${setup}, attempt ${attempt}: ${state.replace("_", " ")}`;
  if (rec && input.validity !== "valid") t += `, mismatch: ${rec.mismatch ? "yes" : "no"}`;
  return t;
}

function paintArc(key) {
  const path = S.arcs.get(key);
  if (!path) return;
  const [model, inputId, setup, attempt] = key.split("|");
  const input = S.inputs.get(inputId);
  const state = arcState(key, model);
  path.setAttribute("fill", COLORS[state] || COLORS.pending);
  path.classList.toggle("pulse", state === "in_progress");
  path.firstChild.textContent = arcTitle(key, model, setup, Number(attempt), input);
}

function buildRing(model, input) {
  const setups = S.snap.setups;
  const total = setups.length * S.snap.attempts;
  const root = svg("svg", { viewBox: "0 0 100 100", width: 84, height: 84 });
  const gap = total > 1 ? Math.min(0.06, 0.3 * 2 * Math.PI / total) : 0;
  let idx = 0;
  for (const setup of setups) {
    for (let a = 1; a <= S.snap.attempts; a++, idx++) {
      const a0 = -Math.PI / 2 + (idx / total) * 2 * Math.PI + gap / 2;
      const a1 = -Math.PI / 2 + ((idx + 1) / total) * 2 * Math.PI - gap / 2;
      const path = svg("path", { d: arcPath(50, 50, 38, 48, a0, a1), class: "arc" });
      path.append(svg("title"));
      const key = recKey(model, input.input_id, setup, a);
      S.arcs.set(key, path);
      root.append(path);
      paintArc(key);
    }
  }
  root.append(cubeNet(input.state, { x: 20, y: 29, width: 60, height: 45 }));
  return root;
}

// ---- Catalogue and form ----------------------------------------------------
function nowId() {
  const d = new Date();
  const p = (v, w = 2) => String(v).padStart(w, "0");
  return `ui-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

function currentRelease() {
  return S.cat.releases.find((r) => r.version === $("release").value);
}

function fillDefaults() {
  const d = S.cat.defaults;
  $("attempts").value = d.attempts;
  $("retry-cap").value = d.retry_cap;
  $("max-tokens").value = d.max_output_tokens;
  $("b-request").value = d.budget.per_request_usd;
  $("b-model").value = d.budget.per_model_usd;
  $("b-experiment").value = d.budget.per_experiment_usd;
  $("exp-id").value = nowId();
}

function renderReleases() {
  const sel = $("release");
  sel.replaceChildren(...S.cat.releases.map((r) => el("option", { value: r.version, text: r.version })));
  sel.value = S.cat.latest;
  const ev = $("eval-release");
  ev.replaceChildren(el("option", { value: "", text: "experiment's release" }),
    ...S.cat.releases.map((r) => el("option", { value: r.version, text: r.version })));
  renderPuzzles();
}

function renderPuzzles() {
  const rel = currentRelease();
  const box = $("puzzles");
  box.replaceChildren();
  S.puzzles = new Set([...S.puzzles].filter((p) => rel && rel.puzzles.includes(p)));
  if (!rel) return;
  $("release-info").textContent = `${rel.input_count} inputs in this release`;
  for (const name of rel.puzzles) {
    const cube = /^(\d+)x(\d+)$/.exec(name);
    const n = cube && cube[1] === cube[2] ? Number(cube[1]) : 0;  // a net only for NxN cubes
    const card = el("button", { type: "button", class: "card", "aria-pressed": "false" },
      n ? cubeNet(solvedState(n), { width: 96, height: 72 }) : null,
      el("div", { class: "name", text: name }),
      el("div", { class: "muted small", text: `${rel.input_counts[name]} inputs` }));
    const toggle = () => {
      if (S.puzzles.has(name)) S.puzzles.delete(name); else S.puzzles.add(name);
      card.classList.toggle("sel", S.puzzles.has(name));
      card.setAttribute("aria-pressed", String(S.puzzles.has(name)));
    };
    card.addEventListener("click", toggle);
    card.classList.toggle("sel", S.puzzles.has(name));
    card.setAttribute("aria-pressed", String(S.puzzles.has(name)));
    box.append(card);
  }
}

function setPuzzles(list) {
  S.puzzles = new Set(list);
  renderPuzzles();
}

function renderModels() {
  const box = $("models");
  box.replaceChildren();
  const groups = new Map();
  for (const m of S.cat.models) {
    if (!groups.has(m.provider)) groups.set(m.provider, []);
    groups.get(m.provider).push(m);
  }
  const rank = (p) => (PROVIDER_ORDER.includes(p) ? PROVIDER_ORDER.indexOf(p) : PROVIDER_ORDER.length);
  const providers = [...groups.keys()].sort((a, b) => rank(a) - rank(b));
  for (const p of providers) {
    const badge = el("span", { class: "badge", text: (p[0] || "?"), "aria-hidden": "true" });
    badge.style.background = PROVIDER_COLORS[p] || UNKNOWN_PROVIDER_COLOR;
    const group = el("div", { class: "provider" }, el("div", { class: "provider-head" }, badge, el("span", { text: p })));
    for (const m of groups.get(p)) {
      const off = !!m.disabled_reason;
      const box_ = el("input", { type: "checkbox", "data-model": m.name });
      box_.disabled = off;
      box_.checked = S.models.has(m.name) && !off;
      box_.addEventListener("change", () => {
        if (box_.checked) S.models.add(m.name); else S.models.delete(m.name);
      });
      const label = el("label", { class: "model" + (off ? " off" : "") }, box_, el("span", { text: m.name }));
      if (off) label.append(el("span", { class: "reason", text: m.disabled_reason }));
      group.append(label);
    }
    box.append(group);
  }
}

function setModels(names) {
  const known = new Set(S.cat.models.filter((m) => !m.disabled_reason).map((m) => m.name));
  S.models = new Set(names.filter((n) => known.has(n)));
  renderModels();
}

function numVal(id, name, whole) {
  const raw = $(id).value.trim();
  const v = Number(raw);
  if (raw === "" || !Number.isFinite(v) || (whole && !Number.isInteger(v))) throw new Error(`${name} must be ${whole ? "a whole" : "a"} number`);
  return v;
}

function readForm() {
  const id = $("exp-id").value.trim();
  if (!id) throw new Error("id: enter an experiment id");
  if (!S.puzzles.size) throw new Error("puzzles: select at least one shape");
  if (!S.models.size) throw new Error("models: select at least one model");
  const rel = currentRelease();
  return {
    id, release: $("release").value,
    puzzles: rel.puzzles.filter((p) => S.puzzles.has(p)),
    models: S.cat.models.filter((m) => S.models.has(m.name)).map((m) => m.name),
    attempts: numVal("attempts", "attempts", true),
    retry_cap: numVal("retry-cap", "retry_cap", true),
    max_output_tokens: numVal("max-tokens", "max_output_tokens", true),
    budget: {
      per_request_usd: numVal("b-request", "per_request_usd"),
      per_model_usd: numVal("b-model", "per_model_usd"),
      per_experiment_usd: numVal("b-experiment", "per_experiment_usd"),
    },
  };
}

function writeForm(f) {
  $("exp-id").value = f.id;
  $("release").value = f.release;
  setPuzzles(f.puzzles);
  setModels(f.models);
  $("attempts").value = f.attempts;
  $("retry-cap").value = f.retry_cap;
  $("max-tokens").value = f.max_output_tokens;
  $("b-request").value = f.budget.per_request_usd;
  $("b-model").value = f.budget.per_model_usd;
  $("b-experiment").value = f.budget.per_experiment_usd;
}

// ---- Progress data ---------------------------------------------------------
function resetProgress() {
  S.records = new Map(); S.counts = new Map(); S.arcs = new Map();
  S.lastArc = {}; S.inputs = new Map();
}

function countFor(model, puzzle) {
  const k = `${model}|${puzzle}`;
  if (!S.counts.has(k)) S.counts.set(k, { done: 0, out: {} });
  return S.counts.get(k);
}

function addRecord(rec) {
  const input = S.inputs.get(rec.input_id);
  if (!input) return;
  const key = recKey(rec.model, rec.input_id, rec.setup, rec.attempt_number);
  const c = countFor(rec.model, input.puzzle);
  const old = S.records.get(key);
  if (old && old.outcome === rec.outcome) return;
  if (old) { c.done--; c.out[old.outcome]--; }
  S.records.set(key, rec);
  c.done++; c.out[rec.outcome] = (c.out[rec.outcome] || 0) + 1;
  paintArc(key);
  updateHeaders(rec.model, input.puzzle);
}

// The attempt a running model is on: the first without a record, in run's loop order
// (input, setup, attempt number). It is an inference; run reports no such thing.
function firstPending(model) {
  for (const input of S.snap.inputs) {
    for (const setup of S.snap.setups) {
      for (let a = 1; a <= S.snap.attempts; a++) {
        const key = recKey(model, input.input_id, setup, a);
        if (!S.records.has(key)) return key;
      }
    }
  }
  return null;
}

function markInProgress() {
  for (const model of S.snap.models) {
    const prev = S.lastArc[model];
    S.lastArc[model] = S.jobs["run:" + model] === "running" ? firstPending(model) : null;
    if (prev) paintArc(prev);
    if (S.lastArc[model]) paintArc(S.lastArc[model]);
  }
}

// Fetch the snapshot and apply it. The first load of an experiment, or one whose inputs changed,
// rebuilds the progress tree; later loads only add records, so open accordions stay open.
async function loadState(id) {
  const snap = await api("GET", "/api/state/" + encodeURIComponent(id));
  const shape = JSON.stringify([id, snap.release, snap.models, snap.attempts, snap.inputs.map((i) => i.input_id)]);
  const rebuild = shape !== S.shape;
  if (rebuild) {
    resetProgress();
    S.shape = shape; S.id = id;
    S.puzzleList = [...new Set(snap.inputs.map((i) => i.puzzle))];
    for (const i of snap.inputs) S.inputs.set(i.input_id, i);
  }
  S.snap = snap;
  S.jobs = { ...snap.jobs };
  if (rebuild) renderProgress();
  for (const r of snap.records) addRecord(r);
  markInProgress();
  renderBanners();
  refreshControls();
  scheduleState();
}

// Poll the snapshot every 1.5 s while a job of the experiment is alive. The poll that sees the
// last job finish is the final one.
function scheduleState() {
  clearTimeout(S.statePoll);
  S.statePoll = anyAlive() ? setTimeout(() => {
    loadState(S.id).catch((e) => { say("form-msg", e.message, "err"); scheduleState(); });
  }, STATE_POLL_MS) : null;
}

// ---- Progress rendering ----------------------------------------------------
function chip(outcome, n) {
  const i = el("i"); i.style.background = COLORS[outcome];
  return el("span", { title: outcome }, i, String(n));
}

function puzzleTotal(puzzle) {
  return S.snap.inputs.filter((i) => i.puzzle === puzzle).length * S.snap.setups.length * S.snap.attempts;
}

function fillCounts(box, done, total, out) {
  box.replaceChildren(el("span", { text: `${done}/${total}` }));
  for (const o of OUTCOMES) if (out[o]) box.append(chip(o, out[o]));
}

function updateHeaders(model, puzzle) {
  const pb = document.querySelector(`[data-counts="${CSS.escape(model + "|" + puzzle)}"]`);
  if (pb) { const c = countFor(model, puzzle); fillCounts(pb, c.done, puzzleTotal(puzzle), c.out); }
  const mb = document.querySelector(`[data-counts="${CSS.escape(model)}"]`);
  if (mb) {
    let done = 0, total = 0; const out = {};
    for (const p of S.puzzleList) {
      const c = countFor(model, p);
      done += c.done; total += puzzleTotal(p);
      for (const [o, n] of Object.entries(c.out)) out[o] = (out[o] || 0) + n;
    }
    fillCounts(mb, done, total, out);
  }
}

function renderLegend() {
  const items = [["pending", "pending"], ["in_progress", "in progress"], ...OUTCOMES.map((o) => [o, o.replace("_", " ")])];
  $("legend").replaceChildren(...items.map(([k, label]) => {
    const i = el("i"); i.style.background = COLORS[k];
    return el("span", {}, i, label);
  }));
}

function renderRows(model, puzzle, body) {
  for (const input of S.snap.inputs.filter((i) => i.puzzle === puzzle)) {
    body.append(el("div", { class: "irow" },
      buildRing(model, input),
      el("div", { class: "meta" },
        el("div", { class: "id", text: input.input_id }),
        el("div", { text: `depth ${input.scramble_depth}, ${input.validity}` }))));
  }
}

function renderProgress() {
  const root = $("progress");
  root.className = "";
  root.replaceChildren();
  for (const model of S.snap.models) {
    const mCounts = el("span", { class: "counts", "data-counts": model });
    const mDet = el("details", {}, el("summary", {}, el("strong", { text: model }), mCounts));
    for (const puzzle of S.puzzleList) {
      const pCounts = el("span", { class: "counts", "data-counts": `${model}|${puzzle}` });
      const body = el("div", { class: "body" });
      const pDet = el("details", {}, el("summary", {}, el("span", { text: puzzle }), pCounts), body);
      let rendered = false;
      pDet.addEventListener("toggle", () => {
        if (pDet.open && !rendered) { rendered = true; renderRows(model, puzzle, body); }
      });
      mDet.append(pDet);
    }
    root.append(mDet);
    S.puzzleList.forEach((p) => updateHeaders(model, p));
  }
}

function renderBanners() {
  const box = $("banners");
  box.replaceChildren();
  for (const [job, state] of Object.entries(S.jobs)) {
    if (state === "failed") {
      box.append(el("div", { class: "banner" }, el("strong", { text: `${job} failed` }),
        el("div", {}, el("code", { text: S.lastErr[job] || "no error output" }))));
    } else if (state === "budget") {
      box.append(el("div", { class: "banner budget" },
        el("strong", { text: `Budget reached (${job})` }),
        el("div", { class: "small", text: S.lastErr[job] || "" }),
        el("div", { class: "small", text: "To resume, raise the budget under Parameters and press Run." }),
        el("div", { class: "small muted", text: "Parallel AI models can each pass the experiment budget by one worst-case request. \"Attempts left\" in the message counts one AI model's attempts." })));
    }
  }
}

// ---- Controls --------------------------------------------------------------
function anyAlive() { return Object.values(S.jobs).includes("running"); }
function runAlive() { return Object.entries(S.jobs).some(([j, s]) => j.startsWith("run:") && s === "running"); }

function refreshControls() {
  $("btn-run").disabled = runAlive();
  $("btn-estimate").disabled = anyAlive();
  $("btn-dry").disabled = anyAlive();
  renderProject();
  $("btn-stop").disabled = !runAlive();
  $("btn-evaluate").disabled = !S.id || runAlive();
  const report = S.snap && S.snap.report;
  $("btn-commit").disabled = !S.id || anyAlive() || !report;
  $("report").textContent = report ? `Report: ${report}` : "No report yet.";
}

async function postForm() {
  const form = readForm();
  const res = await api("POST", "/api/experiment", form);
  return { form, status: res.status };
}

async function guarded(msgId, fn) {
  say(msgId, "");
  try { await fn(); } catch (e) { say(msgId, e.message, "err"); }
}

function onEstimate() {
  return guarded("form-msg", async () => {
    const { form } = await postForm();
    await loadState(form.id);
    await api("POST", "/api/estimate", { id: form.id });
    await loadState(form.id);
    say("form-msg", "Estimate started; see the terminal.", "ok");
  });
}

function onRun() {
  return guarded("form-msg", async () => {
    const raw = $("limit").value.trim();
    let limit = null;
    if (raw !== "") {
      limit = Number(raw);
      if (!Number.isInteger(limit) || limit < 1) throw new Error("limit must be a whole number of at least 1");
    }
    const { form, status } = await postForm();
    await loadState(form.id);
    await api("POST", "/api/run", { id: form.id, limit });
    await loadState(form.id);
    say("form-msg", `Experiment ${status}; run started.`, "ok");
  });
}

function onDry() {
  return guarded("form-msg", async () => {
    const { form } = await postForm();
    await loadState(form.id);
    await api("POST", "/api/dry-run", { id: form.id });
    await loadState(form.id);
    say("form-msg", "Dry run started; see the terminal.", "ok");
  });
}

function onStop() {
  return guarded("form-msg", async () => {
    await api("POST", "/api/stop", { id: S.id || $("exp-id").value.trim() });
    say("form-msg", "Stop requested.", "ok");
  });
}

function onLoad() {
  return guarded("form-msg", async () => {
    const id = $("exp-id").value.trim();
    if (!id) throw new Error("id: enter an experiment id");
    const cfg = await api("GET", "/api/experiment/" + encodeURIComponent(id));
    writeForm({ ...cfg, id });
    await loadState(id);
    say("form-msg", `Loaded ${id}.`, "ok");
  });
}

function onEvaluate() {
  return guarded("commit-result", async () => {
    await api("POST", "/api/evaluate", { id: S.id, release: $("eval-release").value || null });
    await loadState(S.id);
  });
}

// ---- Setup and release -----------------------------------------------------
function renderSecrets(list) {
  $("secrets").replaceChildren(...Object.entries(list).map(([provider, s]) => {
    const status = s.source === "file" ? `Key …${s.tail} from ${s.location}`
      : s.source === "env" ? `Set by ${s.location}` : "No key";
    const key = el("input", { type: "password", autocomplete: "off", placeholder: s.variable });
    const act = (action) => guarded("secrets-msg", async () => {
      if (action === "clear" && !confirm(`Delete the saved ${provider} key?`)) return;
      renderSecrets(await api("POST", "/api/secrets", { provider, action, api_key: key.value }));
      key.value = "";
      await refreshCatalogue();
    });
    const save = el("button", { type: "button", text: "Save" });
    const clear = el("button", { type: "button", text: "Clear" });
    clear.disabled = s.source !== "file";
    save.addEventListener("click", () => act("save"));
    clear.addEventListener("click", () => act("clear"));
    return el("div", { class: "row key-row" }, el("strong", { text: provider }),
      el("span", { class: "muted small", text: status }), key, save, clear);
  }));
}

async function loadSecrets() {
  renderSecrets(await api("GET", "/api/secrets"));
}

function onImport(ev) {
  const file = ev.target.files[0];
  ev.target.value = "";
  if (!file) return;
  guarded("secrets-msg", async () => {
    const r = await api("POST", "/api/secrets/import", { text: await file.text() });
    await loadSecrets();
    await refreshCatalogue();
    say("secrets-msg", `Saved: ${r.saved.join(", ")}.`, "ok");
  });
}

// Reload the catalogue, keeping the form: models enable, new releases appear.
async function refreshCatalogue() {
  const keep = [$("release").value, $("eval-release").value];
  S.cat = await api("GET", "/api/catalogue");
  renderReleases();
  for (const [id, v] of [["release", keep[0]], ["eval-release", keep[1]]]) {
    if ([...$(id).options].some((o) => o.value === v)) $(id).value = v;
  }
  renderPuzzles();
  setModels([...S.models]);
}

async function loadProject() {
  S.project = await api("GET", "/api/project");
  renderProject();
}

function renderProject() {
  const p = S.project;
  if (!p) return;
  const pk = Object.entries(p.packages).map(([k, v]) => `${k} ${v ? "ok" : "missing"}`).join(", ");
  $("project").textContent = `Branch ${p.branch}, ${p.clean ? "clean" : "changes"}. ${pk}. gh ${p.gh ? "found" : "missing"}.`;
  const why = p.branch === "main" ? "on main" : p.branch === "HEAD" ? "detached HEAD"
    : !p.clean ? "working tree has changes: commit them first" : "";
  $("release-state").textContent = `Latest release ${p.latest_release || "none"} on ${p.branch}.${why ? " " + why + "." : ""}`;
  const busy = S.anyAlive || anyAlive();
  $("btn-release").disabled = !!why || busy;
  $("btn-push").disabled = p.branch === "main" || p.branch === "HEAD" || busy;
  for (const id of ["btn-install", "btn-tests"]) $(id).disabled = busy;
}

// Start a project job. Mark it running and poll the log at once, so a job that ends within
// seconds is still seen to end and the refresh in pollLog runs.
function projectJob(msgId, path, body, text) {
  return guarded(msgId, async () => {
    await api("POST", path, body);
    S.projRunning.add(path.slice("/api/".length));
    S.anyAlive = true;
    clearTimeout(S.logTimer);
    S.logTimer = setTimeout(pollLog, 0);
    say(msgId, text, "ok");
  });
}

function onRelease() {
  const note = $("note").value.trim();
  if (!note) return say("release-msg", "note: enter a release note", "err");
  return projectJob("release-msg", "/api/release", { bump: $("bump").value, note }, "Release started; see the terminal.");
}

function onPush() {
  return guarded("release-msg", async () => {
    say("release-msg", "Pushing...");
    const r = await api("POST", "/api/push", {});
    const out = $("release-msg");
    out.className = "msg ok";
    out.replaceChildren(`Pushed ${r.branch}. `);
    if (/^https?:\/\//.test(r.pr_url)) out.append(el("a", { href: r.pr_url, target: "_blank", rel: "noopener", text: "Open pull request" }));
    await afterProjectJob();
  });
}

async function afterProjectJob() {
  await Promise.all([loadProject(), refreshCatalogue()]).catch(() => {});
}

// ---- Commit dialog ---------------------------------------------------------
async function onCommit() {
  say("commit-result", "");
  say("commit-error", "");
  const dlg = $("commit-dialog");
  const box = $("commit-preview");
  try {
    const p = await api("GET", "/api/commit/" + encodeURIComponent(S.id));
    box.replaceChildren(
      el("p", {}, "Branch: ", el("code", { text: p.branch }), " from ", el("code", { text: String(p.base).slice(0, 10) })),
      el("p", { text: "Files:" }),
      el("ul", {}, ...p.files.map((f) => el("li", { text: f }))),
      el("pre", { text: p.diffstat }));
    $("btn-confirm").disabled = false;
    dlg.showModal();
  } catch (e) { say("commit-result", e.message, "err"); }
}

async function onConfirm() {
  $("btn-confirm").disabled = true;
  try {
    const r = await api("POST", "/api/commit", { id: S.id });
    await loadState(S.id);
    $("commit-dialog").close();
    const out = $("commit-result");
    out.className = "msg ok";
    out.replaceChildren(`Committed ${String(r.commit).slice(0, 10)} on ${r.branch}. `);
    if (/^https?:\/\//.test(r.pr_url)) out.append(el("a", { href: r.pr_url, target: "_blank", rel: "noopener", text: "Open pull request" }));
    else out.append(r.pr_url || "");
  } catch (e) {
    say("commit-error", e.message, "err");
    $("btn-confirm").disabled = false;
  }
}

// ---- Terminal --------------------------------------------------------------
function termLine(ev) {
  const term = $("terminal");
  const atBottom = term.scrollHeight - term.scrollTop - term.clientHeight < 24;
  const cls = ev.stream === "cmd" ? "cmd" : ev.stream === "stderr" ? "err" : "";
  const line = el("span", { class: cls });
  line.append(el("span", { class: "tag", text: `[${ev.job}] ` }), (ev.stream === "cmd" ? "$ " : "") + ev.text, "\n");
  term.append(line);
  while (term.childNodes.length > 5000) term.firstChild.remove();
  if (atBottom) term.scrollTop = term.scrollHeight;
}

// ---- Terminal log poll -----------------------------------------------------
async function pollLog() {
  const conn = $("conn");
  try {
    const data = await api("GET", "/api/log?after=" + S.logAfter);
    conn.textContent = "live"; conn.className = "conn ok";
    for (const line of data.lines) {
      termLine(line);
      if (line.stream === "stderr") S.lastErr[line.job] = line.text;
    }
    S.logAfter = data.last;
    S.anyAlive = data.jobs.some((j) => j.state === "running");
    const running = new Set(data.jobs.filter((j) => j.state === "running").map((j) => j.job));
    const ended = ["install", "release", "push"].some((n) => S.projRunning.has(n) && !running.has(n));
    S.projRunning = new Set([...running]);
    if (ended) afterProjectJob();
    renderProject();
    // A job of the loaded experiment started elsewhere (the CLI cannot, but a second tab can).
    if (S.id && !S.statePoll && data.jobs.some((j) => j.id === S.id && j.state === "running")) {
      loadState(S.id).catch(() => {});
    }
  } catch (e) {
    conn.textContent = "reconnecting"; conn.className = "conn bad";
  }
  clearTimeout(S.logTimer);
  S.logTimer = setTimeout(pollLog, S.anyAlive ? LOG_POLL_MS.busy : LOG_POLL_MS.idle);
}

// ---- Startup ---------------------------------------------------------------
async function init() {
  const meta = document.querySelector('meta[name="ui-token"]');
  S.token = meta ? meta.content : "";
  renderLegend();
  $("btn-estimate").addEventListener("click", onEstimate);
  $("btn-run").addEventListener("click", onRun);
  $("btn-dry").addEventListener("click", onDry);
  $("secrets-file").addEventListener("change", onImport);
  $("btn-install").addEventListener("click", () => projectJob("setup-msg", "/api/install", {}, "Install started; see the terminal."));
  $("btn-tests").addEventListener("click", () => projectJob("setup-msg", "/api/tests", {}, "Tests started; see the terminal."));
  $("btn-release").addEventListener("click", onRelease);
  $("btn-push").addEventListener("click", onPush);
  $("btn-stop").addEventListener("click", onStop);
  $("btn-load").addEventListener("click", onLoad);
  $("btn-evaluate").addEventListener("click", onEvaluate);
  $("btn-commit").addEventListener("click", onCommit);
  $("btn-confirm").addEventListener("click", onConfirm);
  $("btn-clear").addEventListener("click", () => $("terminal").replaceChildren());
  $("release").addEventListener("change", renderPuzzles);
  try {
    S.cat = await api("GET", "/api/catalogue");
    fillDefaults();
    renderReleases();
    renderModels();
  } catch (e) {
    say("form-msg", "Could not load catalogue: " + e.message, "err");
  }
  loadSecrets().catch((e) => say("secrets-msg", e.message, "err"));
  loadProject().catch((e) => say("setup-msg", e.message, "err"));
  pollLog();
}

init();
