// Spec: docs/specs/ui.md (Models)
// One block per provider: the API key controls (/api/secrets) and a table of the catalogue models. Reads the bundle only.
(function () {
  const h = UI.el;

  const usd = (v) => "$" + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });

  function keyRow(p, msg) {
    const row = h("div", { class: "row key-row" });
    const k = p.key;
    const btn = (text, fn) => { const b = h("button", { type: "button", text }); b.addEventListener("click", fn); return b; };
    const draw = (editing) => {
      const field = h("input", { type: "password", autocomplete: "off", placeholder: p.variable });
      const act = async (action) => {
        if (action === "clear" && !confirm(`Delete the saved ${p.name} key?`)) return;
        const body = { provider: p.name, action, api_key: field.value };
        field.value = "";
        msg.textContent = ""; msg.className = "msg";
        try {
          await UI.api("/api/secrets", { method: "POST", body });
          await UI.reload(false);
        } catch (e) { msg.textContent = e.message; msg.className = "msg err"; }
      };
      const status = k.source === "file" ? `Key …${k.tail} from secrets/${p.name}.json`
        : k.source === "env" ? `Set by env var ${p.variable}` : "No key";
      const parts = [h("span", { class: "muted small", text: status })];
      if (k.source === "missing" || editing) parts.push(field, btn("Save", () => act("save")));
      if (editing) parts.push(btn("Cancel", () => { field.value = ""; draw(false); }));
      else if (k.source === "file") parts.push(btn("Edit", () => draw(true)), btn("Clear", () => act("clear")));
      row.replaceChildren(...parts);
    };
    draw(false);
    return row;
  }

  const COLS = ["24%", "26%", "12%", "13%", "13%", "12%"];
  const HEADS = [["Model"], ["API model id"], ["Kind"], ["Input $/M tokens", "num"], ["Output $/M tokens", "num"], ["Experiments", "num"]];

  // One function builds the column group, so every provider's table has the same widths.
  const colgroup = () => h("colgroup", {}, ...COLS.map((w) => h("col", { style: "width:" + w })));

  function modelRow(m, p, q) {
    const noKey = p.key && p.key.source === "missing";
    const n = m.experiments.length;
    const name = h("td", {}, h("strong", { text: m.name }));
    if (m.disabled_reason && !noKey) name.append(h("div", { class: "reason", text: m.disabled_reason }));
    const price = (v) => h("td", { class: "num" }, v == null ? h("span", { class: "muted", text: "n/a" }) : usd(v));
    return h("tr", { class: m.disabled_reason || noKey ? "off" : "" }, name,
      h("td", {}, h("code", { text: m.api_model_id })),
      h("td", {}, m.kind || h("span", { class: "muted", text: "not set" })),
      price(m.price && m.price.input_per_mtok), price(m.price && m.price.output_per_mtok),
      h("td", { class: "num" }, h("a", { href: `#/experiments?model=${encodeURIComponent(m.name)}${q}`, text: String(n) })));
  }

  function modelTable(p, q) {
    return h("table", { class: "models-table" }, colgroup(),
      h("thead", {}, h("tr", {}, ...HEADS.map(([t, c]) => h("th", { class: c || "", text: t })))),
      h("tbody", {}, ...p.models.map((m) => modelRow(m, p, q))));
  }

  UI.registerPage("models", {
    render(bundle, params, el) {
      const q = params.release ? "&release=" + encodeURIComponent(params.release) : "";
      el.append(h("h2", { text: "Models" }));
      const msg = h("p", { class: "msg", role: "status" });
      for (const p of bundle.providers) {
        const missing = p.key && p.key.source === "missing";
        const head = h("div", { class: "provider-head" }, h("span", { text: p.name }));
        if (missing) head.append(h("span", { class: "reason", text: "⚠️ no API key" }));
        const box = h("section", { class: "step provider" }, head);
        if (p.key) box.append(keyRow(p, msg));
        box.append(modelTable(p, q));
        const src = bundle.repo && bundle.main_sha ? UI.sourceLink(`${bundle.repo}/blob/${bundle.main_sha}/config/models.toml`) : null;
        if (src) box.append(h("p", { class: "small" }, src));
        el.append(box);
      }
      el.append(h("p", { class: "muted small", text: "Keys are stored in ./secrets/ (one file per provider), which is .gitignored and never committed." }), msg);
    },
  });
})();
