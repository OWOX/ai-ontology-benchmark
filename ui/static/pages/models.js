// Spec: docs/specs/ui.md (Models)
// One block per provider: the key badge and icons (/api/secrets) and a table of the catalogue models. Reads the bundle only.
(function () {
  const h = UI.el;

  const usd = (v) => "$" + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 });

  const SVG = {
    edit: '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    source: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/>',
  };

  // An icon-only button (or a link, with href) from the static markup above.
  function icon(kind, label, fn, href) {
    const a = h(href ? "a" : "button", { class: "icon-btn", title: label, "aria-label": label, ...(href ? { href, target: "_blank", rel: "noopener" } : { type: "button" }) });
    a.innerHTML = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${SVG[kind]}</svg>`;
    if (fn) a.addEventListener("click", fn);
    return a;
  }

  async function secret(p, action, msg, key, account) {
    msg.textContent = ""; msg.className = "msg";
    try {
      await UI.api("/api/secrets", { method: "POST", body: { provider: p.name, action, api_key: key, ...(account === undefined ? {} : { account_id: account }) } });
      await UI.reload(false);
      return true;
    } catch (e) { msg.textContent = e.message; msg.className = "msg err"; return false; }
  }

  // The key edit row: the password field, showing only the saved key's last 4 characters, then (for a provider
  // with an account id) a second password field, then Save, Cancel, and Clear. An empty field keeps the saved value. Cancel is left out when there is no key to fall back to, and Clear when no key is saved in a file.
  function editRow(p, msg, onCancel) {
    const saved = p.key.source === "file" || (p.key.account && p.key.account.source === "file");
    const field = h("input", { type: "password", autocomplete: "off", "aria-label": `${p.name} API key`,
      placeholder: p.key.source === "file" ? "•".repeat(12) + p.key.tail : p.variable });
    const acc = p.key.account;
    const accountField = acc ? h("input", { type: "password", autocomplete: "off", "aria-label": `${p.name} account id`,
      placeholder: acc.source === "file" ? "•".repeat(12) : acc.variable }) : null;
    const save = h("button", { type: "button", text: "Save" });
    save.addEventListener("click", async () => {
      const key = field.value; field.value = "";
      let account;
      if (accountField) { account = accountField.value; accountField.value = ""; }
      // The reload redraws the page, so the new Edit icon takes the focus.
      if (await secret(p, "save", msg, key, account)) { const e = document.querySelector(`.provider[data-provider="${p.name}"] [aria-label="Edit API key"]`); if (e) e.focus(); }
    });
    const row = h("div", { class: "row key-row" }, field, ...(accountField ? [accountField] : []), save);
    if (onCancel) {
      const cancel = h("button", { type: "button", text: "Cancel" });
      cancel.addEventListener("click", () => { field.value = ""; if (accountField) accountField.value = ""; onCancel(); });
      row.append(cancel);
    }
    if (saved) {
      const clear = h("button", { type: "button", class: "danger", text: "Clear" });
      clear.addEventListener("click", () => { if (confirm(`Delete the saved ${p.name} ${p.key.account ? "API token and account id" : "API key"}?`)) secret(p, "clear", msg, ""); });
      row.append(clear);
    }
    return row;
  }

  function providerBlock(p, bundle, msg, q) {
    const k = p.key;
    const acc = k && k.account;
    const lacks = !k ? [] : [k.source === "missing" ? "API key" : null, acc && acc.source === "missing" ? "account id" : null].filter(Boolean);
    const status = !k ? "" : lacks.length ? `Missing: ${lacks.join(" and ")}` : k.source === "file" ? `Key …${k.tail} from secrets/${p.name}.json`
      : `Set by env var ${p.variable}`;
    const missing = k && lacks.length > 0;
    const head = h("div", { class: "provider-head" }, h("span", { text: p.name }));
    if (k) head.append(h("span", { class: "badge " + (missing ? "bad" : "ok"), title: status, text: missing ? "not configured" : "configured" }));
    if (k && !missing) head.append(h("span", { class: "muted small", title: status, text: status }));
    const slot = h("div");
    let edit = null;
    const close = () => { slot.replaceChildren(); if (edit) edit.focus(); };
    const open = () => {
      if (slot.firstChild) return;
      const row = editRow(p, msg, missing ? null : close);
      slot.replaceChildren(row);
      row.querySelector("input").focus();
    };
    const icons = h("div", { class: "provider-icons" });
    if (k && (k.source === "file" || missing || (acc && acc.source === "file"))) icons.append(edit = icon("edit", "Edit API key", open));
    if (bundle.repo && bundle.main_sha) icons.append(icon("source", "Source: config/models.toml", null, `${bundle.repo}/blob/${bundle.main_sha}/config/models.toml`));
    head.append(icons);
    if (missing) open();
    return h("section", { class: "step provider", "data-provider": p.name }, head, slot, modelTable(p, q));
  }

  const COLS = ["24%", "26%", "12%", "13%", "13%", "12%"];
  const HEADS = [["Model"], ["API model id"], ["Kind"], ["Input $/M tokens", "amount"], ["Output $/M tokens", "amount"], ["Experiments", "amount"]];

  // One function builds the column group, so every provider's table has the same widths.
  const colgroup = () => h("colgroup", {}, ...COLS.map((w) => h("col", { style: "width:" + w })));

  function modelRow(m, p, q) {
    const noKey = p.key && !p.key.configured;
    const n = m.experiments.length;
    const name = h("td", {}, h("strong", { text: m.name }));
    if (m.disabled_reason && !noKey) name.append(h("div", { class: "reason", text: m.disabled_reason }));
    const price = (v) => h("td", { class: "amount" }, v == null ? h("span", { class: "muted", text: "n/a" }) : usd(v));
    return h("tr", { class: m.disabled_reason || noKey ? "off" : "" }, name,
      h("td", {}, h("code", { text: m.api_model_id })),
      h("td", {}, m.kind || h("span", { class: "muted", text: "not set" })),
      price(m.price && m.price.input_per_mtok), price(m.price && m.price.output_per_mtok),
      h("td", { class: "amount" }, h("a", { href: `#/experiments?model=${encodeURIComponent(m.name)}${q}`, text: String(n) })));
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
      for (const p of bundle.providers) el.append(providerBlock(p, bundle, msg, q));
      el.append(h("p", { class: "muted small", text: "Keys are stored in ./secrets/ (one file per provider), which is .gitignored and never committed." }), msg);
    },
  });
})();
