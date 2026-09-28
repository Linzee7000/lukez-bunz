"""Read the original Publisher (.pub) route maps, page by page.

The PDFs exported from these lose two things: the Garbage PDFs' text comes out garbled, and there's no way to
tell which street-map picture a page is drawn over. The .pub files (dumped with libmspub's `pub2raw`,
`brew install libmspub`) have both:
  - the title as plain text ("Monday Run 201 Garbage")
  - the route lines (green = driven, purple = reverse in, orange = drive in / reverse out), in inches
  - every picture on the page, with the frame it's stretched into (and its rotation)
Several runs are often drawn over the SAME street-map picture in the same frame. Their route lines then share
one page -> ground transform, so a page that can't be placed by its own shape (a part-run or detail page) can
borrow the transform of a page that could. See place_from_pub.py.

    python pub_pages.py "<file.pub>"      # print a summary of every page
"""
import hashlib, os, re, subprocess, sys

COL = {'#00b050': 'green', '#7030a0': 'purple', '#ffc000': 'orange'}
PT_PER_IN = 72.0

def raw(pub):
    cache = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'work', 'pub', re.sub(r'[^A-Za-z0-9]+', '_', os.path.basename(pub)) + '.raw')
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    if not os.path.exists(cache) or os.path.getmtime(cache) < os.path.getmtime(pub):
        with open(cache, 'w') as f: subprocess.run(['pub2raw', pub], stdout=f, stderr=subprocess.DEVNULL, check=False)
    return cache

_num = re.compile(r'svg:x: (-?[\d.]+)in, svg:y: (-?[\d.]+)in')
def _pts(s): return [(float(x) * PT_PER_IN, float(y) * PT_PER_IN) for x, y in _num.findall(s)]

def pages(pub):
    """[{title, texts, lines:{green,purple,orange}, images:[{hash, w, h, frame:[(x,y)...], rotate}]}] - coordinates in pt."""
    out, cur, style = [], None, {}
    for line in open(raw(pub), errors='replace'):
        s = line.strip()
        if s.startswith('startPage'):
            cur = dict(title='', texts=[], lines={'green': [], 'purple': [], 'orange': []}, images=[]); out.append(cur); style = {}
        elif cur is None: continue
        elif s.startswith('insertText ('):
            t = s[len('insertText ('):-1].strip()
            if t: cur['texts'].append(t)
            m = re.search(r'(Monday|Tuesday|Wednesday|Thursday|Friday) Run (\d{3})', t)
            if m and not cur['title']: cur['title'] = t
        elif s.startswith('setStyle('):
            style = {}
            m = re.search(r'svg:stroke-color: (#[0-9a-fA-F]{6})', s); style['stroke'] = m.group(1).lower() if m else None
            m = re.search(r'draw:fill-image: ([A-Za-z0-9+/=]+)', s)
            if m and 'draw:fill: bitmap' in s:
                b = m.group(1); style['img'] = hashlib.md5(b.encode()).hexdigest()[:10]
                style['imgsize'] = len(b) * 3 // 4
                style['imgdim'] = _png_dim(b) if b.startswith('iVBOR') else None
                r = re.search(r'librevenge:rotate: (-?\d+)', s); style['rot'] = int(r.group(1)) if r else 0
        elif s.startswith('drawPath') or s.startswith('drawPolyline') or s.startswith('drawPolygon'):
            pts = _pts(s)
            col = COL.get(style.get('stroke') or '')
            if col and len(pts) > 1 and not s.startswith('drawPolygon'): cur['lines'][col].append(pts)
            if style.get('img') and s.startswith('drawPolygon') and style.get('imgsize', 0) > 200000:
                cur['images'].append(dict(hash=style['img'], size=style['imgsize'], dim=style.get('imgdim'), rot=style.get('rot', 0), frame=pts[:4]))
                style = dict(style, img=None)
    return out

def _png_dim(b64):
    import base64, struct
    h = base64.b64decode(b64[:48])
    return struct.unpack('>II', h[16:24]) if h[:8] == b'\x89PNG\r\n\x1a\n' else None

if __name__ == '__main__':
    for i, p in enumerate(pages(sys.argv[1]), 1):
        n = {k: len(v) for k, v in p['lines'].items()}
        imgs = [(im['hash'], im['dim'], im['rot'], [tuple(round(v) for v in q) for q in im['frame'][:1]]) for im in p['images']]
        print(i, p['title'] or '(no title)', n, imgs)
