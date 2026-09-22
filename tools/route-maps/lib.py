"""Shared geometry helpers for reading the driver route-map PDFs. See README.md."""
import csv, json, math, re, subprocess, os
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial import cKDTree
from scipy.optimize import minimize
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from shapely import prepared

HERE = os.path.dirname(os.path.abspath(__file__))
S = os.path.join(HERE, 'work'); os.makedirs(S + '/pdf/svg', exist_ok=True)   # master.csv and per-run outputs live here
DL = os.environ.get('ROUTEMAP_PDF_DIR', os.path.abspath(os.path.join(HERE, '..', '..')))   # folder with the route-map PDFs (default: the repo root)
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
ROUTE_COL = {'green': (0.0, 68.99, 31.4), 'orange': (100.0, 75.3, 0.0), 'purple': (50.2, 0.0, 50.2)}
LAT0, LNG0 = -38.30, 144.95
KX = 111320 * math.cos(math.radians(LAT0)); KY = 110540.0
def to_m(lat, lng): return ((lng - LNG0) * KX, (lat - LAT0) * KY)
def to_ll(x, y): return [round(LAT0 + y / KY, 5), round(LNG0 + x / KX, 5)]

# ---------- one row per stream: how its houses/runs/boundary keys are shaped ----------
class Stream:
    def __init__(self, name, csv_field, has_week, title_word):
        self.name = name; self.csv_field = csv_field; self.has_week = has_week; self.title_word = title_word
    def key(self, day, week, run):
        return f'{self.name}#{day}#{week}#{run}' if self.has_week else f'{self.name}#{day}#{run}'

STREAMS = {
    'REC': Stream('Recycling', 'Solo Recycling Run', True, 'Recycle'),
    'ORG': Stream('FOGO', 'Solo FOGO Run', True, 'Organics'),
    'GAR': Stream('Garbage', 'Solo Garbage Run', False, None),
}

def load_houses(csv_field, has_week):
    """{(day, week, run): [(x,y), ...]}. week is '' for a stream with no week (Garbage)."""
    houses = {}
    with open(f'{S}/master.csv', newline='', encoding='utf8') as f:
        for row in csv.DictReader(f):
            run = (row.get(csv_field) or '').strip()
            if not run: continue
            try: lat, lng = float(row['Lat']), float(row['Lng'])
            except Exception: continue
            week = row['Solo Week Cycle'].strip().upper() if has_week else ''
            houses.setdefault((row['Solo Collection Day'].strip(), week, run), []).append(to_m(lat, lng))
    return houses

def load_boundaries(path_or_json):
    return json.loads(path_or_json) if path_or_json.lstrip().startswith('{') else json.load(open(path_or_json))

def current_and_prior_boundaries():
    """The live data/run-boundaries.json, and the version from before any of this route-map work (for A/B comparison)."""
    cur = load_boundaries(os.path.join(REPO, 'data', 'run-boundaries.json'))
    prior = load_boundaries(subprocess.run(['git', '-C', REPO, 'show', '5d2c3bc:data/run-boundaries.json'], capture_output=True, text=True).stdout)
    return cur, prior

def geom_for(bd, key):
    rings = []
    if key in bd['boundaries']: rings.append(bd['boundaries'][key]); rings += bd.get('extras', {}).get(key, [])
    else:
        alias = bd.get('aliases', {}).get(key)
        if alias and alias in bd['boundaries']: rings.append(bd['boundaries'][alias]); rings += bd.get('extras', {}).get(alias, [])
    polys = []
    for ring in rings:
        pts = [to_m(p[0], p[1]) for p in ring]
        if len(pts) >= 3:
            pg = Polygon(pts)
            if not pg.is_valid: pg = pg.buffer(0)
            if not pg.is_empty: polys.append(pg)
    return unary_union(polys) if polys else None

# ---------- PDF page -> route polylines, in the page's own point coordinates ----------
def parse_matrix(t):
    m = re.match(r'matrix\(([^)]*)\)', t or '')
    if not m: return (1, 0, 0, 1, 0, 0)
    a, b, c, d, e, f = [float(x) for x in m.group(1).replace(',', ' ').split()]
    return (a, b, c, d, e, f)
def mul(m1, m2):  # apply m2 first, then m1
    a1, b1, c1, d1, e1, f1 = m1; a2, b2, c2, d2, e2, f2 = m2
    return (a1*a2 + c1*b2, b1*a2 + d1*b2, a1*c2 + c1*d2, b1*c2 + d1*d2, a1*e2 + c1*f2 + e1, b1*e2 + d1*f2 + f1)
