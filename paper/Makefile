# Build the template, run the style check, and render previews.
# Put the TeX binaries on PATH when their folder exists. Otherwise rely on PATH.
# Set TEXBIN to use another folder.
TEXBIN ?= $(firstword $(wildcard $(HOME)/Library/TinyTeX/bin/universal-darwin $(HOME)/.TinyTeX/bin/universal-darwin $(HOME)/.TinyTeX/bin/x86_64-linux))
ifneq ($(wildcard $(TEXBIN)),)
export PATH := $(TEXBIN):$(PATH)
endif

all: pdf check previews

pdf:
	latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex

check:
	python3 ste_check.py

previews: pdf
	mkdir -p previews
	python3 make_previews.py $$(pdfinfo main.pdf | awk '/Pages/{print $$2}')
	heavy=$$(python3 ids.py | awk '/FIGURE_HEAVY_PAGE/{print $$2}'); \
	rm -f previews/figure-heavy-page*.png; \
	pdftoppm -r 150 -png -f $$heavy -l $$heavy -singlefile main.pdf previews/figure-heavy-page$$heavy

clean:
	latexmk -c

.PHONY: all pdf check previews clean
