# paper-previews

File: `paper/make_previews.py`.

## Purpose

Render page images of `paper/main.pdf` so a reader can review the layout without opening the PDF. `paper/build.sh` and `make previews` run it last. They pass the page count from `pdfinfo`, so the contact sheet covers every page.

## Inputs

1. `paper/main.pdf`.
2. Optional argument: the number of pages on the contact sheet. Default 8.

## Outputs

1. `paper/previews/page-NN.png`: every page at 110 dpi. Old page images are deleted first.
2. `paper/preview.png`: a contact sheet of the first N pages, four per row.

Both are build output and are ignored by git.

## How to test

1. Run `python3 make_previews.py 8` in `paper/`. One PNG exists per PDF page, and `preview.png` shows 8 pages.

`tests/test_paper_previews.py` runs this on a copy of `main.pdf`. It skips without poppler or Pillow.