def apply(m, x, y): return (m[0]*x + m[2]*y + m[4], m[1]*x + m[3]*y + m[5])
def color_name(s):
    mm = re.match(r'rgb\(([\d.]+)%,\s*([\d.]+)%,\s*([\d.]+)%\)', s or '')
    if not mm: return None
    v = tuple(float(x) for x in mm.groups())
    for n, c in ROUTE_COL.items():
        if all(abs(v[i] - c[i]) < 1.5 for i in range(3)): return n
    return None
def parse_d(d):
    toks = re.findall(r'[MLCZHVmlczhv]|-?\d*\.?\d+(?:e-?\d+)?', d)
    out, i = [], 0
    sub = []
    def flush():
        nonlocal sub
        if len(sub) > 1: out.append(sub)
        sub = []
    cmd = None
    while i < len(toks):
        t = toks[i]
        if re.match(r'[A-Za-z]', t): cmd = t; i += 1
        if cmd == 'M':
            flush(); x, y = float(toks[i]), float(toks[i+1]); i += 2; sub = [(x, y)]; cmd = 'L'
        elif cmd == 'L':
            x, y = float(toks[i]), float(toks[i+1]); i += 2; sub.append((x, y))
        elif cmd == 'C':
            x1, y1, x2, y2, x3, y3 = [float(v) for v in toks[i:i+6]]; i += 6
            x0, y0 = sub[-1]
            for k in range(1, 7):
                u = k / 6; a = (1-u)**3; b = 3*u*(1-u)**2; c = 3*u*u*(1-u); e = u**3
                sub.append((a*x0 + b*x1 + c*x2 + e*x3, a*y0 + b*y1 + c*y2 + e*y3))
        elif cmd in ('Z', 'z'):
            if sub: sub.append(sub[0])
            flush(); cmd = None
        else:
            i += 1
    flush()
    return out
def page_routes(pdf, page):
    svg = f"{S}/pdf/svg/{re.sub(r'[^A-Za-z0-9]+', '_', pdf)}_{page}.svg"
    if not os.path.exists(svg):
        subprocess.run(['pdftocairo', '-svg', '-f', str(page), '-l', str(page), os.path.join(DL, pdf), svg], check=True)
    root = ET.parse(svg).getroot()
    lines = {'green': [], 'orange': [], 'purple': []}
    def walk(el, m):
        m2 = mul(m, parse_matrix(el.get('transform')))
        if el.tag.split('}')[-1] == 'path':
            cn = color_name(el.get('stroke'))
            if cn and el.get('d'):
                for sub in parse_d(el.get('d')):
                    lines[cn].append([apply(m2, x, y) for x, y in sub])
        for ch in el: walk(ch, m2)
    walk(root, (1, 0, 0, 1, 0, 0))
    return lines
def page_count(pdf):
    out = subprocess.run(['pdfinfo', os.path.join(DL, pdf)], capture_output=True, text=True).stdout
    return int(re.search(r'Pages:\s+(\d+)', out).group(1))
def densify(polys, step=2.0):
    pts = []
    for pl in polys:
        for (x0, y0), (x1, y1) in zip(pl[:-1], pl[1:]):
            L = math.hypot(x1 - x0, y1 - y0); n = max(1, int(L / step))
            for k in range(n): pts.append((x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n))
        pts.append(pl[-1])
    return np.array(pts)

# ---------- registration: fit a page's route lines onto a candidate house cluster ----------
def _density_grid(H, C=20.0):
    from scipy.ndimage import gaussian_filter
    lo = np.percentile(H, 1, axis=0) - 300; hi = np.percentile(H, 99, axis=0) + 300
    keep = (H[:, 0] >= lo[0]) & (H[:, 0] <= hi[0]) & (H[:, 1] >= lo[1]) & (H[:, 1] <= hi[1])
    Hc = H[keep]
    hx0, hy0 = lo[0], lo[1]
    nx, ny = int((hi[0] - lo[0]) / C) + 1, int((hi[1] - lo[1]) / C) + 1
    G = np.zeros((ny, nx))
    ix = ((Hc[:, 0] - hx0) / C).astype(int); iy = ((Hc[:, 1] - hy0) / C).astype(int)
    np.add.at(G, (iy, ix), 1.0)
    G = gaussian_filter(G, 1.5); G /= (G.max() or 1)
    return G, hx0, hy0, nx, ny

