// Spec: docs/specs/ui.md (Page, Markdown)
// window.renderMarkdown(text, linkBase) -> HTML string. Every piece of text is escaped before it
// reaches the output. Links are kept only for http, https, and relative targets.
(function () {
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c]);

  // The safe absolute URL for a link target, or null when the scheme is not allowed.
  function target(href, base) {
    if (/^[a-z][a-z0-9+.-]*:/i.test(href)) return /^https?:/i.test(href) ? href : null;
    if (href.startsWith("//")) return null;
    if (!base) return null;
    try { return new URL(href, base).href; } catch (e) { return null; }
  }

  function emphasis(s) {  // s is already escaped
    return s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/\*([^*\s][^*]*)\*/g, "<em>$1</em>");
  }

  function inline(raw, base) {
    return raw.split(/(`[^`]+`)/).map((part, i) => {
      if (i % 2) return "<code>" + esc(part.slice(1, -1)) + "</code>";
      let out = "", last = 0, m;
      const re = /\[([^\]]+)\]\(([^)\s]+)\)/g;
      while ((m = re.exec(part))) {
        out += emphasis(esc(part.slice(last, m.index)));
        const url = target(m[2], base);
        out += url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${emphasis(esc(m[1]))}</a>` : emphasis(esc(m[0]));
        last = m.index + m[0].length;
      }
      return out + emphasis(esc(part.slice(last)));
    }).join("");
  }

  const cells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  const isSep = (line) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line) && line.includes("-");
  const BLOCK = /^(\s*```|#{1,6}\s|\s*[-*]\s|\s*\d+\.\s|\s*\|)/;

  window.renderMarkdown = function (text, linkBase) {
    const lines = String(text == null ? "" : text).replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    const inl = (s) => inline(s, linkBase);
    for (let i = 0; i < lines.length;) {
      const line = lines[i];
      let m;
      if (/^\s*```/.test(line)) {
        const code = [];
        for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) code.push(lines[i]);
        i++;
        out.push("<pre><code>" + esc(code.join("\n")) + "</code></pre>");
      } else if ((m = /^(#{1,6})\s+(.*)$/.exec(line))) {
        out.push(`<h${m[1].length}>${inl(m[2].replace(/\s+#+\s*$/, ""))}</h${m[1].length}>`);
        i++;
      } else if (line.includes("|") && i + 1 < lines.length && isSep(lines[i + 1])) {
        const head = cells(line);
        const rows = [];
        for (i += 2; i < lines.length && lines[i].includes("|") && lines[i].trim(); i++) rows.push(cells(lines[i]));
        out.push("<table><thead><tr>" + head.map((c) => `<th>${inl(c)}</th>`).join("") + "</tr></thead><tbody>" +
          rows.map((r) => "<tr>" + r.map((c) => `<td>${inl(c)}</td>`).join("") + "</tr>").join("") + "</tbody></table>");
      } else if (/^\s*(\d+\.|[-*])\s/.test(line)) {
        const ordered = /^\s*\d+\./.test(line);
        const re = ordered ? /^\s*\d+\.\s+(.*)$/ : /^\s*[-*]\s+(.*)$/;
        const items = [];
        for (; i < lines.length && (m = re.exec(lines[i])); i++) items.push(`<li>${inl(m[1])}</li>`);
        out.push(ordered ? `<ol>${items.join("")}</ol>` : `<ul>${items.join("")}</ul>`);
      } else if (!line.trim()) {
        i++;
      } else {
        const para = [line];
        for (i++; i < lines.length && lines[i].trim() && !BLOCK.test(lines[i]); i++) para.push(lines[i]);
        out.push(`<p>${inl(para.join(" "))}</p>`);
      }
    }
    return out.join("\n");
  };
})();
