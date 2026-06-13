#!/usr/bin/env python3
# generate assets/demo.svg, an animated terminal cast of the killer flow.
# no deps, no recorder, no external service: the reveal is a clipPath whose
# height steps down one line at a time on a loop, so it animates inline on
# github when the readme links it as an image. run: python examples/make_cast.py
import html
from pathlib import Path

# colors roughly track the readme's terminal output
FG = "#cdd6f4"
DIM = "#6c7086"
PROMPT = "#a6e22e"
OK = "#94e2d5"
WARN = "#f38ba8"
BG = "#1e1e2e"
BAR = "#181825"

# each line is a list of (text, color) spans. an empty list is a blank line.
LINES = [
    [("$ ", PROMPT), ("quicksave init", FG)],
    [("initialized quicksave in /tmp/demo", DIM)],
    [],
    [("$ ", PROMPT), ("quicksave save -n pre-agent", FG)],
    [("saved 98c66e6a pre-agent ", OK), ("(3 files)", DIM)],
    [],
    [("$ ", PROMPT), ("rm -rf src .env  ", FG), ("# the agent wipes untracked files", DIM)],
    [],
    [("$ ", PROMPT), ("quicksave restore pre-agent --clean", FG)],
    [("restored 3 files from pre-agent", OK)],
    [],
    [("$ ", PROMPT), ("ls src", FG)],
    [("app.py  ", FG), ("# back from the dead", DIM)],
]

CHAR_W = 8.4
LINE_H = 22
FONT = 14
PAD_X = 18
BAR_H = 34
TOP = BAR_H + 16
WIDTH = 660
HEIGHT = TOP + LINE_H * len(LINES) + 16

# step the reveal one line per frame, hold the full screen, then loop
STEP = 0.55
HOLD = 2.2
total = STEP * len(LINES) + HOLD
heights = [TOP - 6]
for i in range(len(LINES)):
    heights.append(TOP + (i + 1) * LINE_H - 4)
heights.append(heights[-1])  # extra stop so the last line sits during the hold
values = ";".join(f"{h:.0f}" for h in heights)
keytimes = [0.0]
for i in range(len(LINES)):
    keytimes.append(round(STEP * (i + 1) / total, 4))
keytimes.append(1.0)
keys = ";".join(f"{k}" for k in keytimes)


def spans(line, y):
    out = []
    x = PAD_X
    for text, color in line:
        out.append(
            f'<text x="{x:.1f}" y="{y}" fill="{color}" xml:space="preserve">'
            f"{html.escape(text)}</text>"
        )
        x += len(text) * CHAR_W
    return "".join(out)


body = []
for i, line in enumerate(LINES):
    y = TOP + i * LINE_H + FONT
    if line:
        body.append(spans(line, y))

dots = "".join(
    f'<circle cx="{18 + i * 18}" cy="{BAR_H / 2:.0f}" r="6" fill="{c}"/>'
    for i, c in enumerate(("#f38ba8", "#f9e2af", "#a6e22e"))
)

svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="{FONT}">
  <clipPath id="reveal">
    <rect x="0" y="0" width="{WIDTH}" height="{heights[0]:.0f}">
      <animate attributeName="height" calcMode="discrete" values="{values}" keyTimes="{keys}" dur="{total:.2f}s" repeatCount="indefinite"/>
    </rect>
  </clipPath>
  <rect width="{WIDTH}" height="{HEIGHT}" rx="10" fill="{BG}"/>
  <rect width="{WIDTH}" height="{BAR_H}" rx="10" fill="{BAR}"/>
  <rect y="{BAR_H - 10}" width="{WIDTH}" height="10" fill="{BAR}"/>
  {dots}
  <text x="{WIDTH / 2:.0f}" y="{BAR_H / 2 + 4:.0f}" fill="{DIM}" text-anchor="middle" font-size="12">quicksave - demo</text>
  <g clip-path="url(#reveal)">
    {"".join(body)}
  </g>
</svg>
"""

out = Path(__file__).resolve().parent.parent / "assets" / "demo.svg"
out.parent.mkdir(exist_ok=True)
out.write_text(svg, encoding="utf-8")
print(f"wrote {out} ({len(svg)} bytes)")
