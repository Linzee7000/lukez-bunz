"""Compare run boundaries with the route maps (PDF): place each PDF page's route lines on the map by fitting
them to that run's houses, then measure how much of the route lies inside each boundary."""
import csv, json, math, re, subprocess, sys, os, glob
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial import cKDTree
from scipy.optimize import minimize
from shapely.geometry import Polygon, Point, MultiPolygon
from shapely.ops import unary_union
from shapely import prepared

S = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'work'); os.makedirs(S + '/pdf/svg', exist_ok=True)   # master.csv, routes-m.json, compare-results.json and pdf/svg/ live here
DL = os.path.expanduser('~/Downloads')
PDFS = ['1.1 RECYCLE - Monday Week A - MAY22.pdf', '2.1 RECYCLE - Tuesday Week A - APR22.pdf',
        '2.2 RECYCLE - Tuesday Week B - MAR22.pdf', '4.2 RECYCLE - Thursday Week B - 2025.pdf']
ROUTE_COL = {'green': (0.0, 68.99, 31.4), 'orange': (100.0, 75.3, 0.0), 'purple': (50.2, 0.0, 50.2)}
LAT0, LNG0 = -38.30, 144.95
KX = 111320 * math.cos(math.radians(LAT0)); KY = 110540.0
def to_m(lat, lng): return ((lng - LNG0) * KX, (lat - LAT0) * KY)

# ---------- houses per run ----------
houses = {}
with open(f'{S}/master.csv', newline='', encoding='utf8') as f:
    r = csv.DictReader(f)
    for row in r:
        run = (row.get('Solo Recycling Run') or '').strip()
        if not run: continue
        try: lat, lng = float(row['Lat']), float(row['Lng'])
        except Exception: continue
        houses.setdefault((row['Solo Collection Day'].strip(), row['Solo Week Cycle'].strip().upper(), run), []).append(to_m(lat, lng))
print('run groups with recycling houses:', len(houses), file=sys.stderr)

# ---------- boundaries ----------
def load_boundaries(path_or_json):
    d = json.loads(path_or_json) if path_or_json.lstrip().startswith('{') else json.load(open(path_or_json))
    return d
NEW = load_boundaries('/Users/bigsms/Projects/binz/data/run-boundaries.json')
OLD = load_boundaries(subprocess.run(['git', '-C', '/Users/bigsms/Projects/binz', 'show', '5d2c3bc:data/run-boundaries.json'], capture_output=True, text=True).stdout)

def geom_for(bd, day, week, run):
    key = f'Recycling#{day}#{week}#{run}'
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

# ---------- PDF -> route polylines (page coordinates) ----------
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
    out, cur, i, start = [], None, 0, None
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
            flush(); i += 0
            cmd = None
        else:
            i += 1
    flush()
    return out
def page_routes(pdf, page):
    svg = f'{S}/pdf/svg/{abs(hash(pdf)) % 10**6}_{page}.svg'
    if not os.path.exists(svg):
        subprocess.run(['pdftocairo', '-svg', '-f', str(page), '-l', str(page), os.path.join(DL, pdf), svg], check=True)
    root = ET.parse(svg).getroot()
    lines = {'green': [], 'orange': [], 'purple': []}
    def walk(el, m):
        tag = el.tag.split('}')[-1]
        m2 = mul(m, parse_matrix(el.get('transform')))
        if tag == 'path':
            cn = color_name(el.get('stroke'))
            if cn and el.get('d'):
                for sub in parse_d(el.get('d')):
                    lines[cn].append([apply(m2, x, y) for x, y in sub])
        for ch in el: walk(ch, m2)
    walk(root, (1, 0, 0, 1, 0, 0))
    return lines
def densify(polys, step=2.0):
    pts = []
    for pl in polys:
        for (x0, y0), (x1, y1) in zip(pl[:-1], pl[1:]):
            L = math.hypot(x1 - x0, y1 - y0); n = max(1, int(L / step))
            for k in range(n): pts.append((x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n))
        pts.append(pl[-1])
    return np.array(pts)

