"""Makes the Lukez Bunz app icon (the four stream logos as a 2x2 square) and the splash screens.
Run from the repo root:  python3 app/icon/make_icons.py"""
import os
from PIL import Image, ImageDraw, ImageChops

ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
RES = os.path.join(ROOT, 'app', 'android', 'app', 'src', 'main', 'res')
IOS = os.path.join(ROOT, 'app', 'ios', 'App', 'App', 'Assets.xcassets')
# stream colour, logo, logo colour - the same as the app's run chips
TILES = [('#ff4d3d', 'garbage.png', '#ffffff'), ('#ffd21f', 'recycle.png', '#000000'),
         ('#2fd16a', 'fogo.png', '#000000'), ('#3b82f6', 'litter.png', '#ffffff')]

def glyph(name, colour, size):
    im = Image.open(os.path.join(ROOT, name)).convert('RGBA')
    im = im.crop(im.getbbox())
    im.thumbnail((size, size), Image.LANCZOS)
    out = Image.new('RGBA', im.size, colour)
    out.putalpha(im.getchannel('A'))
    return out

def grid(N, line, inset, logo):
    """N px square: four coloured squares split by a black cross. Each logo sits `inset` (0..1) of the way
    from its square's centre toward the middle of the icon, so a round launcher mask doesn't clip it."""
    img = Image.new('RGBA', (N, N), '#000000')
    d = ImageDraw.Draw(img)
    h = N // 2
    for i, (bg, _, _) in enumerate(TILES):
        x0, y0 = (i % 2) * h, (i // 2) * h
        d.rectangle([x0 + (line // 2 if i % 2 else 0), y0 + (line // 2 if i // 2 else 0),
                     x0 + h - (0 if i % 2 else line // 2) - 1, y0 + h - (0 if i // 2 else line // 2) - 1], fill=bg)
    for i, (_, f, fg) in enumerate(TILES):
        g = glyph(f, fg, logo)
        cx = (N / 4 if i % 2 == 0 else 3 * N / 4); cy = (N / 4 if i // 2 == 0 else 3 * N / 4)
        cx += (h - cx) * inset; cy += (h - cy) * inset
        img.alpha_composite(g, (int(cx - g.width / 2), int(cy - g.height / 2)))
    return img

def rounded(img, r):
    m = Image.new('L', img.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, img.width - 1, img.height - 1], r, fill=255)
    out = img.copy(); out.putalpha(ImageChops.multiply(img.getchannel('A'), m)); return out

def circle(img):
    m = Image.new('L', img.size, 0); ImageDraw.Draw(m).ellipse([0, 0, img.width - 1, img.height - 1], fill=255)
    out = img.copy(); out.putalpha(m); return out

def tiles(N, frac, gap, logo, rad):
    """N px square on black: four separate rounded squares (stream colour + logo) in a 2x2, together `frac` of N
    wide, `gap` px apart - space between them and all round them."""
    img = Image.new('RGBA', (N, N), '#000000')
    total = int(N * frac); t = (total - gap) // 2; x0 = (N - total) // 2
    for i, (bg, f, fg) in enumerate(TILES):
        x = x0 + (i % 2) * (t + gap); y = x0 + (i // 2) * (t + gap)
        sq = Image.new('RGBA', (t, t), bg)
        g = glyph(f, fg, int(t * logo))
        sq.alpha_composite(g, ((t - g.width) // 2, (t - g.height) // 2))
        img.alpha_composite(rounded(sq, rad), (x, y))
    return img

# Android adaptive icon: the launcher shows only the middle 72 of the 108 dp and cuts its own shape from that, so the
# squares take up about the middle 50 dp with black space between them and round them
fg = tiles(1296, 0.47, 48, 0.62, 56)
# legacy square / round icons (old launchers) and iOS: the same squares, a little bigger as nothing is cut off
sq = tiles(1024, 0.80, 40, 0.62, 52)
rd = tiles(1024, 0.66, 34, 0.62, 44)
DPI = {'mdpi': 1, 'hdpi': 1.5, 'xhdpi': 2, 'xxhdpi': 3, 'xxxhdpi': 4}
for k, sc in DPI.items():
    d = os.path.join(RES, 'mipmap-' + k)
    fg.resize((int(108 * sc),) * 2, Image.LANCZOS).save(os.path.join(d, 'ic_launcher_foreground.png'))
    rounded(sq, 150).resize((int(48 * sc),) * 2, Image.LANCZOS).save(os.path.join(d, 'ic_launcher.png'))
    circle(rd).resize((int(48 * sc),) * 2, Image.LANCZOS).save(os.path.join(d, 'ic_launcher_round.png'))

# iOS: one 1024 square, no transparency (iOS rounds the corners itself)
sq.convert('RGB').save(os.path.join(IOS, 'AppIcon.appiconset', 'AppIcon-512@2x.png'))

# splash: black with the icon in the middle
def splash(w, h, frac=0.42):
    s = Image.new('RGB', (w, h), '#000000')
    n = int(min(w, h) * frac)
    s.paste(rounded(sq, 150).resize((n, n), Image.LANCZOS), ((w - n) // 2, (h - n) // 2), rounded(sq, 150).resize((n, n), Image.LANCZOS))
    return s
for dn in os.listdir(RES):
    p = os.path.join(RES, dn, 'splash.png')
    if dn.startswith('drawable') and os.path.exists(p):
        w, h = Image.open(p).size
        splash(w, h).save(p)
for f in os.listdir(os.path.join(IOS, 'Splash.imageset')):
    if f.endswith('.png'):
        splash(2732, 2732, 0.22).save(os.path.join(IOS, 'Splash.imageset', f))
print('icons done')
