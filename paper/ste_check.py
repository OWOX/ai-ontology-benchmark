# Spec: docs/specs/paper-ste-check.md
"""Convert main.tex to a check HTML file and run verify_ste100.py on it.

verify_ste100.py reads HTML. This script maps the LaTeX source onto the HTML structure
that the verifier expects:
  \\section / \\subsection           -> <h2> / <h3>
  body paragraphs, abstract,        -> <p>   (sentence <= 25 words, >= 2 sentences)
  uncertainty boxes
  itemize                           -> <ul class="compact-list"><li><p>  (>= 2 sentences)
  procedure (enumerate)             -> <ol class="procedure"><li><p>  (1 sentence, <= 20 words, imperative)
  captions and placeholder texts    -> <ol class="ref-list"><li><p>  (word limit only)
Inline math becomes one token, \\cref becomes "Figure 1", \\cite becomes "[1]".
It then runs extra checks the verifier does not cover: at most 5 sentences per body
paragraph, forbidden terms, and hardcoded section numbers in the text.
"""
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEX = HERE / "main.tex"
OUT = HERE / "build" / "main.check.html"
VERIFY = HERE / "verify_ste100.py"
FORBIDDEN = [r"A/B[- ]?plot", r"\bA-plot\b", r"\bB-plot\b", r"Veritasium", r"Error 404", r"Reviewer 2", r"Reviewer\s*#?2"]


def strip_comments(src: str) -> str:
    return "\n".join(re.sub(r"(?<!\\)%.*$", "", line) for line in src.splitlines())


def arg_end(s: str, i: int) -> int:
    """s[i] == '{'; return index after the matching '}'."""
    depth = 0
    for k in range(i, len(s)):
        if s[k] == "{":
            depth += 1
        elif s[k] == "}":
            depth -= 1
            if depth == 0:
                return k + 1
    raise ValueError("unbalanced braces")


def replace_cmd(s: str, name: str, fn, nargs: int = 1) -> str:
    pat = re.compile(r"\\" + name + r"\*?(?:\[[^\]]*\])?\s*(?=\{)")
    out, pos = [], 0
    while True:
        m = pat.search(s, pos)
        if not m:
            out.append(s[pos:])
            return "".join(out)
        out.append(s[pos:m.start()])
        k, args = m.end(), []
        for _ in range(nargs):
            while k < len(s) and s[k].isspace():
                k += 1
            e = arg_end(s, k)
            args.append(s[k + 1:e - 1])
            k = e
        out.append(fn(*args))
        pos = k


def extract_env(s: str, env: str):
    pat = re.compile(r"\\begin\{" + re.escape(env) + r"\}(.*?)\\end\{" + re.escape(env) + r"\}", re.S)
    return pat


def inline(t: str) -> str:
    t = t.replace(r"\$", "")
    t = re.sub(r"\$[^$]*\$", " X ", t)
    t = replace_cmd(t, "todo", lambda a: f" [TODO: {inline(a)}] ")
    t = replace_cmd(t, "val", lambda a: " [VALUE] ")
    for c in ("cref", "Cref"):
        t = replace_cmd(t, c, lambda a: "Figure 1")
    t = replace_cmd(t, "ref", lambda a: "1")
    for c in ("citep", "citet", "cite"):
        t = replace_cmd(t, c, lambda a: "[1]")
    t = replace_cmd(t, "label", lambda a: "")
    for c in ("code", "texttt", "emph", "textbf", "textit", "mathrm", "path"):
        t = replace_cmd(t, c, lambda a: a)
    t = t.replace(r"\_", "_").replace(r"\%", "%").replace(r"\&", "&").replace(r"\$", "$")
    t = t.replace(r"\{", "{").replace(r"\}", "}").replace("~", " ").replace("---", " - ").replace("--", "-")
    t = t.replace("``", '"').replace("''", '"')
    t = re.sub(r"\\[a-zA-Z]+\*?", " ", t)
    t = t.replace("{", "").replace("}", "")
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return " ".join(t.split())


def items(block: str):
    block = re.sub(r"\\(begin|end)\{[a-z]+\}(\[[^\]]*\])?", " ", block)
    parts = re.split(r"\\item\b", block)
    return [inline(p) for p in parts[1:] if p.strip()]