# ---------- registration ----------
def fit(route_pts, H):
    """page (px,py) -> metres.  X = s*(cos*u - sin*v)+tx ; Y = s*(sin*u + cos*v)+ty ; u=px, v=-py.
    Coarse: FFT correlation of the route raster with a blurred house-density raster over rotation x scale.
    Fine: Nelder-Mead on the trimmed mean house-to-route distance."""
    from scipy.signal import fftconvolve
    from scipy.ndimage import gaussian_filter
    tree = cKDTree(route_pts)
    C = 20.0
    lo = np.percentile(H, 1, axis=0) - 300; hi = np.percentile(H, 99, axis=0) + 300
    keep = (H[:, 0] >= lo[0]) & (H[:, 0] <= hi[0]) & (H[:, 1] >= lo[1]) & (H[:, 1] <= hi[1])
    Hc = H[keep]
    hx0, hy0 = lo[0], lo[1]
    nx, ny = int((hi[0] - lo[0]) / C) + 1, int((hi[1] - lo[1]) / C) + 1
    G = np.zeros((ny, nx))
    ix = ((Hc[:, 0] - hx0) / C).astype(int); iy = ((Hc[:, 1] - hy0) / C).astype(int)
    np.add.at(G, (iy, ix), 1.0)
    G = gaussian_filter(G, 1.5); G /= (G.max() or 1)
    cands = []
    for k in range(4):
        th = k * math.pi / 2; c, sn = math.cos(th), math.sin(th)
        u = route_pts[:, 0]; v = -route_pts[:, 1]
        ru, rv = c * u - sn * v, sn * u + c * v
        for s in np.geomspace(1.5, 16, 34):
            X, Y = s * ru, s * rv
            xmin, ymin = X.min(), Y.min()
            cx = ((X - xmin) / C).astype(int); cy = ((Y - ymin) / C).astype(int)
            R = np.zeros((cy.max() + 1, cx.max() + 1)); R[cy, cx] = 1.0
            if R.shape[0] > 3 * ny or R.shape[1] > 3 * nx: continue
            conv = fftconvolve(G, R[::-1, ::-1], mode='full')
            i, j = np.unravel_index(np.argmax(conv), conv.shape)
            score = conv[i, j] / R.sum()
            roff, coff = i - (R.shape[0] - 1), j - (R.shape[1] - 1)
            tx = hx0 + coff * C - xmin; ty = hy0 + roff * C - ymin
            cands.append((score, [s, th, tx, ty]))
    cands.sort(key=lambda t: -t[0])
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
    for score, p0 in cands[:6]:
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
    for name, polys in routes_m.items():
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

results = []
out_geo = {}
only = sys.argv[1] if len(sys.argv) > 1 else None
for pdf in PDFS:
    n = int(re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', os.path.join(DL, pdf)], capture_output=True, text=True).stdout).group(1))
    for page in range(1, n + 1):
        txt = subprocess.run(['pdftotext', '-f', str(page), '-l', str(page), os.path.join(DL, pdf), '-'], capture_output=True, text=True).stdout
        m = re.search(r'(Monday|Tuesday|Wednesday|Thursday|Friday) Run (\d+) Recycle W([AB])', txt)
        if not m: continue
        day, run, week = m.group(1), m.group(2), m.group(3)
        tag = f'{pdf.split()[0]} p{page} {day[:3]} {week} {run}'
        if only and only not in tag: continue
        H = np.array(houses.get((day, week, run), []))
        lines = page_routes(pdf, page)
        allpolys = lines['green'] + lines['orange'] + lines['purple']
        if len(H) < 20 or not allpolys:
            results.append(dict(tag=tag, note=f'skipped ({len(H)} houses, {len(allpolys)} route lines)')); print(tag, 'skipped', len(H), len(allpolys), flush=True); continue
        pts = densify(allpolys)
        f, p = fit(pts, H)
        rm = transform_routes(lines, p)
        gn = measure(rm, geom_for(NEW, day, week, run)); go = measure(rm, geom_for(OLD, day, week, run))
        rec = dict(tag=tag, houses=len(H), fit_m=round(float(f), 1), scale_m_per_pt=round(float(p[0]), 2), new=gn, old=go)
        results.append(rec); out_geo[tag] = rm
        fmt = lambda g: 'n/a' if not g else f"in {g['inside']*100:4.0f}%  ≤15m {g['w15']*100:4.0f}%  ≤30m {g['w30']*100:4.0f}%  far {g['far_m']:5.0f}m"
        print(f"{tag:22s} fit {f:5.1f}m ({len(H)} houses, {rec['scale_m_per_pt']} m/pt) {gn['km'] if gn else 0:.1f}km | NEW {fmt(gn)} | OLD {fmt(go)}", flush=True)
json.dump(results, open(f'{S}/compare-results.json', 'w'), indent=1)
json.dump({k: {n: [[(x / KX + 0, y / KY) for x, y in pl] for pl in polys] for n, polys in v.items()} for k, v in out_geo.items()}, open(f'{S}/routes-m.json', 'w'))
