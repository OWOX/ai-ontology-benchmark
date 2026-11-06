// Spec: docs/specs/ui.md (Page, Left menu, Cache and refresh)
// The shell: hash router, bundle cache, left menu, and the job log. Pages register by name and
// get render(bundle, params, el). Reads /api/bundle and /api/log; stores only bundles in localStorage
// (`bundle:<release>`, plus `bundle:last`, the newest release returned, for the instant render when the hash names none).
(function () {
  const $ = (id) => document.getElementById(id);
  const meta = document.querySelector('meta[name="ui-token"]');
  const MENU = [["benchmarks", "Benchmarks"], ["models", "Models"], ["puzzles", "Puzzles"], ["experiments", "Experiments"], ["about", "About"]];
  const pages = {};
  const st = { bundle: null, seq: 0, params: null, jobs: [], listeners: [], lineListeners: [], logAfter: 0, lines: [] };

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

  function listen(list, fn) {
    list.push(fn);
    return () => { const i = list.indexOf(fn); if (i >= 0) list.splice(i, 1); };
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
      if (!res.ok) {
        const err = new Error((data && data.error) || `${o.method} ${path} failed (${res.status})`);
        // The token changes on every server start, so a page loaded before a restart sends a stale one.
        err.staleToken = res.status === 403 && err.message === "missing or wrong X-Token";
        throw err;
      }
      return data;
    },
    // Resolves with the server's bundle. onCached(cached) runs first when the cache holds one.
    async bundle(release, refresh, onCached) {
      // `bundle:last` remembers the newest release returned; it stands in when the hash names none.
      const key = "bundle:" + (release || store.get("bundle:last") || "");
      const cached = key === "bundle:" ? null : store.get(key);
      if (cached && cached.schema !== 3) store.drop(key);
      else if (cached && onCached) onCached(cached);
      const q = new URLSearchParams();
      if (release) q.set("release", release);
      if (refresh) q.set("refresh", "1");
      const fresh = await UI.api("/api/bundle?" + q);
      store.set("bundle:" + fresh.release, fresh);
      store.set("bundle:last", fresh.release);
      return fresh;
    },
    // The folder of a Markdown source URL, which resolves its relative links; "" with no URL.
    mdBase(url) { return url ? url.replace(/[^/]*$/, "") : ""; },
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
    // Both return a function that removes the listener.
    onJobs(fn) { return listen(st.listeners, fn); },
    onLines(fn) { return listen(st.lineListeners, fn); },
    get jobs() { return st.jobs; },
    // True when a running job of the experiment `id` has a job name that `pred` accepts (the log's job id is the experiment id).
    mine(id, pred) { return st.jobs.some((j) => j.id === id && j.state === "running" && pred(j.job)); },
    // Every log line received so far (at most 5,000, like the server), so a page can draw the history on mount.
    get lines() { return st.lines; },
    get bundleNow() { return st.bundle; },
    // Gives a `.tip-src` element the status dot's tooltip panel: the `.tip-fixed` sibling after it, placed at each open.
    tipOn(src) { for (const ev of ["mouseenter", "focus"]) src.addEventListener(ev, () => placeTip(src, src.nextElementSibling)); },
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

  function drawMenu() {
    const b = st.bundle;
    if (!b) return;
    const current = st.params.top;
    // Menu links always lead to the newest release: with no release select, a `?release=` picked up from one
    // link would otherwise stick to every page.
    $("links").replaceChildren(...MENU.map(([name, label]) => {
      const a = Object.assign(document.createElement("a"), { href: "#/" + name, textContent: label });
      if (name === current) a.className = "current";
      return a;
    }));
    st.fetch = { at: b.fetched_at, error: b.fetch_error };
    drawConn();
  }

  // One dot beside the title: server state by colour, and a tooltip panel in plain sentences.
  function drawConn() {
    const el = $("conn"), tip = $("conn-tip"), f = st.fetch || {};
    const when = f.at ? new Date(f.at).toLocaleString() : "";
    const err = String(f.error || "").replace(/\.$/, "");
    const server = { live: "The server is live.", down: "The server is not reachable. Reconnecting." }[st.server] || "Connecting to the server.";
    const fetched = f.error
      ? (when ? `GitHub was not reached, so this shows data from ${when}. Error: ${err}.` : `GitHub was not reached and there is no data yet. Error: ${err}.`)
      : when ? `Data was fetched from GitHub on ${when}.` : "Nothing has been fetched yet.";
    const b = st.bundle, newest = b && b.releases && b.releases[0];
    const release = !b ? "" : !newest || newest === b.release ? `Release ${b.release}, the newest.` : `Release ${b.release}. The newest is ${newest}.`;
    const text = [server, fetched, release].filter(Boolean).join(" ");
    const cls = "conn tip-src" + (st.server === "down" ? " bad" : st.server === "live" ? (f.error ? " warn" : " ok") : "");
    // The log poll calls this every few seconds. Writing only on change keeps an open panel steady.
    if (el.className !== cls) el.className = cls;
    if (tip.textContent !== text) tip.textContent = text;
  }

  // The panel is fixed so the menu's overflow cannot clip it. It is placed at each open, because the menu can scroll.
  function placeTip(src, tip) {
    const r = src.getBoundingClientRect();
    const left = Math.max(12, Math.min(r.left - 6, window.innerWidth - 12 - tip.offsetWidth));
    tip.style.left = left + "px";
    // Below the source, or above it when the panel would run past the bottom of the window and there is more room above.
    const below = r.bottom + 6 + tip.offsetHeight <= window.innerHeight - 12 || window.innerHeight - r.bottom >= r.top;
    tip.style.top = (below ? r.bottom + 6 : Math.max(12, r.top - 6 - tip.offsetHeight)) + "px";
  }
  UI.tipOn($("conn"));

  function draw(b, force) {
    // A reload that brings nothing new keeps the page, so typed fields survive.
    const sig = JSON.stringify([b, st.params]);
    if (!force && sig === st.drawn) return;
    st.drawn = sig;
    st.bundle = b;
    drawMenu();
    $("termbox").hidden = st.params.name !== "about";
    const page = pages[st.params.name];
    const main = $("main");
    main.replaceChildren();
    if (!page) return;
    page.render(b, st.params, main);
  }

  function showFetchError(e) {
    const box = $("fetch-error");
    if (!e.staleToken) { box.textContent = e.message; return; }
    const link = el("a", { href: location.href, text: "Reload the page" });
    link.addEventListener("click", (ev) => { ev.preventDefault(); location.reload(); });
    box.replaceChildren("The server restarted, so this page is out of date. ", link, ".");
  }

  async function load(release, refresh) {
    const mine = ++st.seq;
    const btn = $("refresh");
    if (refresh) btn.classList.add("spin");
    $("fetch-error").textContent = "";
    try {
      const b = await UI.bundle(release, refresh, (c) => { if (mine === st.seq) draw(c); });
      // ↻ redraws the page even when the bundle brings nothing new, so the page loads its own data again.
      if (mine === st.seq) draw(b, refresh);
    } catch (e) {
      if (mine === st.seq) showFetchError(e);
    } finally {
      if (mine === st.seq) btn.classList.remove("spin");
    }
  }

  // A path change within the loaded release only redraws. A release change loads its bundle.
  function route() {
    const prev = st.params;
    st.params = parse();
    if (location.hash === "" || location.hash === "#") history.replaceState(null, "", "#/experiments");
    const reloadLink = $("fetch-error").querySelector("a");
    if (reloadLink) reloadLink.href = location.href;  // the stale-token link keeps pointing at the current view
    if (st.bundle && prev && prev.release === st.params.release) draw(st.bundle, true);
    else load(st.params.release, false);
  }

  // One poll at a time: a call while one is in flight shares it, and a call between polls runs one now and
  // reschedules the next.
  function pollLog() {
    if (st.polling) return st.polling;
    clearTimeout(st.pollTimer);
    st.polling = pollOnce().finally(() => {
      st.polling = null;
      st.pollTimer = setTimeout(pollLog, st.jobs.some((j) => j.state === "running") ? 1000 : 5000);
    });
    return st.polling;
  }
  // Brings the job states up to date at once. A poll already in flight may predate what the caller just did,
  // so it waits for that one and then polls again.
  UI.pollNow = async () => { if (st.polling) await st.polling; return pollLog(); };

  async function pollOnce() {
    try {
      const data = await UI.api("/api/log?after=" + st.logAfter);
      st.server = "live"; drawConn();
      for (const ev of data.lines) {
        st.lines.push(ev);
        if (st.lines.length > 5000) st.lines.shift();
        termLine(ev);
        for (const fn of st.lineListeners.slice()) { try { fn(ev); } catch (e) { console.error(e); } }
      }
      st.logAfter = data.last;
      const key = (j) => j.id + "\u0000" + j.job;
      const running = new Set(data.jobs.filter((j) => j.state === "running").map(key));
      const ended = st.jobs.filter((j) => j.state === "running" && !running.has(key(j))).map((j) => j.job);
      st.jobs = data.jobs;
      for (const fn of st.listeners.slice()) { try { fn(st.jobs, ended); } catch (e) { console.error(e); } }
      if (ended.length) UI.reload(false);
    } catch (e) {
      st.server = "down"; drawConn();
    }
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

  document.addEventListener("click", (e) => {  // a click outside an open column or release picker closes it
    for (const d of document.querySelectorAll("details.col-picker[open]")) if (!d.contains(e.target)) d.open = false;
  });
  $("refresh").addEventListener("click", () => UI.reload(true));
  $("new-exp").addEventListener("click", () => UI.go("#/new"));
  $("btn-clear").addEventListener("click", () => $("terminal").replaceChildren());
  window.addEventListener("hashchange", route);
  document.addEventListener("DOMContentLoaded", () => { route(); pollLog(); });
})();
