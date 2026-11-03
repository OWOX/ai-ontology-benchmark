// Spec: docs/specs/ui.md (Progress, Arc colours, banners)
// Drawing helpers for progress.js: the ring arc path, outcome chips, the legend, and the job banners.
// Pure DOM builders: they read their arguments and write nothing else.
(function () {
  const h = UI.el;

  function arcPath(cx, cy, r0, r1, a0, a1) {
    const pt = (r, a) => `${(cx + r * Math.cos(a)).toFixed(2)} ${(cy + r * Math.sin(a)).toFixed(2)}`;
    const large = a1 - a0 > Math.PI ? 1 : 0;
    return `M ${pt(r1, a0)} A ${r1} ${r1} 0 ${large} 1 ${pt(r1, a1)} L ${pt(r0, a1)} A ${r0} ${r0} 0 ${large} 0 ${pt(r0, a0)} Z`;
  }

  function chip(colors, outcome, n) {
    const i = h("i"); i.style.background = colors[outcome];
    return h("span", { title: outcome }, i, String(n));
  }

  function legend(colors, outcomes) {
    const items = [["pending", "pending"], ["in_progress", "in progress"],
      ...outcomes.map((k) => [k, k.replace("_", " ")])];
    return h("div", { class: "legend" }, ...items.map(([k, label]) => {
      const i = h("i"); i.style.background = colors[k];
      return h("span", {}, i, label);
    }));
  }

  // The bar across the top of the Experiment page: done over planned attempts, a % label, and a chip per outcome.
  // update({done, planned, out}) redraws it.
  function bar(colors, outcomes) {
    const fillBar = h("div", { class: "pbar-fill" });
    const label = h("span", { class: "pbar-label", text: "0%" });
    const counts = h("span", { class: "counts" });
    const track = h("div", { class: "pbar-track", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-label": "Attempts done" }, fillBar);
    const node = h("div", { class: "pbar" }, track, label, counts);
    function update(t) {
      const pct = t.planned ? Math.floor((100 * t.done) / t.planned) : 0;
      fillBar.style.width = (t.planned ? (100 * t.done) / t.planned : 0) + "%";
      track.setAttribute("aria-valuenow", String(pct));
      label.textContent = t.planned ? `${pct}% \u00b7 ${t.done}/${t.planned}` : "waiting for the first results";
      counts.replaceChildren();
      for (const k of outcomes) if (t.out[k]) counts.append(chip(colors, k, t.out[k]));
    }
    return { node, update };
  }

  // A failed job shows its last stderr line; a job in state budget shows the plain note.
  function banners(jobs, lastErr) {
    const out = [];
    for (const [job, state] of Object.entries(jobs)) {
      if (state === "failed") {
        out.push(h("div", { class: "banner" }, h("strong", { text: `${job} failed` }),
          h("div", {}, h("code", { text: lastErr[job] || "no error output" }))));
      } else if (state === "budget") {
        out.push(h("div", { class: "banner budget" }, h("strong", { text: `Budget reached (${job})` }),
          h("div", { class: "small", text: lastErr[job] || "" }),
          h("div", { class: "small", text: "To resume, open New Experiment, pick this branch, raise the budget under Parameters, and press Run." }),
          h("div", { class: "small muted", text: "Parallel AI models run as separate processes and can each pass the experiment budget by their own in-flight requests. \"Attempts left\" in the message counts one AI model's attempts." })));
      }
    }
    return out;
  }

  window.ProgressView = { arcPath, chip, legend, banners, bar };
})();
