"""Place Garbage route-map pages that couldn't be placed by their route's shape, by matching their street-map
PICTURE against pages that could.

Every page is drawn over a street-map picture, and the PDF keeps exactly where that picture sits on the page
(pdftocairo's SVG: the <use> transform of the picture). Many pages - part-run pages, detail pages, runs
sharing an area - are cut from the same original street map, so their pictures share identical pixels.
OpenCV finds matching features between two pictures and the similarity transform between them (RANSAC); from
a placed page's picture -> ground transform that gives the unplaced page's picture -> ground, and so its
page -> ground, and its route lines go on the map exactly where the picture says.

A match is only used when many features agree (MIN_INLIERS) and the result is checked the same way a fit is:
the route must run past the run's houses (route -> nearest house, trimmed mean <= MAX_ROUTE_M).

    python picture_place.py --check     # re-place pages that are ALREADY placed from each other's pictures: accuracy
    python picture_place.py             # place the rest -> work/compare-results-GAR-P*.json, work/routes-m-GAR-P*.json
"""
import base64, glob, json, math, os, re, sys
import numpy as np, cv2
from scipy.spatial import cKDTree
from lib import S, KX, KY, page_routes, densify, current_and_prior_boundaries, geom_for, measure, routes_to_ll, drop_stray_pieces
from identify_garbage import find_pdfs, load_houses_by_run
from garbage_font import read_title, page_texts

DOWN = 4              # pictures are ~6000 px; match at a quarter size
MIN_INLIERS = 60
MAX_ROUTE_M = 15.0

def svg_path(pdf, page):
    p = f"{S}/pdf/svg/{re.sub(r'[^A-Za-z0-9]+', '_', pdf)}_{page}.svg"
    if not os.path.exists(p): page_routes(pdf, page)          # makes the SVG
    return p

_pic = {}
def picture(pdf, page):
    if (pdf, page) not in _pic: _pic[(pdf, page)] = _picture(pdf, page)
    return _pic[(pdf, page)]

def _picture(pdf, page):
    """(grey picture at 1/DOWN size, 3x3 picture-pixel -> page-pt matrix) for the page's street map."""
    t = open(svg_path(pdf, page)).read()
    imgs = {m.group(1): (int(m.group(2)), int(m.group(3)), m.group(4)) for m in
            re.finditer(r'<image id="([^"]+)" x="0" y="0" width="(\d+)" height="(\d+)" xlink:href="data:image/[a-z]+;base64,([^"]+)"', t)}
    best = None
    for m in re.finditer(r'<use xlink:href="#([^"]+)"(?![^>]*filter)[^>]*transform="matrix\(([^)]+)\)"', t):
        sid = m.group(1)
        if sid not in imgs: continue
        w, h, b64 = imgs[sid]
        if w * h < 1_000_000: continue                       # logos, legend swatches
        if best is None or w * h > best[0]: best = (w * h, sid, [float(v) for v in m.group(2).split(',')], b64)
    if not best: return None, None
    _, sid, (a, b, c, d, e, f), b64 = best
    img = cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None or not img.size: return None, None
    k = max(1.0, max(img.shape) / 1600.0)            # match at ~1600 px on the long side (small pictures kept as they are)
    img = cv2.resize(img, (max(1, int(img.shape[1] / k)), max(1, int(img.shape[0] / k))), interpolation=cv2.INTER_AREA)
    M = np.array([[a * k, c * k, e], [b * k, d * k, f], [0, 0, 1.0]])   # matching-size px -> page pt
    return img, M

def ll_to_m(pl): return [(x * KX, y * KY) for x, y in pl]

