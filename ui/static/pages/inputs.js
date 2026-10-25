// Spec: docs/specs/ui.md (Puzzles, inputs paragraph)
// Every input of one puzzle, from /api/inputs, with depth and validity filters. Reads the bundle for the source link.
(function () {
  const h = UI.el;
  let shown = null;  // the key of the page being drawn, so a late response for an old page is dropped

  function row(r, n) {
    const net = h("td", {}, n ? cubeNet(r.state, { width: 150 }) : h("code", { text: r.state }));
    const extra = r.validity === "invalid"
      ? [`from ${r.source_input_id}`, r.corruption].filter(Boolean).join(": ") : "";
    return h("tr", {}, h("td", {}, h("code", { text: r.input_id })), h("td", { text: String(r.scramble_depth) }),
      h("td", { text: r.validity }), net, h("td", { class: "small", text: extra }));
  }

  UI.registerPage("inputs", {
    render(bundle, params, el) {
      const puzzle = decodeURIComponent(params.parts[0] || "");
      const info = bundle.puzzles.find((p) => p.name === puzzle);
      const q = params.release ? "?release=" + encodeURIComponent(params.release) : "";
      el.append(h("h2", { text: `${puzzle} inputs` }), h("p", { class: "small" }, h("a", { href: "#/puzzles" + q, text: "Back to puzzles" })));
      if (!info) { el.append(h("p", { class: "muted", text: "This release has no such puzzle." })); return; }
      const src = UI.sourceLink(info.inputs_source);
      const depth = h("select", { "aria-label": "Depth" }, h("option", { value: "", text: "all depths" }),
        ...info.depths.map((d) => h("option", { value: String(d), text: `depth ${d}` })));
      const validity = h("select", { "aria-label": "Validity" },
        ...[["", "all inputs"], ["valid", "valid only"], ["invalid", "invalid only"]].map(([v, t]) => h("option", { value: v, text: t })));
      const out = h("div", {}, h("p", { class: "muted", text: "Loading." }));
      el.append(h("p", {}, depth, " ", validity, " ", src), out);
      let rows = [];
      const draw = () => {
        const keep = rows.filter((r) => (!depth.value || String(r.scramble_depth) === depth.value) && (!validity.value || r.validity === validity.value));
        const head = h("tr", {}, ...["Input", "Depth", "Validity", "State", "Source and corruption"].map((t) => h("th", { text: t })));
        out.replaceChildren(h("p", { class: "small muted", text: `${keep.length} of ${rows.length} inputs` }),
          h("table", {}, h("thead", {}, head), h("tbody", {}, ...keep.map((r) => row(r, info.n)))));
      };
      depth.addEventListener("change", draw);
      validity.addEventListener("change", draw);
      const key = shown = Symbol();
      UI.api(`/api/inputs?release=${encodeURIComponent(bundle.release)}&puzzle=${encodeURIComponent(puzzle)}`)
        .then((data) => { if (shown === key) { rows = data; draw(); } })
        .catch((e) => { if (shown === key) out.replaceChildren(h("p", { class: "msg err", text: e.message })); });
    },
  });
})();
