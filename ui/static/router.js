// Spec: docs/specs/ui.md (Page, Left menu, Cache and refresh)
// The shell: hash router, bundle cache, left menu, and the job log. Pages register by name and
// get render(bundle, params, el). Reads /api/bundle and /api/log; stores only bundles in localStorage
// (`bundle:<release>`, plus `bundle:last`, the newest release returned, for the instant render when the hash names none).
(function () {
  const $ = (id) => document.getElementById(id);
  const meta = document.querySelector('meta[name="ui-token"]');
  const MENU = [["models", "Models"], ["puzzles", "Puzzles"], ["experiments", "Experiments"], ["about", "About"]];
  const pages = {};
  const st = { bundle: null, seq: 0, params: null, jobs: [], listeners: [], logAfter: 0 };

  const store = {
    get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* blocked storage only loses the cache */ } },
    drop(k) { try { localStorage.removeItem(k); } catch (e) { /* ignore */ } },
  };

  // Builds an element: props "class" and "text" are shortcuts, the rest are attributes.
  function el(tag, props, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else n.setAttribute(k, v);
    }
    for (const kid of kids) if (kid != null) n.append(kid);
    return n;
  }

  const UI = window.UI = {
    el,
    token: meta ? meta.content : "",
    async api(path, opts) {
      const o = Object.assign({ method: "GET" }, opts || {});
      o.headers = Object.assign({ "X-Token": UI.token }, o.headers);
      if (o.body !== undefined && typeof o.body !== "string") {
        o.body = JSON.stringify(o.body);
        o.headers["Content-Type"] = "application/json";
      }
      const res = await fetch(path, o);
      let data = null;
      try { data = await res.json(); } catch (e) { /* non-JSON body */ }
      if (!res.ok) throw new Error((data && data.error) || `${o.method} ${path} failed (${res.status})`);
      return data;
    },
    // Resolves with the server's bundle. onCached(cached) runs first when the cache holds one.
    async bundle(release, refresh, onCached) {
      // `bundle:last` remembers the newest release returned; it stands in when the hash names none.
      const key = "bundle:" + (release || store.get("bundle:last") || "");
      const cached = key === "bundle:" ? null : store.get(key);
      if (cached && cached.schema !== 1) store.drop(key);
      else if (cached && onCached) onCached(cached);
      const q = new URLSearchParams();
      if (release) q.set("release", release);
      if (refresh) q.set("refresh", "1");
      const fresh = await UI.api("/api/bundle?" + q);
      store.set("bundle:" + fresh.release, fresh);
      store.set("bundle:last", fresh.release);
      return fresh;
    },
    go(hash) { if (location.hash === hash) route(); else location.hash = hash; },
    registerPage(name, page) { pages[name] = page; },
    // A small "source" link, or null with no GitHub base URL.
    sourceLink(url) {
      if (!url) return null;
      const a = document.createElement("a");
      Object.assign(a, { href: url, target: "_blank", rel: "noopener", textContent: "source", className: "source" });
      return a;
    },
    // Re-request the bundle for the current release and render again.
    reload(refresh) { return load(st.params ? st.params.release : "", refresh); },
    onJobs(fn) { st.listeners.push(fn); },
    get jobs() { return st.jobs; },
    get bundleNow() { return st.bundle; },
  };

  function parse() {
    const [path, qs] = (location.hash.replace(/^#/, "") || "/experiments").split("?");
    const parts = path.split("/").filter(Boolean);
    const query = Object.fromEntries(new URLSearchParams(qs || ""));
    const top = MENU.some((m) => m[0] === parts[0]) || parts[0] === "new" ? parts[0] : "experiments";
    const rest = top === parts[0] ? parts.slice(1) : [];
    // Sub-paths: #/puzzles/<puzzle>/inputs and #/experiments/<id> have their own pages.
    const name = top === "puzzles" && rest[1] === "inputs" ? "inputs" : top === "experiments" && rest.length ? "experiment" : top;
    return { name, top, parts: rest, query, release: query.release || "" };
  }

  function menuHref(name) {
    return "#/" + name + (st.params && st.params.release ? "?release=" + encodeURIComponent(st.params.release) : "");
  }

  function drawMenu() {
    const b = st.bundle;
    if (!b) return;
    const sel = $("release");
    const keep = st.params.release || b.release;
    sel.replaceChildren(...b.releases.map((v) => Object.assign(document.createElement("option"), { value: v, textContent: v })));
    sel.value = keep;
    const warn = b.providers.some((p) => p.name !== "fake" && p.key && p.key.source === "missing");
    const current = st.params.top;
    $("links").replaceChildren(...MENU.map(([name, label]) => {
      const a = Object.assign(document.createElement("a"), { href: menuHref(name), textContent: label + (name === "models" && warn ? " ⚠️" : "") });
      if (name === current) a.className = "current";
      return a;
    }));
    const when = b.fetched_at ? new Date(b.fetched_at).toLocaleString() : "never";
    const status = $("fetch-status");
    status.textContent = b.fetch_error ? `GitHub not reached, showing data from ${when}` : `fetched ${when}`;
    status.title = b.fetch_error || "";
  }

  function draw(b, force) {
    // A reload that brings nothing new keeps the page, so typed fields survive.
    const sig = JSON.stringify([b, st.params]);
    if (!force && sig === st.drawn) return;
    st.drawn = sig;
    st.bundle = b;
    drawMenu();
    const page = pages[st.params.name];
    const main = $("main");
    if (!page) { main.replaceChildren(); return; }
    main.replaceChildren();
    page.render(b, st.params, main);
  }

  async function load(release, refresh) {
    const mine = ++st.seq;
    const btn = $("refresh");
    if (refresh) btn.classList.add("spin");
    $("fetch-error").textContent = "";
    try {
      const b = await UI.bundle(release, refresh, (c) => { if (mine === st.seq) draw(c); });
      if (mine === st.seq) draw(b);
    } catch (e) {
      if (mine === st.seq) $("fetch-error").textContent = e.message;
    } finally {
      if (mine === st.seq) btn.classList.remove("spin");
    }
  }

  // A path change within the loaded release only redraws. A release change loads its bundle.
  function route() {
    const prev = st.params;
    st.params = parse();
    if (location.hash === "" || location.hash === "#") history.replaceState(null, "", "#/experiments");
    if (st.bundle && prev && prev.release === st.params.release) draw(st.bundle, true);
    else load(st.params.release, false);
  }

  async function pollLog() {
    const conn = $("conn");
    try {
      const data = await UI.api("/api/log?after=" + st.logAfter);
      conn.textContent = "live"; conn.className = "conn ok";
      for (const ev of data.lines) termLine(ev);
      st.logAfter = data.last;
      const running = new Set(data.jobs.filter((j) => j.state === "running").map((j) => j.job));
      const ended = st.jobs.filter((j) => j.state === "running" && !running.has(j.job)).map((j) => j.job);
      st.jobs = data.jobs;
      for (const fn of st.listeners) { try { fn(st.jobs, ended); } catch (e) { console.error(e); } }
      if (ended.length) UI.reload(false);
    } catch (e) {
      conn.textContent = "reconnecting"; conn.className = "conn bad";
    }
    setTimeout(pollLog, st.jobs.some((j) => j.state === "running") ? 1000 : 5000);
  }

  function termLine(ev) {
    const term = $("terminal");
    const atBottom = term.scrollHeight - term.scrollTop - term.clientHeight < 24;
    const line = document.createElement("span");
    line.className = ev.stream === "cmd" ? "cmd" : ev.stream === "stderr" ? "err" : "";
    const tag = Object.assign(document.createElement("span"), { className: "tag", textContent: `[${ev.job}] ` });
    line.append(tag, (ev.stream === "cmd" ? "$ " : "") + ev.text + "\n");
    term.append(line);
    while (term.childNodes.length > 5000) term.firstChild.remove();
    if (atBottom) term.scrollTop = term.scrollHeight;
  }

  $("release").addEventListener("change", () => {
    const p = parse();
    const q = new URLSearchParams(p.query);
    q.set("release", $("release").value);
    UI.go("#/" + [p.top].concat(p.parts).join("/") + "?" + q);
  });
  $("refresh").addEventListener("click", () => UI.reload(true));
  $("btn-clear").addEventListener("click", () => $("terminal").replaceChildren());
  window.addEventListener("hashchange", route);
  document.addEventListener("DOMContentLoaded", () => { route(); pollLog(); });
})();