def page_to_m_from_saved(pdf, page, routes_ll):
    """Recover a placed page's page-pt -> metres similarity from its saved route lines (same vertices, in order)."""
    lines = page_routes(pdf, page); src, dst = [], []
    for col, saved in routes_ll.items():
        inp = list(lines.get(col, [])); j = 0
        for pl in saved:
            while j < len(inp) and len(inp[j]) != len(pl): j += 1
            if j >= len(inp): break
            src += inp[j]; dst += ll_to_m(pl); j += 1
    if len(src) < 4: return None
    A = np.array(src); B = np.array(dst)
    # u = x, v = -y (page y runs down) then similarity: least squares for [a -b; b a] + t
    X = np.column_stack([A[:, 0], -A[:, 1]])
    n = len(X); Mx = np.zeros((2 * n, 4)); y = np.zeros(2 * n)
    Mx[0::2] = np.column_stack([X[:, 0], -X[:, 1], np.ones(n), np.zeros(n)]); y[0::2] = B[:, 0]
    Mx[1::2] = np.column_stack([X[:, 1], X[:, 0], np.zeros(n), np.ones(n)]); y[1::2] = B[:, 1]
    a, b, tx, ty = np.linalg.lstsq(Mx, y, rcond=None)[0]
    T = np.array([[a, b, tx], [b, -a, ty], [0, 0, 1.0]])      # (x, y) -> (a x + b y + tx, b x - a y + ty)
    err = np.sqrt(((apply(T, A) - B) ** 2).sum(1)).mean()
    return T if err < 2.0 else None

def apply(M, pts):
    pts = np.asarray(pts, float); return (M[:2, :2] @ pts.T).T + M[:2, 2]

_sift = cv2.SIFT_create(nfeatures=6000)
_feat = {}
def features(key, img):
    if key not in _feat: _feat[key] = _sift.detectAndCompute(img, None)
    return _feat[key]

def match(ka, ia, kb, ib):
    """3x3 similarity taking picture a px -> picture b px, and the number of agreeing features."""
    ka_, da = features(ka, ia); kb_, db = features(kb, ib)
    if da is None or db is None or len(ka_) < 20 or len(kb_) < 20: return None, 0
    m = cv2.BFMatcher(cv2.NORM_L2).knnMatch(da, db, k=2)
    good = [x[0] for x in m if len(x) == 2 and x[0].distance < 0.72 * x[1].distance]
    if len(good) < 12: return None, len(good)
    P = np.float32([ka_[g.queryIdx].pt for g in good]); Q = np.float32([kb_[g.trainIdx].pt for g in good])
    A, inl = cv2.estimateAffinePartial2D(P, Q, method=cv2.RANSAC, ransacReprojThreshold=4.0, maxIters=5000)
    if A is None: return None, 0
    return np.vstack([A, [0, 0, 1]]), int(inl.sum())

def load_placed():
    """every page already placed (by its route's shape): {(pdf, page): (day, run, page->m)}"""
    placed = {}
    for f in sorted(glob.glob(f'{S}/compare-results-GAR-*.json')):
        if re.search(r'GAR-(P|zpic|zlab)', f): continue
        routes = json.load(open(f.replace('compare-results', 'routes-m')))
        for r in json.load(open(f)):
            if 'fit_m' not in r: continue
            _, day, _, run, rest = r['tag'].split('|'); pdf, pg = rest.rsplit(' p', 1)
            T = page_to_m_from_saved(pdf, int(pg), routes[r['tag']])
            if T is not None: placed[(pdf, int(pg))] = (day, run, T)
    return placed

def place(pdf, page, placed, exclude=None):
    """best placement of one page from the placed pages' pictures -> (page->m, source key, inliers)"""
    img, M = picture(pdf, page)
    if img is None: return None
    best = None
    for key, (day, run, T) in placed.items():
        if key == exclude or key == (pdf, page): continue
        ib, Mb = picture(*key)
        if ib is None: continue
        H, n = match((pdf, page), img, key, ib)
        if H is None or n < MIN_INLIERS: continue
        if best is None or n > best[2]:
            best = (T @ Mb @ H @ np.linalg.inv(M), key, n)
    return best

def route_check(pts_m, Hs):
    d, _ = cKDTree(Hs).query(pts_m); d = np.sort(d); return float(d[: int(len(d) * 0.8)].mean())