def main() -> int:
    src = strip_comments(TEX.read_text(encoding="utf-8"))
    body = src.split(r"\begin{document}", 1)[1].split(r"\end{document}", 1)[0]
    body = body.replace(r"\appendix", "")
    captions, ph_texts = [], []

    def grab_float(m):
        blk = m.group(0)
        replace_cmd(blk, "caption", lambda a: captions.append(inline(a)) or "")
        replace_cmd(blk, "phpanel", lambda *a: ph_texts.append(inline(a[5])) or "", nargs=6)
        replace_cmd(blk, "phsingle", lambda *a: ph_texts.append(inline(a[1])) or "", nargs=2)
        return "\n\n"
    for env in ("figure*", "figure", "table*", "table"):
        body = extract_env(body, env).sub(grab_float, body)
    for env in ("equation", "align", "gathered", "tikzpicture", "phcanvas", "tabularx", "lstlisting"):
        body = extract_env(body, env).sub("\n", body)
    body = re.sub(r"\\lstinputlisting(\[[^\]]*\])?\{[^}]*\}", "\n\n", body)
    body = re.sub(r"\\(bibliographystyle|bibliography|maketitle)\{?[^}\n]*\}?", "\n", body)

    html = ["<!DOCTYPE html><html><body>"]
    tokens = re.split(r"(\\section\*?\{[^}]*\}|\\subsection\*?\{[^}]*\}|\\begin\{itemize\}.*?\\end\{itemize\}|\\begin\{procedure\}.*?\\end\{procedure\}|\\begin\{uncertainty\}\{[^}]*\}|\\end\{uncertainty\}|\\begin\{abstract\}|\\end\{abstract\})", body, flags=re.S)
    para_counts = []
    for tok in tokens:
        if not tok or not tok.strip():
            continue
        m = re.match(r"\\(section|subsection)\*?\{([^}]*)\}", tok)
        if m:
            tag = "h2" if m.group(1) == "section" else "h3"
            html.append(f"<{tag}>{inline(m.group(2))}</{tag}>")
            continue
        if tok.startswith(r"\begin{itemize}"):
            html.append('<ul class="compact-list">' + "".join(f"<li><p>{x}</p></li>" for x in items(tok)) + "</ul>")
            continue
        if tok.startswith(r"\begin{procedure}"):
            html.append('<ol class="procedure">' + "".join(f"<li><p>{x}</p></li>" for x in items(tok)) + "</ol>")
            continue
        if tok.startswith(r"\begin{uncertainty}") or tok.startswith(r"\end{") or tok.startswith(r"\begin{abstract}"):
            continue
        for para in re.split(r"\n\s*\n", tok):
            t = inline(para)
            if t:
                html.append(f"<p>{t}</p>")
    html.append('<ol class="ref-list">' + "".join(f"<li><p>{c}</p></li>" for c in captions + ph_texts) + "</ol>")
    html.append("</body></html>")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(html), encoding="utf-8")
    print(f"Wrote {OUT} ({len(captions)} captions, {len(ph_texts)} placeholder texts)")

    rc = subprocess.run([sys.executable, str(VERIFY), str(OUT)]).returncode

    # Extra checks
    sys.path.insert(0, str(VERIFY.parent))
    import verify_ste100 as v
    extra = []
    text = OUT.read_text(encoding="utf-8")
    ul = {m for b in v.UL_BLOCK_RE.findall(text) for m in v.P_TAG_RE.findall(b)}
    pr = {m for b in v.PROC_BLOCK_RE.findall(text) for m in v.P_TAG_RE.findall(b)}
    rf = {m for b in v.REF_BLOCK_RE.findall(text) for m in v.P_TAG_RE.findall(b)}
    for m in v.P_TAG_RE.finditer(text):
        inner = m.group(1)
        if inner in ul or inner in pr or inner in rf:
            continue
        n = len(v.split_sentences(v.clean_html(inner)))
        if n > 5 or n < 3:
            extra.append(f"[PARAGRAPH NOT 3-5 SENTENCES ({n})] {v.clean_html(inner)[:90]}...")
    raw = TEX.read_text(encoding="utf-8")
    for pat in FORBIDDEN:
        for m in re.finditer(pat, raw, re.I):
            extra.append(f"[FORBIDDEN TERM] {m.group(0)!r} at offset {m.start()}")
    for m in re.finditer(r"\b(Section|Sec\.|Figure|Fig\.|Table|Equation|Eq\.)\s+\d", strip_comments(raw)):
        extra.append(f"[HARDCODED REFERENCE] {m.group(0)!r}")
    # Placeholder IDs come from the float counter; a typed ID could drift from the number.
    for m in re.finditer(r"\b(?:fig|tab)-onto-\d+", strip_comments(raw)):
        extra.append(f"[HARDCODED PLACEHOLDER ID] {m.group(0)!r}")
    print("\n=== Extra checks (paragraph length 3-5, forbidden terms, hardcoded refs and placeholder IDs) ===")
    print(f"Extra violations             : {len(extra)}")
    for e in extra:
        print("  -", e)
    return 1 if (rc or extra) else 0


if __name__ == "__main__":
    sys.exit(main())
