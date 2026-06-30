#!/usr/bin/env python3
# render assets/demo.gif, an animated terminal cast of the killer flow.
# github strips smil animation from inline svg shown as <img>, so the old
# demo.svg only rendered its first frame. a plain gif animates everywhere.
# no recorder, no external service: pillow draws each line-reveal frame.
# run: python examples/make_gif.py
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FG = (205, 214, 244)
DIM = (108, 112, 134)
PROMPT = (166, 226, 46)
OK = (148, 226, 213)
RED = (243, 139, 168)
BG = (30, 30, 46)
BAR = (24, 24, 37)

# each line is a list of (text, color) spans; [] is a blank line.
LINES = [
    [("$ ", PROMPT), ("quicksave save -n pre-agent", FG)],
    [("saved 98c66e6a pre-agent ", OK), ("(3 files)", DIM)],
    [],
    [("$ ", PROMPT), ("rm -rf src .env  ", RED), ("# an agent wipes files git never tracked", DIM)],
    [("$ ", PROMPT), ("ls", FG)],
    [("README.md", FG)],
    [],
    [("$ ", PROMPT), ("quicksave restore pre-agent --clean", FG)],
    [("restored 3 files from pre-agent", OK)],
    [("$ ", PROMPT), ("ls src", FG)],
    [("app.py  ", FG), ("# back from the dead", DIM)],
]

FONT_CANDIDATES = [
    "C:/Windows/Fonts/CascadiaMono.ttf",
    "C:/Windows/Fonts/consola.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Menlo.ttc",
]
FONT_PATH = next((p for p in FONT_CANDIDATES if Path(p).exists()), None)
if FONT_PATH is None:
    raise SystemExit("no monospace font found, set FONT_PATH to one")
FONT_SIZE = 22
LINE_H = 32
PAD_X = 22
BAR_H = 44
TOP = BAR_H + 18
WIDTH = 860
HEIGHT = TOP + LINE_H * len(LINES) + 16

font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
title_font = ImageFont.truetype(FONT_PATH, 16)


def base():
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, WIDTH, BAR_H], fill=BAR)
    for i, c in enumerate([(243, 139, 168), (249, 226, 175), (166, 226, 46)]):
        d.ellipse([22 + i * 26, BAR_H // 2 - 7, 36 + i * 26, BAR_H // 2 + 7], fill=c)
    d.text((WIDTH // 2, BAR_H // 2), "quicksave", font=title_font, fill=DIM, anchor="mm")
    return img


def draw_through(n):
    img = base()
    d = ImageDraw.Draw(img)
    for row, line in enumerate(LINES[:n]):
        x = PAD_X
        y = TOP + row * LINE_H
        for text, color in line:
            d.text((x, y), text, font=font, fill=color)
            x += d.textlength(text, font=font)
    return img


frames = [draw_through(i) for i in range(1, len(LINES) + 1)]
durations = [600] * len(frames)
durations[-1] = 2800  # hold the payoff
# a short blank-ish lead so the loop reads as a restart
lead = base()
frames = [lead] + frames
durations = [500] + durations

out = Path(__file__).resolve().parent.parent / "assets" / "demo.gif"
frames[0].save(
    out,
    save_all=True,
    append_images=frames[1:],
    duration=durations,
    loop=0,
    optimize=True,
    disposal=2,
)
print(f"wrote {out} ({out.stat().st_size // 1024} kb, {len(frames)} frames)")
