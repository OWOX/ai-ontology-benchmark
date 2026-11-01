#!/usr/bin/env bash
# Build main.pdf, run the STE100 and ID checks, and render previews.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build previews
export PATH="${TEXBIN:-$HOME/.TinyTeX/bin/x86_64-linux}:$PATH"
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex > build/latexmk.log 2>&1 || { tail -40 main.log; exit 1; }
grep -h "placeholders: scaled" main.log || true
python3 ste_check.py
idout=$(python3 ids.py) || { echo "$idout"; exit 1; }
echo "$idout" | grep -v FIGURE_HEAVY_PAGE
heavy=$(echo "$idout" | awk '/FIGURE_HEAVY_PAGE/{print $2}')
python3 make_previews.py 8
rm -f previews/figure-heavy-page*.png
pdftoppm -r 150 -png -f "$heavy" -l "$heavy" -singlefile main.pdf "previews/figure-heavy-page$heavy"
echo "Figure-heavy page: previews/figure-heavy-page$heavy.png"
echo "Built main.pdf ($(pdfinfo main.pdf | awk '/Pages/{print $2}') pages)"
