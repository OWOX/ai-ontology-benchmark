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
  inprog: {},              // model -> attempt | null
  jobs: {},                // job -> state
  lastErr: {},             // job -> last stderr line
  arcs: new Map(),         // key -> path element
  lastArc: {},             // model -> key painted as in progress
};

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
  if (method === "POST" || path.startsWith("/api/commit/")) headers["X-Token"] = S.token;
  if (method === "POST") {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body || {});
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (e) { /* non-JSON body */ }
  if (res.status === 403 && data && data.error === "missing or wrong X-Token") {
    S.stale = true;
    renderBanners();
    throw new Error("The server restarted. Reload the page.");
  }
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
    const n = Number(name.split("x")[0]) || 2;
    const counts = rel.input_counts && rel.input_counts[name];
    const card = el("div", { class: "card", role: "button", tabindex: "0", "aria-pressed": "false" },
      cubeNet(solvedState(n), { width: 96, height: 72 }),
      el("div", { class: "name", text: name }),
      el("div", { class: "muted small", text: counts != null ? `${counts} inputs` : "" }));
    const toggle = () => {
      if (S.puzzles.has(name)) S.puzzles.delete(name); else S.puzzles.add(name);
      card.classList.toggle("sel", S.puzzles.has(name));
      card.setAttribute("aria-pressed", String(S.puzzles.has(name)));
    };
    card.addEventListener("click", toggle);
    card.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
    card.classList.toggle("sel", S.puzzles.has(name));
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
  if (f.release) { $("release").value = f.release; }
  setPuzzles(f.puzzles || []);
  setModels(f.models || []);
  if (f.attempts != null) $("attempts").value = f.attempts;
  if (f.retry_cap != null) $("retry-cap").value = f.retry_cap;
  if (f.max_output_tokens != null) $("max-tokens").value = f.max_output_tokens;
  const b = f.budget || {};
  if (b.per_request_usd != null) $("b-request").value = b.per_request_usd;
  if (b.per_model_usd != null) $("b-model").value = b.per_model_usd;
  if (b.per_experiment_usd != null) $("b-experiment").value = b.per_experiment_usd;
}

// ---- Progress data ---------------------------------------------------------
function resetProgress() {
  S.records = new Map(); S.counts = new Map(); S.inprog = {}; S.arcs = new Map();
  S.lastArc = {}; S.jobs = {}; S.inputs = new Map();
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
  if (old) { c.done--; c.out[old.outcome]--; }
  S.records.set(key, rec);
  c.done++; c.out[rec.outcome] = (c.out[rec.outcome] || 0) + 1;
  paintArc(key);
  updateHeaders(rec.model, input.puzzle);
}

function setInProgress(model, attempt) {
  const prev = S.lastArc[model];
  S.inprog[model] = attempt;
  S.lastArc[model] = attempt ? recKey(model, attempt.input_id, attempt.setup, attempt.attempt_number) : null;
  if (prev) paintArc(prev);
  if (S.lastArc[model]) paintArc(S.lastArc[model]);
}

// Events for the target id that arrive while its snapshot is in flight.
let pendingLoad = null; // {id, events: []}

function applyEvent(name, ev) {
  if (name === "record") addRecord(ev.record);
  else if (name === "in_progress") setInProgress(ev.model, ev.attempt);
  else if (name === "job") onJob(ev);
}

async function loadState(id) {
  const pending = { id, events: [] };
  pendingLoad = pending;
  let snap;
  try {
    snap = await api("GET", "/api/state/" + encodeURIComponent(id));
  } catch (e) {
    if (pendingLoad === pending) pendingLoad = null;
    throw e;
  }
  if (pendingLoad !== pending) return; // a newer load superseded this one
  resetProgress();
  S.id = id; S.snap = snap;
  for (const i of snap.inputs) S.inputs.set(i.input_id, i);
  S.jobs = { ...snap.jobs };
  renderProgress();
  for (const r of snap.records) addRecord(r);
  for (const [m, a] of Object.entries(snap.in_progress || {})) setInProgress(m, a);
  pendingLoad = null;
  for (const [name, ev] of pending.events) applyEvent(name, ev);
  refreshControls();
}

// ---- Progress rendering ----------------------------------------------------
function chip(outcome, n) {
  const i = el("i"); i.style.background = COLORS[outcome];
  return el("span", { title: outcome }, i, String(n));
}

function headerText(model, puzzle) {
  const total = (puzzle ? S.snap.inputs.filter((i) => i.puzzle === puzzle).length : 0) * S.snap.setups.length * S.snap.attempts;
  const c = countFor(model, puzzle);
  return { total, c };
}

