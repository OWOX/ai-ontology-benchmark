# Build the template, run the style check, and render previews.
TEXBIN ?= $(HOME)/.TinyTeX/bin/x86_64-linux
export PATH := $(TEXBIN):$(PATH)

all: pdf check previews

pdf:
	latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex

check:
	python3 ste_check.py

previews: pdf
	python3 make_previews.py 8
	pdftoppm -r 150 -png -f 8 -l 8 -singlefile main.pdf previews/figure-heavy-page8

clean:
	latexmk -c

.PHONY: all pdf check previews clean
