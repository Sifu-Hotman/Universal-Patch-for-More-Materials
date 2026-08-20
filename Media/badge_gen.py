#!/usr/bin/env python3
"""Universal Patch for More Materials: badge + Workshop preview.

Same geometry system as the rest of my mods' badges (300x100 bar/circle/ring
knockout; 512 preview) so they read as one set, with its own identity:

- Accent INGOT BLUE. Copper would have been the thematic pick, but it sits ~9
  degrees from the Loadouts amber and ~27 from the Tactics red — squeezed between
  two hues already in use. Blue at ~220 is 44 clear of the Loadout Quality teal
  and 45 clear of the Better Attack Orders violet.
- Emblem is a stack of three ingots, drawn here from scratch. Nothing in this
  badge derives from Combat Extended's art: this mod has no CE dependency and no
  weapons in it.

Run from Media/:  python3 badge_gen.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSansCondensed-Bold.ttf"
S = 4
BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)
INGOT = (58, 104, 212, 255)


def ingots(img, d, cx, cy, scale, accent):
    """Three stacked ingots: two on the bottom course, one centred on top."""
    def ingot(x, y, w, h, fill):
        taper = w * 0.22
        d.polygon(
            [(x - w / 2 + taper, y - h / 2), (x + w / 2 - taper, y - h / 2),
             (x + w / 2, y + h / 2), (x - w / 2, y + h / 2)],
            fill=fill,
        )

    w = 34 * scale
    h = 15 * scale
    gap = 2 * scale
    ingot(cx - (w + gap) / 2, cy + h * 0.75, w, h, WHITE)
    ingot(cx + (w + gap) / 2, cy + h * 0.75, w, h, WHITE)
    ingot(cx, cy - h * 0.75, w, h, accent)


def render_badge():
    W, H = 300 * S, 100 * S
    bar = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    db = ImageDraw.Draw(bar)
    db.rectangle([0, 25 * S, 300 * S, 74 * S], fill=BLACK)
    hole = Image.new("L", (W, H), 0)
    dh = ImageDraw.Draw(hole)
    cx, cy, r, gap = 50 * S, 50 * S, 50 * S, 5 * S
    dh.ellipse([cx - (r + gap), cy - (r + gap), cx + (r + gap), cy + (r + gap)], fill=255)
    dh.rectangle([0, 0, 5 * S, H], fill=255)
    bar.putalpha(Image.composite(Image.new("L", (W, H), 0), bar.getchannel("A"), hole))

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    img.alpha_composite(bar)
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BLACK)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=INGOT, width=3 * S)
    ingots(img, d, cx, cy, S, INGOT)

    f1 = ImageFont.truetype(FONT, 15 * S)
    f2 = ImageFont.truetype(FONT, 10 * S)
    CX = 202 * S
    t1 = "UNIVERSAL PATCH"
    w1 = d.textlength(t1, font=f1)
    d.text((CX - w1 / 2, 32 * S), t1, font=f1, fill=WHITE)
    t2 = "for MORE MATERIALS"
    K = 1.6 * S
    w2 = sum(d.textlength(c, font=f2) + K for c in t2) - K
    x = CX - w2 / 2
    for ch in t2:
        d.text((x, 55 * S), ch, font=f2, fill=INGOT)
        x += d.textlength(ch, font=f2) + K
    img.resize((300, 100), Image.LANCZOS).save(os.path.join(HERE, "Badge_UPMM.png"))
    print("wrote Badge_UPMM.png")


def render_preview():
    P = 4
    W = H = 512 * P
    img = Image.new("RGBA", (W, H), (12, 12, 12, 255))
    d = ImageDraw.Draw(img)
    cx, cy, r = 256 * P, 190 * P, 140 * P
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BLACK, outline=INGOT, width=8 * P)
    ingots(img, d, cx, cy, P * 2.8, INGOT)

    f1 = ImageFont.truetype(FONT, 36 * P)
    f2 = ImageFont.truetype(FONT, 30 * P)
    f3 = ImageFont.truetype(FONT, 20 * P)
    for text, font, y, color in [
        ("UNIVERSAL PATCH", f1, 362 * P, WHITE),
        ("for MORE MATERIALS", f2, 406 * P, WHITE),
        ("MODDED BUILDINGS PAY THE SAME PRICE", f3, 456 * P, INGOT),
    ]:
        w = d.textlength(text, font=font)
        d.text(((W - w) / 2, y), text, font=font, fill=color)
    img.resize((512, 512), Image.LANCZOS).save(os.path.join(HERE, "..", "About", "Preview.png"))
    print("wrote About/Preview.png")


if __name__ == "__main__":
    render_badge()
    render_preview()
