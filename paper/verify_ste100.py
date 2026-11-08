# Spec: docs/specs/paper-verify-ste100.md
r"""Verify ASD-STE100 compliance and paragraph structure on an HTML file (default: build/main.check.html, written by ste_check.py).

Checks:
1. Every <p> element (matched via <p(?:\s[^>]*)?>...</p>, avoiding SVG <path>)
   outside procedural steps and reference items contains sentences with at most 25 words.
2. Every procedural step (<ol class="procedure"><li><p>...</p></li></ol>)
   contains exactly one sentence, at most 20 words, and starts with an imperative verb.
3. No hardcoded section numbers in <h2> or <h3> tags.
4. Every body prose <p> element (outside <ol> and <ul> lists) is a genuine multi-sentence
   academic paragraph (>= 2 sentences, with mean >= 3.0 sentences per paragraph).
5. Every bullet item in <ul class="compact-list"> wraps all of its sentences inside a single
   <li><p>...</p></li> element (>= 2 sentences per bullet item).
"""

import re
import sys
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parent / "build" / "main.check.html"

P_TAG_RE = re.compile(r"<p(?:\s[^>]*)?>(.*?)</p>", re.DOTALL | re.IGNORECASE)
PROC_BLOCK_RE = re.compile(r'<ol\s+class="procedure"[^>]*>(.*?)</ol>', re.DOTALL | re.IGNORECASE)
REF_BLOCK_RE = re.compile(r'<ol\s+class="ref-list"[^>]*>(.*?)</ol>', re.DOTALL | re.IGNORECASE)
UL_BLOCK_RE = re.compile(r'<ul\s+class="compact-list"[^>]*>(.*?)</ul>', re.DOTALL | re.IGNORECASE)
LI_TAG_RE = re.compile(r"<li(?:\s[^>]*)?>(.*?)</li>", re.DOTALL | re.IGNORECASE)
TAG_STRIP_RE = re.compile(r"<[^>]+>")
HEADING_RE = re.compile(r"<(h[23])(?:\s[^>]*)?>(.*?)</\1>", re.DOTALL | re.IGNORECASE)

IMPERATIVE_VERBS = {
    "open", "run", "execute", "verify", "check", "create", "inspect", "confirm",
    "set", "export", "install", "start", "stop", "freeze", "commit", "push",
    "merge", "compare", "compute", "record", "review", "read", "write", "select",
    "enter", "navigate", "change", "clone", "configure", "launch", "validate",
    "score", "raise", "test", "ensure", "build", "generate", "copy", "update",
}


def clean_html(raw: str) -> str:
    text = TAG_STRIP_RE.sub(" ", raw)
    replacements = {
        "&le;": "<=",
        "&ge;": ">=",
        "&equiv;": "=",
        "&times;": "x",
        "&middot;": "*",
        "&minus;": "-",
        "&ndash;": "-",
        "&mdash;": " - ",
        "&rarr;": "->",
        "&rArr;": "=>",
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&nbsp;": " ",
        "&bull;": "*",
        "&hellip;": "...",
        "&plusmn;": "+/-",
        "&isin;": "in",
        "&notin;": "not_in",
        "&succ;": ">",
        "&sum;": "sum",
        "&sigma;": "sigma",
        "&tau;": "tau",
        "&circ;": "o",
        "&ntilde;": "n",
    }
    for entity, repl in replacements.items():
        text = text.replace(entity, repl)
    return " ".join(text.split())


def split_sentences(text: str) -> list[str]:
    protected = re.sub(r"(\d)\.(\d)", r"\1<DOT>\2", text)
    protected = re.sub(r"(\d)\.(\d)", r"\1<DOT>\2", protected)
    protected = re.sub(
        r"\.(py|sh|md|toml|jsonl|json|txt|js|css|html|pdf|org|com)\b",
        r"<DOT>\1",
        protected,
    )
    protected = re.sub(r"\b(al|Biomed|Inform|J|V|M|S)\.", r"\1<DOT>", protected)
    parts = re.split(r"(?<=[.!?])\s+", protected.strip())
    return [p.replace("<DOT>", ".").strip() for p in parts if p.strip()]


