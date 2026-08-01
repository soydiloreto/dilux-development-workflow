# -*- coding: utf-8 -*-
"""Renders the DDW phases-and-gates diagram.

Draws with Pillow at 3x supersampling and scales down to the final size (clean
edges). Output: assets/ddw-pipeline.png (2000x775).
"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.environ.get("DDW_DIAGRAM_OUT", os.path.join(os.path.dirname(__file__), "..", "assets", "ddw-pipeline.png"))
W, H, S = 2000, 775, 3                       # final size and supersampling factor

DILUX      = (0x00, 0x86, 0x71)
DILUX_DARK = (0x00, 0x53, 0x47)
DILUX_SOFT = (0xE4, 0xF2, 0xEF)
LOCK       = (0xC4, 0x4B, 0x12)              # orange: the hook-enforced gate
LOCK_SOFT  = (0xFD, 0xEF, 0xE7)
INK        = (0x25, 0x2E, 0x2C)
MUTED      = (0x6E, 0x7D, 0x79)
LINE       = (0xC8, 0xD5, 0xD2)
BG         = (0xFF, 0xFF, 0xFF)

FONTS = "/usr/share/fonts/truetype/dejavu/"
def f(name, size):
    return ImageFont.truetype(FONTS + name, size * S)
F_TITLE = f("DejaVuSans-Bold.ttf", 40)
F_SUB   = f("DejaVuSans.ttf", 21)
F_PHASE = f("DejaVuSans-Bold.ttf", 24)
F_NUM   = f("DejaVuSans-Bold.ttf", 15)
F_BODY  = f("DejaVuSans.ttf", 14)
F_SMALL = f("DejaVuSans.ttf", 13)
F_GATE  = f("DejaVuSans-Bold.ttf", 12)
F_FOOT  = f("DejaVuSans.ttf", 16)

img = Image.new("RGB", (W * S, H * S), BG)
d = ImageDraw.Draw(img)
def sc(*v): return tuple(x * S for x in v)

def center(txt, font, cx, y, fill=INK):
    w = d.textlength(txt, font=font)
    d.text((cx * S - w / 2, y * S), txt, font=font, fill=fill)

def lines_at(txt, font, cx, y, fill, lh):
    for i, ln in enumerate(txt.split("\n")):
        center(ln, font, cx, y + i * lh, fill)

# ── header ────────────────────────────────────────────────────────────────
center("DDW — Dilux Development Workflow", F_TITLE, W / 2, 42, DILUX_DARK)
center("Six phases, and a gate to clear between each one", F_SUB, W / 2, 98, MUTED)

# ── geometry ─────────────────────────────────────────────────────────────────
PHASES = [
    ("CLASSIFY", "Understand what\nis being asked", "ticket + branch"),
    ("DEFINE",   "The what\nand the why",           "docs/ddw/prd/"),
    ("PLAN",     "The how, and what\ncould go wrong", "docs/ddw/specs/\n+ threat model"),
    ("CODE",     "Implement,\nblock by block",      "code + tests"),
    ("VERIFY",   "Have someone\nelse review it",     "docs/ddw/reports/"),
    ("RELEASE",  "Close out and\nleave a trail",     "commit + PR"),
]
GATES = [                      # condition to LEAVE each phase
    "you confirm the\nclassification",
    "gates.define",
    "gates.spec\n+ gates.threat",
    "gates.tests\n+ gates.sast",
    "gates.verify",
]
# Every gate that names a condition is hook-enforced. The first one names no
# condition — it asks for your confirmation, and a confirmation cannot be put
# in an `if`.
ENFORCED = {1, 2, 3, 4}

BW, BH, GAP = 180, 150, 112
X0, TOP = 250, 245
ay = TOP + BH / 2
idle_cx = 145

# ── IDLE pill ──────────────────────────────────────────────────────────────
d.rounded_rectangle(sc(72, TOP + 42, 218, TOP + 108), radius=33 * S,
                    fill=(0xF2, 0xF5, 0xF4), outline=LINE, width=3 * S)
center("IDLE", F_PHASE, idle_cx, TOP + 60, MUTED)
center("at rest", F_SMALL, idle_cx, TOP + 8, MUTED)

# ── phase boxes ─────────────────────────────────────────────────────────────
for i, (name, what, artifact) in enumerate(PHASES):
    x = X0 + i * (BW + GAP)
    cx = x + BW / 2
    d.rounded_rectangle(sc(x, TOP, x + BW, TOP + BH), radius=14 * S,
                        fill=DILUX_SOFT, outline=DILUX, width=3 * S)
    d.ellipse(sc(x + 11, TOP + 11, x + 41, TOP + 41), fill=DILUX)
    center(str(i + 1), F_NUM, x + 26, TOP + 18, BG)
    center(name, F_PHASE, cx, TOP + 48, DILUX_DARK)
    lines_at(what, F_BODY, cx, TOP + 92, INK, 20)
    center("produces", F_SMALL, cx, TOP + BH + 20, MUTED)
    lines_at(artifact, F_GATE, cx, TOP + BH + 40, DILUX_DARK, 17)

# ── arrows and gates ───────────────────────────────────────────────────────────
def arrow(x1, x2, y, color=DILUX, width=3):
    d.line(sc(x1, y, x2 - 11, y), fill=color, width=width * S)
    d.polygon([sc(x2, y)[0:2], sc(x2 - 13, y - 7)[0:2], sc(x2 - 13, y + 7)[0:2]], fill=color)

arrow(222, X0 - 4, ay)                                     # IDLE → CLASSIFY

for i in range(len(PHASES) - 1):
    x_end  = X0 + i * (BW + GAP) + BW
    x_next = X0 + (i + 1) * (BW + GAP)
    mid = (x_end + x_next) / 2
    enforced = (i in ENFORCED)
    col = LOCK if enforced else DILUX
    arrow(x_end + 4, mid - 22, ay, col)
    arrow(mid + 22, x_next - 4, ay, col)
    r = 21
    d.ellipse(sc(mid - r, ay - r, mid + r, ay + r),
              fill=(LOCK_SOFT if enforced else BG), outline=col, width=3 * S)
    if enforced:
        d.rounded_rectangle(sc(mid - 8, ay - 1, mid + 8, ay + 12), radius=3 * S, fill=LOCK)
        d.arc(sc(mid - 6, ay - 12, mid + 6, ay + 3), 180, 360, fill=LOCK, width=3 * S)
    else:
        d.line(sc(mid - 8, ay + 1, mid - 3, ay + 8), fill=col, width=4 * S)
        d.line(sc(mid - 3, ay + 8, mid + 9, ay - 7), fill=col, width=4 * S)
    # the gate condition, ABOVE the row of boxes (never overlapping it)
    txt = GATES[i]
    n = len(txt.split("\n"))
    lines_at(txt, F_GATE, mid, TOP - 20 - n * 18, col, 18)
    d.line(sc(mid, TOP - 14, mid, ay - r - 6), fill=col, width=1 * S)

# ── back to IDLE ─────────────────────────────────────────────────────────────
last_x = X0 + (len(PHASES) - 1) * (BW + GAP) + BW
ret_y = TOP + BH + 108
arrow(last_x + 4, last_x + 46, ay, LINE)
d.line(sc(last_x + 46, ay, last_x + 46, ret_y), fill=LINE, width=3 * S)
d.line(sc(last_x + 46, ret_y, idle_cx, ret_y), fill=LINE, width=3 * S)
d.line(sc(idle_cx, ret_y, idle_cx, TOP + 122), fill=LINE, width=3 * S)
d.polygon([sc(idle_cx, TOP + 114)[0:2], sc(idle_cx - 7, TOP + 128)[0:2],
           sc(idle_cx + 7, TOP + 128)[0:2]], fill=LINE)
center("back to IDLE, ready for the next request", F_SMALL, W / 2, ret_y + 12, MUTED)

# ── legend ───────────────────────────────────────────────────────────────
ly = 585
d.line(sc(150, ly, W - 150, ly), fill=LINE, width=2 * S)

d.ellipse(sc(230, ly + 32, 262, ly + 64), fill=BG, outline=DILUX, width=3 * S)
d.line(sc(238, ly + 49, 243, ly + 55), fill=DILUX, width=4 * S)
d.line(sc(243, ly + 55, 255, ly + 42), fill=DILUX, width=4 * S)
d.text(sc(285, ly + 38)[0:2],
       "Your confirmation — the machine closes the phase, shows you what it did, and waits.",
       font=F_FOOT, fill=INK)

d.ellipse(sc(230, ly + 84, 262, ly + 116), fill=LOCK_SOFT, outline=LOCK, width=3 * S)
d.rounded_rectangle(sc(238, ly + 101, 254, ly + 112), radius=3 * S, fill=LOCK)
d.arc(sc(240, ly + 92, 252, ly + 104), 180, 360, fill=LOCK, width=3 * S)
d.text(sc(285, ly + 90)[0:2],
       "Hook-enforced — code outside the model reads the state and refuses. Not a promise.",
       font=F_FOOT, fill=INK)

center("Every arrow needs your explicit approval   ·   every phase leaves an artifact and commits it",
       F_SMALL, W / 2, ly + 148, MUTED)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
img.resize((W, H), Image.LANCZOS).save(OUT, "PNG", optimize=True)
print("OK ->", os.path.abspath(OUT))