def coarse_candidates(route_pts, H, n_scales=34, top_n=999, normalize=False):
    """The FFT-correlation half of fit() on its own: how well would `route_pts` (a page's route, in its own
    point coordinates) line up against this house cluster, at the best rotation/scale/offset? Returns a list
    of (score, [s, th, tx, ty]) sorted best-first - higher score is a better coarse match. Used to RANK many
    candidate house clusters cheaply (skips the expensive per-candidate Nelder-Mead refinement in fit());
    call fit() afterwards on just the winner to get a precise registration.

    normalize=True divides by the local density energy under the route's footprint (normalised cross-
    correlation), not just the raw route pixel count - the raw score is biased toward whichever candidate
    simply has the most/densest houses, regardless of whether its shape actually matches; set this when
    ranking BETWEEN candidates (e.g. identifying which run a page belongs to). Leave it off (as fit() does)
    when only refining a registration against one already-chosen candidate, where that bias doesn't matter."""
    from scipy.signal import fftconvolve
    C = 20.0
    G, hx0, hy0, nx, ny = _density_grid(H, C)
    G2 = G * G
    cands = []
    for k in range(4):
        th = k * math.pi / 2; c, sn = math.cos(th), math.sin(th)
        u = route_pts[:, 0]; v = -route_pts[:, 1]
        ru, rv = c * u - sn * v, sn * u + c * v
        for s in np.geomspace(1.5, 16, n_scales):
            X, Y = s * ru, s * rv
            xmin, ymin = X.min(), Y.min()
            cx = ((X - xmin) / C).astype(int); cy = ((Y - ymin) / C).astype(int)
            R = np.zeros((cy.max() + 1, cx.max() + 1)); R[cy, cx] = 1.0
            if R.shape[0] > 3 * ny or R.shape[1] > 3 * nx: continue
            conv = fftconvolve(G, R[::-1, ::-1], mode='full')
            if normalize:
                energy = fftconvolve(G2, np.ones_like(R), mode='full')
                score_map = conv / np.sqrt(energy + 1e-9)
                i, j = np.unravel_index(np.argmax(score_map), score_map.shape)
                score = float(score_map[i, j])
            else:
                i, j = np.unravel_index(np.argmax(conv), conv.shape)
                score = conv[i, j] / R.sum()
            roff, coff = i - (R.shape[0] - 1), j - (R.shape[1] - 1)
            tx = hx0 + coff * C - xmin; ty = hy0 + roff * C - ymin
            cands.append((score, [s, th, tx, ty]))
    cands.sort(key=lambda t: -t[0])
    return cands[:top_n]

def fit(route_pts, H, top_n=6, _cands=None):
    """page (px,py) -> metres.  X = s*(cos*u - sin*v)+tx ; Y = s*(sin*u + cos*v)+ty ; u=px, v=-py.
    Coarse: FFT correlation of the route raster with a blurred house-density raster over rotation x scale.
    Fine: Nelder-Mead on the trimmed mean house-to-route distance. Returns (cost, params) - lower cost is a better fit.
    Pass `_cands` (from coarse_candidates()) to skip redoing the coarse search."""
    tree = cKDTree(route_pts)
    cands = _cands if _cands is not None else coarse_candidates(route_pts, H)
    Hn = H[np.random.default_rng(1).permutation(len(H))[:1500]]
    def to_page(p, Hm):
        s, th, tx, ty = p
        c, sn = math.cos(th), math.sin(th)
        X, Y = (Hm[:, 0] - tx) / s, (Hm[:, 1] - ty) / s
        u = c * X + sn * Y; v = -sn * X + c * Y
        return np.column_stack([u, -v])
    def cost(p):
        if p[0] <= 0: return 1e9
        d, _ = tree.query(to_page(p, Hn)); d = np.sort(d * p[0]); k = int(len(d) * 0.6)
        return d[:k].mean()
    best = None
    for score, p0 in cands[:top_n]:
        r = minimize(cost, p0, method='Nelder-Mead', options={'xatol': 0.01, 'fatol': 0.01, 'maxiter': 600})
        r2 = minimize(cost, r.x, method='Nelder-Mead', options={'xatol': 0.005, 'fatol': 0.005, 'maxiter': 600})
        if best is None or r2.fun < best[0]: best = (r2.fun, r2.x)
    return best

def transform_routes(lines, p):
    s, th, tx, ty = p
    c, sn = math.cos(th), math.sin(th)
    out = {}
    for name, polys in lines.items():
        res = []
        for pl in polys:
            pts = []
            for px, py in pl:
                u, v = px, -py
                pts.append((s * (c * u - sn * v) + tx, s * (sn * u + c * v) + ty))
            res.append(pts)
        out[name] = res
    return out

def measure(routes_m, geom):
    """fractions of route length inside geom / within 15 m / within 30 m; length outside by >30 m."""
    if geom is None: return None
    pg = prepared.prep(geom)
    tot = ins = w15 = w30 = 0.0; far = 0.0
    for polys in routes_m.values():
        for pl in polys:
            for (x0, y0), (x1, y1) in zip(pl[:-1], pl[1:]):
                L = math.hypot(x1 - x0, y1 - y0)
                if L < 1e-6: continue
                n = max(1, int(L / 5)); seg = L / n
                for k in range(n):
                    pt = Point(x0 + (x1 - x0) * (k + .5) / n, y0 + (y1 - y0) * (k + .5) / n)
                    tot += seg
                    if pg.contains(pt): ins += seg; w15 += seg; w30 += seg
                    else:
                        d = geom.distance(pt)
                        if d <= 15: w15 += seg; w30 += seg
                        elif d <= 30: w30 += seg
                        else: far += seg
    return dict(km=tot / 1000, inside=ins / tot, w15=w15 / tot, w30=w30 / tot, far_m=far)

