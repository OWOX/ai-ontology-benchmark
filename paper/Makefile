# Build the template, run the style check, and render previews.
# Put the TeX binaries on PATH when a folder exists. The first folder that exists wins:
# TEXBIN, then the TinyTeX folders. Otherwise rely on PATH. build.sh uses the same order.
TEXDIR := $(firstword $(wildcard $(TEXBIN) $(HOME)/Library/TinyTeX/bin/universal-darwin $(HOME)/.TinyTeX/bin/universal-darwin $(HOME)/.TinyTeX/bin/x86_64-linux))
ifneq ($(TEXDIR),)
export PATH := $(TEXDIR):$(PATH)
endif

all: pdf check previews

pdf:
	latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex

check:
	python3 ste_check.py

previews: pdf
	mkdir -p previews
	python3 make_previews.py $$(pdfinfo main.pdf | awk '/^Pages:/{print $$2}')
	idout=$$(python3 ids.py) || { echo "$$idout"; exit 1; }; \
	echo "$$idout" | grep -v FIGURE_HEAVY_PAGE; \
	heavy=$$(echo "$$idout" | awk '/FIGURE_HEAVY_PAGE/{print $$2}'); \
	rm -f previews/figure-heavy-page*.png; \
	pdftoppm -r 150 -png -f $$heavy -l $$heavy -singlefile main.pdf previews/figure-heavy-page$$heavy

clean:
	latexmk -c

.PHONY: all pdf check previews clean