function fillCounts(box, done, total, out) {
  box.replaceChildren(el("span", { text: `${done}/${total}` }));
  for (const o of OUTCOMES) if (out[o]) box.append(chip(o, out[o]));
}

function updateHeaders(model, puzzle) {
  const pb = document.querySelector(`[data-counts="${CSS.escape(model + "|" + puzzle)}"]`);
  if (pb) { const { total, c } = headerText(model, puzzle); fillCounts(pb, c.done, total, c.out); }
  const mb = document.querySelector(`[data-counts="${CSS.escape(model)}"]`);
  if (mb) {
    let done = 0, total = 0; const out = {};
    for (const p of S.snap.puzzles) {
      const h = headerText(model, p);
      done += h.c.done; total += h.total;
      for (const [o, n] of Object.entries(h.c.out)) out[o] = (out[o] || 0) + n;
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
  S.snap.puzzles = [...new Set(S.snap.inputs.map((i) => i.puzzle))];
  for (const model of S.snap.models) {
    const mCounts = el("span", { class: "counts", "data-counts": model });
    const mDet = el("details", {}, el("summary", {}, el("strong", { text: model }), mCounts));
    for (const puzzle of S.snap.puzzles) {
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
    S.snap.puzzles.forEach((p) => updateHeaders(model, p));
  }
  renderBanners();
}

function renderBanners() {
  const box = $("banners");
  box.replaceChildren();
  if (S.stale) box.append(el("div", { class: "banner" }, el("strong", { text: "The server restarted. Reload the page." })));
  for (const [job, state] of Object.entries(S.jobs)) {
    if (state === "failed") {
      box.append(el("div", { class: "banner" }, el("strong", { text: `${job} failed` }),
        el("div", {}, el("code", { text: S.lastErr[job] || "no error output" }))));
    } else if (state === "budget") {
      const btn = el("button", { type: "button", text: "Raise budget and resume" });
      btn.addEventListener("click", () => {
        $("b-experiment").scrollIntoView({ behavior: "smooth", block: "center" });
        $("b-experiment").focus();
      });
      box.append(el("div", { class: "banner budget" },
        el("strong", { text: `Budget reached (${job})` }),
        el("div", { class: "small", text: S.lastErr[job] || "" }),
        el("div", { class: "small muted", text: "Parallel AI models can each pass the experiment budget by one worst-case request. \"Attempts left\" in the message counts one AI model's attempts." }),
        btn));
    }
  }
}

// ---- Controls --------------------------------------------------------------
function anyAlive() { return Object.values(S.jobs).includes("running"); }
function runAlive() { return Object.entries(S.jobs).some(([j, s]) => j.startsWith("run:") && s === "running"); }

function refreshControls() {
  $("btn-run").disabled = runAlive();
  $("btn-estimate").disabled = anyAlive();
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
    say("form-msg", `Experiment ${status}; run started.`, "ok");
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
    await api("POST", "/api/evaluate", { id: S.id });
  });
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

// ---- Event stream ----------------------------------------------------------
function onJob(ev) {
  S.jobs[ev.job] = ev.state;
  renderBanners();
  refreshControls();
  if (ev.job === "evaluate" && ev.state === "done") loadState(S.id).catch((e) => say("commit-result", e.message, "err"));
}

function openEvents() {
  const conn = $("conn");
  const es = new EventSource("/api/events");
  es.onopen = () => {
    conn.textContent = "live"; conn.className = "conn ok";
    if (S.id) loadState(S.id).catch(() => {});
  };
  es.onerror = () => { conn.textContent = "reconnecting"; conn.className = "conn bad"; };
  const on = (name, fn) => es.addEventListener(name, (m) => {
    let ev; try { ev = JSON.parse(m.data); } catch (e) { return; }
    fn(ev);
  });
  on("terminal", (ev) => {
    termLine(ev);
    if (ev.stream === "stderr") S.lastErr[ev.job] = ev.text;
  });
  for (const name of ["record", "in_progress", "job"]) {
    on(name, (ev) => {
      if (pendingLoad && ev.id === pendingLoad.id) pendingLoad.events.push([name, ev]);
      else if (ev.id === S.id && S.snap) applyEvent(name, ev);
    });
  }
}

// ---- Startup ---------------------------------------------------------------
async function init() {
  const meta = document.querySelector('meta[name="ui-token"]');
  S.token = meta ? meta.content : "";
  renderLegend();
  $("btn-estimate").addEventListener("click", onEstimate);
  $("btn-run").addEventListener("click", onRun);
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
  openEvents();
}

init();
