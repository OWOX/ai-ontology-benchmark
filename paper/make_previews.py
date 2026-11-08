# Spec: docs/specs/paper-previews.md
"""Render page PNGs and a contact sheet (preview.png) of the first pages of main.pdf."""
import glob, subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw

here = Path(__file__).resolve().parent
out = here / "previews"
out.mkdir(exist_ok=True)
for f in out.glob("page-*.png"):
    f.unlink()
subprocess.run(["pdftoppm", "-r", "110", "-png", str(here / "main.pdf"), str(out / "page")], check=True)
pages = sorted(out.glob("page-*.png"))
n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
imgs = [Image.open(p).convert("RGB") for p in pages[:n]]
w, h = imgs[0].size
cols = 4
rows = (len(imgs) + cols - 1) // cols
scale = 0.5
tw, th = int(w * scale), int(h * scale)
pad = 16
sheet = Image.new("RGB", (cols * (tw + pad) + pad, rows * (th + pad) + pad), (210, 210, 210))
for i, im in enumerate(imgs):
    r, c = divmod(i, cols)
    x, y = pad + c * (tw + pad), pad + r * (th + pad)
    sheet.paste(im.resize((tw, th), Image.LANCZOS), (x, y))
    ImageDraw.Draw(sheet).rectangle([x - 1, y - 1, x + tw, y + th], outline=(90, 90, 90))
sheet.save(here / "preview.png")
print("pages:", len(pages), "sheet:", sheet.size)