def routes_to_ll(routes_m):
    """metres -> the (dlng, dlat) offset pairs the *-m.json files store on disk (see to_ll/KX/KY)."""
    return {n: [[(x / KX, y / KY) for x, y in pl] for pl in polys] for n, polys in routes_m.items()}

def street_for(x, y, tree, addrs):
    """nearest address's street name, or '' if the nearest house is more than 60 m away."""
    d, i = tree.query([x, y])
    if d >= 60: return ''
    a = addrs[i].split(',')[0]
    a = re.sub(r'^(Unit|Shop|Lot|Suite)\s+[\w/-]+/', '', a, flags=re.I)
    a = re.sub(r'^[\w/-]*\d[\w/-]*\s+', '', a)
    return a.strip().title()

def house_tree():
    pts, addrs = [], []
    with open(f'{S}/master.csv', newline='', encoding='utf8') as f:
        for row in csv.DictReader(f):
            try: lat, lng = float(row['Lat']), float(row['Lng'])
            except Exception: continue
            pts.append(to_m(lat, lng)); addrs.append(row['Address'])
    return cKDTree(np.array(pts)), addrs

def load_results(pattern_prefix):
    """Merge every work/{pattern_prefix}*.json written by compare.py / identify_garbage.py."""
    import glob
    routes, results = {}, {}
    for f in sorted(glob.glob(f'{S}/routes-m-{pattern_prefix}*.json')): routes.update(json.load(open(f)))
    for f in sorted(glob.glob(f'{S}/compare-results-{pattern_prefix}*.json')):
        for r in json.load(open(f)):
            if 'fit_m' in r: results[r['tag']] = r
    return routes, results

# ---------- drop stray legend/key artifacts picked up by page_routes() ----------
def drop_stray_pieces(routes_m, join_m=250.0, keep_near_km=0.8):
    """A page's real route can be in a few genuinely separate pieces (e.g. a pocket reached by an
    unmarked road), but a legend colour swatch (the small "Reverse In" / "Drive In" key near the page
    footer) is a handful of points forming its own tiny closed shape, nowhere near the rest of the page's
    route. Group polylines that come within join_m of each other; keep the group with the most route
    length, plus any other group within keep_near_km of it; drop the rest. routes_m: {colour: [[(x,y),...],...]}
    in real metres. Returns (kept, dropped_count, dropped_length_m)."""
    items = []  # (colour, polyline)
    for colour, polys in routes_m.items():
        for pl in polys:
            if len(pl) >= 2: items.append((colour, pl))
    n = len(items)
    if n <= 1: return routes_m, 0, 0.0
    boxes = []
    for _, pl in items:
        xs = [p[0] for p in pl]; ys = [p[1] for p in pl]
        boxes.append((min(xs) - join_m, min(ys) - join_m, max(xs) + join_m, max(ys) + join_m))
    def seg_min_dist(a, b):
        best = 1e18
        for (ax, ay) in a:
            for (bx, by) in b:
                d = (ax - bx) ** 2 + (ay - by) ** 2
                if d < best: best = d
        return best ** 0.5
    parent = list(range(n))
    def find(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj: parent[ri] = rj
    for i in range(n):
        for j in range(i + 1, n):
            bi, bj = boxes[i], boxes[j]
            if bi[2] < bj[0] or bj[2] < bi[0] or bi[3] < bj[1] or bj[3] < bi[1]: continue  # bounding boxes miss - can't be within join_m
            if seg_min_dist(items[i][1], items[j][1]) <= join_m: union(i, j)
    groups = {}
    for i in range(n): groups.setdefault(find(i), []).append(i)
    def poly_len(pl): return sum(math.hypot(pl[k+1][0]-pl[k][0], pl[k+1][1]-pl[k][1]) for k in range(len(pl)-1))
    lengths = {g: sum(poly_len(items[i][1]) for i in idx) for g, idx in groups.items()}
    main = max(lengths, key=lengths.get)
    main_pts = [p for i in groups[main] for p in items[i][1]]
    def group_near_main(idx):
        return any(seg_min_dist(items[i][1], main_pts) <= keep_near_km * 1000 for i in idx)
    kept, dropped_n, dropped_len = {c: [] for c in routes_m}, 0, 0.0
    for g, idx in groups.items():
        keep = (g == main) or group_near_main(idx)
        for i in idx:
            colour, pl = items[i]
            if keep: kept[colour].append(pl)
            else: dropped_n += 1; dropped_len += poly_len(pl)
    return kept, dropped_n, dropped_len
