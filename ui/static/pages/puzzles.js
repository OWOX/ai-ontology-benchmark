// Spec: docs/specs/ui.md (Puzzles)
// One card per puzzle of the release: a rotatable 3D picture, description, allowed moves, and input
// counts on the left, the named net on the right, then the prompt templates and the not-allowed moves
// seen. Reads the bundle only.
(function () {
  const h = UI.el;
  // Sticker size in px on the named net, the same for every puzzle size.
  const NET_CELL = 40;

  function picture(p) {
    if (!p.n) return h("div", { class: "puzzle-name-box", text: p.name });
    const wrap = h("div", { class: "puzzle-pic", title: "Drag to turn" });
    wrap.append(cube3d(solvedState(p.n), p.n, { width: 160, height: 160 }));
    return wrap;
  }

  // The source as a numbered footnote marker, or null without a source.
  function footnote(source) {
    return source ? h("sup", { class: "footnote" },
      h("a", { href: source, target: "_blank", rel: "noopener", title: "Source", text: "[1]" })) : null;
  }

  function heading(text, source) {
    return h("h4", { text }, footnote(source));
  }

  function description(p) {
    const d = p.description || {};
    const box = h("div", {}, heading("Description", d.source));
    if (!d.text) { box.append(h("p", { class: "muted", text: "no description on main" })); return box; }
    const body = h("div", { class: "md plain" });
    body.innerHTML = window.renderMarkdown(d.text, d.source ? d.source.replace(/[^/]*$/, "") : "");
    box.append(body);
    return box;
  }

  function links(p, q) {
    const row = h("p", { class: "small" },
      `${p.input_count} inputs, depths ${p.depths.join(", ") || "none"}, ${p.valid} valid, ${p.invalid} invalid. `,
      h("a", { href: `#/puzzles/${encodeURIComponent(p.name)}/inputs${q ? "?" + q : ""}`, text: "Scrambled states" }), " ",
      h("a", { href: `#/experiments?puzzle=${encodeURIComponent(p.name)}${q ? "&" + q : ""}`, text: "Experiments" }));
    return row;
  }

  // One toggle per setup. A click shows that setup's prompt template below, and a second click hides it.
  function prompts(p) {
    const box = h("div", {}, h("h4", { text: "Prompts" }));
    const setups = Object.entries(p.prompts || {});
    if (!setups.length) { box.append(h("p", { class: "muted small", text: "No prompt templates in this release." })); return box; }
    const panel = h("div", { class: "prompt-panel", hidden: true });
    const buttons = setups.map(([setup, t]) => {
      const b = h("button", { type: "button", class: "small", "aria-pressed": "false", text: setup.replace(/_/g, " ") });
      b.addEventListener("click", () => {
        const open = b.getAttribute("aria-pressed") !== "true";
        for (const o of buttons) o.setAttribute("aria-pressed", String(open && o === b));
        panel.replaceChildren();
        panel.hidden = !open;
        if (!open) return;
        panel.append(h("pre", { class: "prompt-text", text: t.text }));
        if (t.source) panel.append(h("p", { class: "small footnote-line" }, footnote(t.source), " ",
          h("a", { href: t.source, target: "_blank", rel: "noopener", text: t.source.replace(/^.*\/blob\/[^/]+\//, "") })));
      });
      return b;
    });
    box.append(h("div", { class: "setup-toggles" }, ...buttons), panel);
    return box;
  }

  function allowed(p) {
    const box = h("div", {}, heading("Allowed moves", p.legal_moves === null ? null : p.legal_moves_source));
    if (p.legal_moves === null) { box.append(h("p", { class: "muted small", text: "No engine" })); return box; }
    box.append(h("div", { class: "chips" }, ...p.legal_moves.map((m) => h("code", { class: "chip", text: m }))));
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
        if (p.n) top.append(h("div", { class: "named-net" }, cubeNetNamed(p.n, { width: 4 * p.n * NET_CELL, height: 3 * p.n * NET_CELL })));
        const card = h("section", { class: "step puzzle" }, h("h3", { text: p.name }), top, prompts(p), seen(p, q));
        el.append(card);
      }
    },
  });
})();