def check():
    placed = load_placed(); print(len(placed), 'placed pages with a recovered transform')
    errs = []
    for key, (day, run, T) in list(placed.items()):
        res = place(*key, placed, exclude=key)
        if not res: print(f'  {key}: no picture match'); continue
        T2, src, n = res
        lines = page_routes(*key); pts = densify(lines['green'] + lines['orange'] + lines['purple'])
        e = np.sqrt(((apply(T, pts) - apply(T2, pts)) ** 2).sum(1)).mean(); errs.append(e)
        print(f'  {key[0][:26]} p{key[1]} run {run}: from p{src[1]} of {src[0][:26]} ({n} features) -> {e:.1f} m from its own fit', flush=True)
    if errs: print(f'{len(errs)} checked: median {np.median(errs):.1f} m, within 15 m {sum(e <= 15 for e in errs)}')

_roads = None
def road_dist(T, pts):
    """trimmed mean distance (m) from a placed route to the real roads (OpenStreetMap, work/roads.json)"""
    global _roads
    if _roads is None:
        from lib import to_m
        R = []
        for r in json.load(open(f'{S}/roads.json')):
            P = np.array([to_m(a, b) for a, b in r['pts']])
            for p, q in zip(P[:-1], P[1:]):
                n = max(1, int(np.hypot(*(q - p)) / 4)); R += [p + (q - p) * k / n for k in range(n)]
        _roads = cKDTree(np.array(R))
    d, _ = _roads.query(apply(T, pts)); d = np.sort(d); return float(d[: int(len(d) * 0.8)].mean())

def refine_to_roads(T, pts, iters=30):
    """Nudge a placement onto the real roads (ICP: pull each route point to its nearest road point, best
    similarity transform, repeat; the worst 30% of points are ignored each round)."""
    road_dist(T, pts[:5])                            # makes sure the road tree is loaded
    for _ in range(iters):
        P = apply(T, pts); d, i = _roads.query(P); keep = d <= np.percentile(d, 70)
        Q = _roads.data[i[keep]]; Pk = P[keep]
        mp, Qk_mean = Pk.mean(0), Q.mean(0)
        A, B = Pk - mp, Q - Qk_mean
        U, Sg, Vt = np.linalg.svd(B.T @ A); D = np.eye(2); D[1, 1] = np.sign(np.linalg.det(U @ Vt))
        Rm = U @ D @ Vt; sc = (Sg * np.diag(D)).sum() / (A ** 2).sum()
        step = np.eye(3); step[:2, :2] = sc * Rm; step[:2, 2] = Qk_mean - sc * Rm @ mp
        T = step @ T
        if abs(sc - 1) < 1e-5 and np.hypot(*(step[:2, 2] - (np.eye(2) - sc * Rm) @ mp)) < 0.05: break
    return T

TRUST_ROAD_M = 9.0     # a page this close to the roads is trusted as a source for other pages
ACCEPT_ROAD_M = 10.0   # a picture-placed page is kept when its route is this close to the roads

def all_pages():
    """every Garbage page with a readable run number: [(pdf, page, day, run)]"""
    houses = load_houses_by_run(); out = []
    for day, pdf in find_pdfs().items():
        texts = page_texts(pdf)
        for page in sorted(texts):
            t = read_title(texts.get(page, ''))
            if t and (day, t[1]) in houses: out.append((pdf, page, day, t[1]))
    return out

