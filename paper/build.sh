#!/usr/bin/env bash
# Build main.pdf, run the STE100 and ID checks, and render previews.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build previews
# Put the TeX binaries on PATH when their folder exists. Otherwise rely on PATH.
# Set TEXBIN to use another folder.
for dir in "${TEXBIN:-}" "$HOME/Library/TinyTeX/bin/universal-darwin" "$HOME/.TinyTeX/bin/universal-darwin" "$HOME/.TinyTeX/bin/x86_64-linux"; do
  if [ -n "$dir" ] && [ -d "$dir" ]; then
    export PATH="$dir:$PATH"
    break
  fi
done
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex > build/latexmk.log 2>&1 || { tail -40 main.log; exit 1; }
grep -h "placeholders: scaled" main.log || true
python3 ste_check.py
idout=$(python3 ids.py) || { echo "$idout"; exit 1; }
echo "$idout" | grep -v FIGURE_HEAVY_PAGE
heavy=$(echo "$idout" | awk '/FIGURE_HEAVY_PAGE/{print $2}')
pages=$(pdfinfo main.pdf | awk '/Pages/{print $2}')
python3 make_previews.py "$pages"
rm -f previews/figure-heavy-page*.png
pdftoppm -r 150 -png -f "$heavy" -l "$heavy" -singlefile main.pdf "previews/figure-heavy-page$heavy"
echo "Figure-heavy page: previews/figure-heavy-page$heavy.png"
echo "Built main.pdf ($pages pages)"