def count_words(sentence: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9_*/+-]+(?:'[A-Za-z0-9]+)?", sentence)
    return tokens


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else HTML_PATH
    if not path.is_file():
        print(f"FAIL: File not found: {path}")
        return 1

    html = path.read_text(encoding="utf-8")
    violations = []

    # 1. Check headings for hardcoded numbers
    headings = list(HEADING_RE.finditer(html))
    h2_count = 0
    h3_count = 0
    for m in headings:
        tag, inner = m.group(1).lower(), clean_html(m.group(2))
        if tag == "h2":
            h2_count += 1
        elif tag == "h3":
            h3_count += 1
        if re.match(r"^\d+(\.\d+)*\.?\s+", inner):
            violations.append(f"[HEADING NUMBER] <{tag}> has hardcoded number: {inner!r}")

    # 2. Check procedural steps (<ol class="procedure">)
    proc_blocks = PROC_BLOCK_RE.findall(html)
    proc_step_count = 0
    proc_p_texts = set()

    if not proc_blocks:
        violations.append('[PROCEDURE] No <ol class="procedure"> block found in HTML.')

    for block in proc_blocks:
        for li_match in LI_TAG_RE.finditer(block):
            proc_step_count += 1
            li_raw = li_match.group(1)
            for pm in P_TAG_RE.finditer(li_raw):
                proc_p_texts.add(pm.group(1))
            text = clean_html(li_raw)
            sentences = split_sentences(text)
            if len(sentences) != 1:
                violations.append(
                    f"[PROCEDURE STEP {proc_step_count}] Expected 1 sentence per step, got {len(sentences)}: {text!r}"
                )
            for s in sentences:
                words = count_words(s)
                if len(words) > 20:
                    violations.append(
                        f"[PROCEDURE STEP {proc_step_count} > 20 WORDS ({len(words)} words)] {s!r}"
                    )
                if words and words[0].lower() not in IMPERATIVE_VERBS:
                    violations.append(
                        f"[PROCEDURE STEP {proc_step_count} IMPERATIVE] First word {words[0]!r} not in imperative list: {s!r}"
                    )

    # 3. Collect reference and bullet list <p> elements
    ref_p_texts = set()
    for block in REF_BLOCK_RE.findall(html):
        for pm in P_TAG_RE.finditer(block):
            ref_p_texts.add(pm.group(1))

    ul_p_texts = set()
    ul_item_count = 0
    for block in UL_BLOCK_RE.findall(html):
        for li_match in LI_TAG_RE.finditer(block):
            ul_item_count += 1
            li_raw = li_match.group(1)
            p_in_li = list(P_TAG_RE.finditer(li_raw))
            if len(p_in_li) != 1:
                violations.append(
                    f"[LIST ITEM #{ul_item_count}] Expected exactly 1 <p> inside <li>, got {len(p_in_li)}"
                )
            for pm in p_in_li:
                ul_p_texts.add(pm.group(1))
                sents = split_sentences(clean_html(pm.group(1)))
                if len(sents) < 2:
                    violations.append(
                        f"[LIST ITEM #{ul_item_count}] Expected multi-sentence bullet (>= 2 sentences), got {len(sents)}"
                    )

    # 4. Check all <p> elements using <p(?:\s[^>]*)?>
    p_matches = list(P_TAG_RE.finditer(html))
    desc_sentence_count = 0
    max_desc_words = 0
    max_proc_words = 0
    prose_p_sentence_counts = []

    for idx, pm in enumerate(p_matches, 1):
        inner_raw = pm.group(1)
        is_proc = inner_raw in proc_p_texts
        is_ref = inner_raw in ref_p_texts
        is_ul = inner_raw in ul_p_texts
        text = clean_html(inner_raw)
        sentences = split_sentences(text)

        if not is_proc and not is_ref and not is_ul:
            prose_p_sentence_counts.append(len(sentences))
            if len(sentences) < 2:
                violations.append(
                    f"[ONE-SENTENCE PROSE <p> #{idx}] Prose paragraphs must contain >= 2 sentences: {text!r}"
                )

        limit = 20 if is_proc else 25
        for s in sentences:
            words = count_words(s)
            wlen = len(words)
            if is_proc:
                max_proc_words = max(max_proc_words, wlen)
            else:
                desc_sentence_count += 1
                max_desc_words = max(max_desc_words, wlen)
            if wlen > limit:
                kind = "PROCEDURAL <p>" if is_proc else "DESCRIPTIVE <p>"
                violations.append(
                    f"[{kind} #{idx} > {limit} WORDS ({wlen} words)] {s!r}"
                )

    avg_sents_per_prose_p = (
        sum(prose_p_sentence_counts) / len(prose_p_sentence_counts)
        if prose_p_sentence_counts
        else 0.0
    )
    if avg_sents_per_prose_p < 3.0:
        violations.append(
            f"[PARAGRAPH DENSITY] Mean sentences per body prose <p> is {avg_sents_per_prose_p:.2f} (expected >= 3.0)"
        )

    print("=== ASD-STE100 & Academic Structure Verification Report ===")
    print(f"File scanned                 : {path}")
    print(f"Top-level <h2> sections      : {h2_count}")
    print(f"Subsection <h3> headings     : {h3_count}")
    print(f"Total <p> elements           : {len(p_matches)}")
    print(f"Body prose <p> paragraphs    : {len(prose_p_sentence_counts)} (mean: {avg_sents_per_prose_p:.2f} sentences/paragraph)")
    print(f"Multi-sentence <ul> bullets  : {ul_item_count}")
    print(f"Descriptive sentences        : {desc_sentence_count} (max words: {max_desc_words} / 25)")
    print(f"Procedural steps             : {proc_step_count} (max words: {max_proc_words} / 20)")
    print(f"Total violations             : {len(violations)}")

    if violations:
        print("\nVIOLATIONS:")
        for v in violations:
            print("  -", v)
        return 1

    print("\nSTATUS: PASS (0 violations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