def run():
    placed = load_placed(); houses = load_houses_by_run(); NEW, OLD = current_and_prior_boundaries()
    pts_of = {}
    def pts(pdf, page):
        if (pdf, page) not in pts_of:
            L = page_routes(pdf, page); pts_of[(pdf, page)] = densify(L['green'] + L['orange'] + L['purple']) if any(L.values()) else None
        return pts_of[(pdf, page)]
    trusted, final = {}, {}
    for key, (day, run_no, T) in placed.items():
        p = pts(*key)
        if p is None: continue
        d = road_dist(T, p)
        if d > TRUST_ROAD_M:                         # a weak fit: try nudging it onto the roads
            T2 = refine_to_roads(T, p); d2 = road_dist(T2, p)
            dh2 = route_check(apply(T2, p), np.array(houses[(day, run_no)]))
            if d2 <= TRUST_ROAD_M and dh2 <= MAX_ROUTE_M and np.sqrt(((apply(T2, p) - apply(T, p)) ** 2).sum(1)).mean() < 250:
                print(f'  {day} run {run_no} p{key[1]}: own fit {d:.1f} m from roads -> nudged to {d2:.1f} m', flush=True)
                trusted[key] = (day, run_no, T2); final[key] = (T2, 'own fit, nudged to roads', d2, dh2); continue
        if d <= TRUST_ROAD_M: trusted[key] = (day, run_no, T); final[key] = (T, 'own fit', d, None)
    print(len(placed), 'placed by shape;', len(trusted), 'of them within', TRUST_ROAD_M, 'm of the roads (trusted)', flush=True)
    todo = [x for x in all_pages() if (x[0], x[1]) not in final]
    changed = True
    while changed:                                   # newly placed pages can place others in turn
        changed = False
        for pdf, page, day, run_no in list(todo):
            p = pts(pdf, page)
            if p is None: todo.remove((pdf, page, day, run_no)); continue
            res = place(pdf, page, trusted)
            if not res: continue
            T, src, n = res
            d = road_dist(T, p)
            dh = route_check(apply(T, p), np.array(houses[(day, run_no)]))
            if d <= ACCEPT_ROAD_M and dh <= MAX_ROUTE_M:
                final[(pdf, page)] = (T, f'picture of {src[0]} p{src[1]} ({n} features)', d, dh)
                if d <= TRUST_ROAD_M: trusted[(pdf, page)] = (day, run_no, T)
                todo.remove((pdf, page, day, run_no)); changed = True
                print(f'  {day} run {run_no} p{page}: placed from {src[0][:24]} p{src[1]} ({n} features) - {d:.1f} m from roads, {dh:.1f} m from houses', flush=True)
    for pdf, page, day, run_no in todo: print(f'  {day} run {run_no} p{page}: still not placed', flush=True)
    # write the picture-placed pages (and pages whose own fit was weak but now placed from a picture)
    by_day = {}
    for (pdf, page), (T, how, d, dh) in final.items():
        if how == 'own fit': continue
        day = next(x[2] for x in all_pages_cache if x[0] == pdf and x[1] == page); run_no = next(x[3] for x in all_pages_cache if x[0] == pdf and x[1] == page)
        L = page_routes(pdf, page)
        rm = {k: [apply(T, pl).tolist() for pl in v] for k, v in L.items()}
        rm, _, _ = drop_stray_pieces(rm)
        tag = f'GAR|{day}||{run_no}|{pdf} p{page}'; key = f'Garbage#{day}#{run_no}'
        r = by_day.setdefault(day, ([], {}))
        r[0].append(dict(tag=tag, houses=len(houses[(day, run_no)]), fit_m=round(dh, 1), road_m=round(d, 1), run_from='picture', matched=how,
                         new=measure(rm, geom_for(NEW, key)), old=measure(rm, geom_for(OLD, key))))
        r[1][tag] = routes_to_ll(rm)
    for day, (res, routes) in by_day.items():
        json.dump(res, open(f'{S}/compare-results-GAR-zpic-{day}.json', 'w'), indent=1)
        json.dump(routes, open(f'{S}/routes-m-GAR-zpic-{day}.json', 'w'))
    # runs covered now
    cov = {}
    for x in all_pages_cache:
        if (x[0], x[1]) in final: cov.setdefault(x[2], set()).add(x[3])
    for d in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
        allr = sorted({x[3] for x in all_pages_cache if x[2] == d}, key=int)
        print(d, 'runs with a placed page:', len(cov.get(d, ())), 'of', len(allr), '- missing', [r for r in allr if r not in cov.get(d, set())])

all_pages_cache = []
_ap = all_pages
def all_pages():
    global all_pages_cache
    if not all_pages_cache: all_pages_cache = _ap()
    return all_pages_cache

if __name__ == '__main__':
    check() if '--check' in sys.argv else run()
