// Spec: docs/specs/ui.md (Puzzles)
// One card per puzzle of the release: a rotatable 3D picture, description, allowed moves, and input
// counts on the left, the named net on the right, then the prompt templates and the not-allowed moves
// seen. Reads the bundle only.
(function () {
  const h = UI.el;

  function picture(p) {
    if (!p.n) return h("div", { class: "puzzle-name-box", text: p.name });
    const wrap = h("div", { class: "puzzle-pic", title: "Drag to turn" });
    wrap.append(cube3d(solvedState(p.n), p.n, { width: 160, height: 160 }));
    return wrap;
  }

  function description(p) {
    const d = p.description || {};
    if (!d.text) return h("p", { class: "muted", text: "no description on main" });
    const box = h("div", { class: "md" });
    box.innerHTML = window.renderMarkdown(d.text, d.source ? d.source.replace(/[^/]*$/, "") : "");
    const src = UI.sourceLink(d.source);
    if (src) box.append(src);
    return box;
  }

  function links(p, q) {
    const row = h("p", { class: "small" },
      `${p.input_count} inputs, depths ${p.depths.join(", ") || "none"}, ${p.valid} valid, ${p.invalid} invalid. `,
      h("a", { href: `#/puzzles/${encodeURIComponent(p.name)}/inputs${q ? "?" + q : ""}`, text: "Scrambled states" }), " ",
      h("a", { href: `#/experiments?puzzle=${encodeURIComponent(p.name)}${q ? "&" + q : ""}`, text: "Experiments" }));
    return row;
  }

  function prompts(p) {
    const box = h("div", {}, h("h4", { text: "What the AI model is told" }));
    const setups = Object.entries(p.prompts || {});
    if (!setups.length) box.append(h("p", { class: "muted small", text: "No prompt templates in this release." }));
    for (const [setup, t] of setups) {
      const d = h("details", {}, h("summary", { text: `${setup}${t.version ? " (prompt version " + t.version + ")" : ""}` }),
        h("pre", { class: "prompt-text", text: t.text }));
      const src = UI.sourceLink(t.source);
      if (src) d.append(src);
      box.append(d);
    }
    return box;
  }

  function allowed(p) {
    const box = h("div", {}, h("h4", { text: "Allowed moves" }));
    if (p.legal_moves === null) { box.append(h("p", { class: "muted small", text: "No engine" })); return box; }
    box.append(h("div", { class: "chips" }, ...p.legal_moves.map((m) => h("code", { class: "chip", text: m }))));
    const src = UI.sourceLink(p.legal_moves_source);
    if (src) box.append(src);
    return box;
  }

  function seen(p, q) {
    const box = h("div", {}, h("h4", { text: "Not allowed moves seen" }));
    if (!p.impossible_seen.length) { box.append(h("p", { class: "muted small", text: "None in pushed experiments yet" })); return box; }
    const rows = p.impossible_seen.map((s) => h("tr", {},
      h("td", {}, h("code", { text: s.move })), h("td", { text: String(s.count) }), h("td", { text: s.models.join(", ") }),
      h("td", {}, ...s.experiments.flatMap((id, i) => [i ? ", " : null,
        h("a", { href: `#/experiments/${encodeURIComponent(id)}${q ? "?" + q : ""}`, text: id })]))));
    box.append(h("table", {}, h("thead", {}, h("tr", {}, ...["Move", "Count", "AI models", "Experiments"].map((t) => h("th", { text: t })))),
      h("tbody", {}, ...rows)));
    return box;
  }

  UI.registerPage("puzzles", {
    render(bundle, params, el) {
      const q = params.release ? "release=" + encodeURIComponent(params.release) : "";
      el.append(h("h2", { text: "Puzzles" }));
      for (const p of bundle.puzzles) {
        const top = h("div", { class: "puzzle-top" }, h("div", { class: "puzzle-main" }, picture(p), description(p), allowed(p), links(p, q)));
        if (p.n) top.append(h("div", { class: "named-net" }, cubeNetNamed(p.n, { width: 480 })));
        const card = h("section", { class: "step puzzle" }, h("h3", { text: p.name }), top, prompts(p), seen(p, q));
        el.append(card);
      }
    },
  });
})();
