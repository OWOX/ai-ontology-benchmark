// Spec: docs/specs/ui.md (Page, Markdown)
// Loads ui/static/markdown.js in a bare context and checks the renderer. Exits 1 on any failure.
import fs from "node:fs";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const file = fileURLToPath(new URL("../../ui/static/markdown.js", import.meta.url));
const ctx = { window: {}, URL };
vm.runInNewContext(fs.readFileSync(file, "utf8"), ctx);
const md = ctx.window.renderMarkdown;
const BASE = "https://github.com/o/r/blob/s/";

let failed = 0;
function check(name, ok, html) {
  if (!ok) { failed++; console.error(`FAIL ${name}\n  got: ${html}`); }
}
const has = (h, s) => h.includes(s);

let h = md("<script>alert(1)</script>", BASE);
check("script escaped", !has(h, "<script") && has(h, "&lt;script"), h);
h = md("[x](javascript:alert(1))", BASE);
check("javascript link dropped", !has(h, 'href="javascript') && !has(h, "<a "), h);
h = md("[x](data:text/html,hi) [y](//evil.example/a)", BASE);
check("data and protocol-relative dropped", !has(h, "<a "), h);
h = md("<img src=x onerror=alert(1)>", BASE);
check("img escaped", !has(h, "<img"), h);
h = md('[a"b](https://e.com/?q="1"&x=<2>)', BASE);
check("attribute escaped", !has(h, '"1"') && !has(h, "<2>"), h);
h = md("| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |", BASE);
check("table", has(h, "<table>") && (h.match(/<td>/g) || []).length === 4 && (h.match(/<tr>/g) || []).length === 3, h);
h = md("1. a\n2. b", BASE);
check("ordered list", has(h, "<ol>") && (h.match(/<li>/g) || []).length === 2, h);
h = md("- a\n- b", BASE);
check("bullet list", has(h, "<ul>") && (h.match(/<li>/g) || []).length === 2, h);
h = md("[r](docs/a.md)", BASE);
check("relative link", has(h, 'href="https://github.com/o/r/blob/s/docs/a.md"'), h);
h = md("[r](https://example.com/x)", BASE);
check("https link", has(h, 'href="https://example.com/x"'), h);
h = md("[r](docs/a.md)", "");
check("relative link without base is text", !has(h, "<a "), h);
h = md("# T\n\nsome `<b>` and **bold** and *it*\n\n```\n<i>&\n```", BASE);
check("blocks", has(h, "<h1>T</h1>") && has(h, "<code>&lt;b&gt;</code>") && has(h, "<strong>bold</strong>") &&
  has(h, "<em>it</em>") && has(h, "<pre><code>&lt;i&gt;&amp;</code></pre>"), h);

if (failed) process.exit(1);
console.log("markdown tests passed");
