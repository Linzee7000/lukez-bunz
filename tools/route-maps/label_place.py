"""Place a route-map page by reading the street names on its street-map picture.

Every street-map picture has its street names printed along the streets. Apple's Vision text recognition
(ocr/ocr.swift, built into macOS) reads them with their positions on the picture; OpenStreetMap (work/roads.json)
knows where each named street really is. Matching the names to the real streets pins the picture to the ground:
  1. keep the names that match a street near the run's houses (e.g. "FETHERS" -> Fethers Road)
  2. RANSAC: try pairs of names, each at its street's middle, as a first guess of picture -> ground
  3. refine: move every agreeing name onto the nearest point of its own street, re-solve, repeat
  4. check the page's route lines then sit on the roads and pass the run's houses
This needs no other page to overlap it, so it reaches the pages picture_place.py couldn't.

    python label_place.py "3_202604_Garbage_Wednesday.pdf" 1        # one page, with a report
    python label_place.py --all                                       # every Garbage page not yet placed
"""
import base64, json, math, os, re, subprocess, sys, random
import numpy as np
from scipy.spatial import cKDTree
from lib import S, to_m, page_routes, densify, current_and_prior_boundaries, geom_for, measure, routes_to_ll, drop_stray_pieces
from picture_place import svg_path, apply, road_dist, route_check, all_pages
from identify_garbage import load_houses_by_run

HERE = os.path.dirname(os.path.abspath(__file__))
OCR_DIR = os.path.join(HERE, 'ocr')
GENERIC = {'beach', 'bridge', 'reserve', 'foreshore', 'library', 'junction', 'bay', 'view', 'hill', 'creek', 'park', 'school', 'club', 'yacht',
           'store', 'camping', 'caravan', 'drain', 'river', 'lake', 'point', 'north', 'south', 'east', 'west', 'main', 'high', 'station', 'track',
           'service', 'the', 'old', 'new', 'upper', 'lower', 'unsealed', 'private', 'fire', 'access', 'boat', 'ramp', 'jetty', 'pier'}
SUFFIX = {'road', 'rd', 'street', 'st', 'court', 'ct', 'avenue', 'ave', 'av', 'drive', 'dr', 'crescent', 'cres', 'parade', 'pde', 'place', 'pl',
          'grove', 'gr', 'close', 'cl', 'highway', 'hwy', 'terrace', 'tce', 'lane', 'la', 'circuit', 'cct', 'boulevard', 'bvd', 'esplanade',
          'esp', 'way', 'wy', 'rise', 'mews', 'walk', 'track', 'trk', 'gardens', 'gdns', 'square', 'sq', 'view', 'vista', 'glade', 'link', 'loop'}

def full_picture(pdf, page):
    """the page's street-map picture at full size (PNG path) and its picture-px -> page-pt matrix"""
    t = open(svg_path(pdf, page)).read()
    imgs = {m.group(1): (int(m.group(2)), int(m.group(3)), m.group(4)) for m in
            re.finditer(r'<image id="([^"]+)" x="0" y="0" width="(\d+)" height="(\d+)" xlink:href="data:image/[a-z]+;base64,([^"]+)"', t)}
    best = None
    for m in re.finditer(r'<use xlink:href="#([^"]+)"(?![^>]*filter)[^>]*transform="matrix\(([^)]+)\)"', t):
        if m.group(1) in imgs and imgs[m.group(1)][0] * imgs[m.group(1)][1] >= 1_000_000:
            w, h, b64 = imgs[m.group(1)]
            if best is None or w * h > best[0]: best = (w * h, [float(v) for v in m.group(2).split(',')], b64)
    if not best: return None, None
    a, b, c, d, e, f = best[1]
    png = os.path.join(OCR_DIR, re.sub(r'[^A-Za-z0-9]+', '_', pdf) + f'_{page}.png')
    if not os.path.exists(png): open(png, 'wb').write(base64.b64decode(best[2]))
    return png, np.array([[a, c, e], [b, d, f], [0, 0, 1.0]])

def ocr(png):
    js = png[:-4] + '.json'
    if not os.path.exists(js):
        with open(js, 'w') as f: subprocess.run(['swift', os.path.join(OCR_DIR, 'ocr.swift'), png], stdout=f, stderr=subprocess.DEVNULL, check=False)
    try: return json.load(open(js))
    except Exception: return []

_roads = None
def roads():
    global _roads
    if _roads is None:
        _roads = []
        for r in json.load(open(f'{S}/roads.json')):
            if not r.get('name') or len(r['pts']) < 2: continue
            words = re.sub(r'[^a-z ]', ' ', r['name'].lower()).split()
            base = ' '.join(w for w in words if w not in SUFFIX) or ' '.join(words)
            _roads.append((base, r['name'], np.array([to_m(a, b) for a, b in r['pts']])))
    return _roads

def label_key(t):
    words = re.sub(r'[^A-Za-z ]', ' ', t).lower().split()
    words = [w for w in words if w not in SUFFIX]
    return ' '.join(words)

def seg_nearest(P, pts):
    """nearest point on polyline P (n x 2) to each of pts (m x 2) -> (points, distances)"""
    A, B = P[:-1], P[1:]; AB = B - A; L2 = (AB ** 2).sum(1) + 1e-9
    best_d = np.full(len(pts), np.inf); best_p = np.zeros_like(pts)
    for i in range(len(A)):
        t = np.clip(((pts - A[i]) @ AB[i]) / L2[i], 0, 1); Q = A[i] + t[:, None] * AB[i]
        d = np.hypot(*(pts - Q).T); m = d < best_d; best_d[m] = d[m]; best_p[m] = Q[m]
    return best_p, best_d

def similarity(src, dst):
    """least-squares similarity (rotation, scale, shift; no mirroring) src -> dst, 3x3"""
    ms, md = src.mean(0), dst.mean(0); A, B = src - ms, dst - md
    U, Sg, Vt = np.linalg.svd(B.T @ A); D = np.eye(2); D[1, 1] = np.sign(np.linalg.det(U @ Vt))
    R = U @ D @ Vt; s = (Sg * np.diag(D)).sum() / max((A ** 2).sum(), 1e-9)
    T = np.eye(3); T[:2, :2] = s * R; T[:2, 2] = md - s * R @ ms; return T

def place_by_labels(pdf, page, H, verbose=False):
    png, M = full_picture(pdf, page)
    if png is None: return None
    words = ocr(png)
    lo, hi = H.min(0) - 2500, H.max(0) + 2500
    near = [(b, n, P) for b, n, P in roads() if (P[:, 0].max() > lo[0]) and (P[:, 0].min() < hi[0]) and (P[:, 1].max() > lo[1]) and (P[:, 1].min() < hi[1])]
    by_base = {}
    for b, n, P in near: by_base.setdefault(b, []).append((n, P))
    labels = []
    for w in words:
        if w['c'] < 0.3: continue
        letters = re.sub(r'[^A-Za-z]', '', w['t'])
        if len(letters) < 4 or letters != letters.upper(): continue       # street names are printed in capitals
        k = label_key(w['t'])
        if len(k) < 4 or k in GENERIC or all(x in GENERIC for x in k.split()): continue
        cands = by_base.get(k) or ([] if len(k) < 5 else [x for b, L in by_base.items() if b.startswith(k) or (len(b) >= 5 and k.startswith(b)) for x in L])
        if not cands: continue
        c = np.array(w['p']).mean(0)
        pts = np.vstack([densify([P.tolist()], 5.0) for _, P in cands])
        labels.append(dict(t=w['t'], k=k, px=c, roads=[P for _, P in cands], tree=cKDTree(pts), pts=pts))
    # one label per distinct name+place (the same name read upright and turned lands in the same spot)
    uniq = []
    for L in labels:
        if not any(u['k'] == L['k'] and np.hypot(*(u['px'] - L['px'])) < 40 for u in uniq): uniq.append(L)
    labels = uniq
    if verbose: print(f'  {len(words)} words read, {len(labels)} match a street near the run: {sorted({l["k"] for l in labels})}')
    if len(labels) < 4: return None
    px = np.array([l['px'] for l in labels])
    def resid(T):
        Q = apply(T, px); return np.array([l['tree'].query(Q[i])[0] for i, l in enumerate(labels)])
    # Voting: for each rotation and zoom, every name votes for every shift that would put it on its own street
    # (one vote per name per cell). The true placement collects votes from most names at once. Done coarse
    # (big cells, so a zoom that's a few % out still lines up) and then fine around the coarse winner.
    per = [(i, l['pts'][::2]) for i, l in enumerate(labels)]
    FLIP = np.array([[1, 0], [0, -1]])                  # picture y runs down, ground y runs north
    def vote(ths, scs, C, around=None, radius=None):
        best = None
        for th in ths:
            c0, s0 = math.cos(th), math.sin(th)
            for sc in scs:
                R = sc * np.array([[c0, -s0], [s0, c0]]) @ FLIP
                keys = []
                for i, pts in per:
                    t = pts - R @ px[i]
                    if around is not None: t = t[np.hypot(*(t - around).T) < radius]
                    if not len(t): continue
                    cells = np.unique(np.floor(t / C).astype(np.int64), axis=0)
                    keys.append(cells[:, 0] * 1000003 + cells[:, 1])
                if not keys: continue
                u, cnt = np.unique(np.concatenate(keys), return_counts=True)
                j = np.argmax(cnt)
                if best is None or cnt[j] > best[0]:
                    k = int(u[j]); a = int(round(k / 1000003)); b = k - a * 1000003
                    best = (int(cnt[j]), th, sc, (np.array([a, b]) + 0.5) * C)
        return best
    coarse_th = [math.radians(r) + math.radians(d) for r in (0, 90, 180, 270) for d in (-4, 0, 4)]
    b1 = vote(coarse_th, np.geomspace(0.08, 6.0, 90), 160.0)
    if not b1 or b1[0] < 5: return None
    b2 = vote([b1[1] + math.radians(d) for d in np.arange(-4, 4.5, 0.5)], b1[2] * np.linspace(0.93, 1.07, 29), 25.0, around=b1[3], radius=900)
    if not b2 or b2[0] < 5: return None
    n, th, sc, tr = b2
    T = np.eye(3); T[:2, :2] = sc * np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]]) @ FLIP; T[:2, 2] = tr
    best = (n, T)
    if verbose: print(f'  votes: coarse {b1[0]}, fine {n} at zoom {sc:.3f} m/px, rotation {math.degrees(th):.1f} deg')
    T = best[1]
    for _ in range(15):                              # pull each agreeing name onto its own street, re-solve
        Q = apply(T, px); src, dst = [], []
        for i, l in enumerate(labels):
            d, k = l['tree'].query(Q[i])
            if d < 60: src.append(px[i]); dst.append(l['pts'][k])
        if len(src) < 4: return None
        # the picture's y runs down the page: solve in flipped picture coordinates, then put the flip back
        T = similarity(np.array(src) * [1, -1], np.array(dst)) @ np.diag([1.0, -1.0, 1.0])
    r = resid(T); inl = int((r < 40).sum())
    page_T = T @ np.linalg.inv(M)                    # page pt -> picture px -> metres
    return page_T, inl, len(labels), float(np.median(r[r < 40])) if inl else 99

def run_all():
    """Every Garbage page not already well placed (by its own fit or by picture_place.py) -> work/*-GAR-zlab-<Day>.json"""
    import glob
    from picture_place import load_placed, refine_to_roads
    houses = load_houses_by_run(); NEW, OLD = current_and_prior_boundaries()
    good = set()
    for f in glob.glob(f'{S}/compare-results-GAR-zpic-*.json'):
        for r in json.load(open(f)):
            if 'fit_m' in r: good.add(r['tag'].split('|')[4])
    for key, (day, run, T) in load_placed().items():
        L = page_routes(*key); p = densify(L['green'] + L['orange'] + L['purple'])
        if road_dist(refine_to_roads(T, p), p) <= 9.0: good.add(f'{key[0]} p{key[1]}')
    by_day = {}
    for pdf, page, day, run in all_pages():
        if f'{pdf} p{page}' in good: continue
        L = page_routes(pdf, page)
        if not any(L.values()): continue
        p = densify(L['green'] + L['orange'] + L['purple']); H = np.array(houses[(day, run)])
        res = place_by_labels(pdf, page, H)
        if not res: print(f'  {day} run {run} p{page}: not enough street names', flush=True); continue
        T, inl, n, med = res
        T2 = refine_to_roads(T, p); dr = road_dist(T2, p); dh = route_check(apply(T2, p), H)
        moved = float(np.sqrt(((apply(T2, p) - apply(T, p)) ** 2).sum(1)).mean())
        # placed if the route sits on the roads and either passes the run's houses, or the street names agree
        # so strongly (15+, three quarters of them) that a detail page's link roads can't count against it
        # (rural pages: wide roads and houses set far back, so with 20+ names agreeing allow a little more)
        ok = moved < 150 and ((dr <= 10.0 and dh <= 40.0 and inl >= 8 and inl >= 0.5 * n) or (dr <= 10.0 and inl >= 15 and inl >= 0.75 * n and moved < 60)
                              or (dr <= 11.0 and inl >= 20 and inl >= 0.65 * n and moved < 60))
        print(f'  {day} run {run} p{page}: {inl}/{n} names agree, route {dr:.1f} m from roads, {dh:.1f} m from houses, nudged {moved:.0f} m -> {"PLACED" if ok else "rejected"}', flush=True)
        if not ok: continue
        rm = {k: [apply(T2, pl).tolist() for pl in v] for k, v in L.items()}
        rm, _, _ = drop_stray_pieces(rm)
        tag = f'GAR|{day}||{run}|{pdf} p{page}'; key = f'Garbage#{day}#{run}'
        d = by_day.setdefault(day, ([], {}))
        d[0].append(dict(tag=tag, houses=len(H), fit_m=round(min(dh, 15.0), 1), road_m=round(dr, 1), run_from='street names', names=f'{inl}/{n}',
                         new=measure(rm, geom_for(NEW, key)), old=measure(rm, geom_for(OLD, key))))
        d[1][tag] = routes_to_ll(rm)
    for day, (res, routes) in by_day.items():
        json.dump(res, open(f'{S}/compare-results-GAR-zlab-{day}.json', 'w'), indent=1)
        json.dump(routes, open(f'{S}/routes-m-GAR-zlab-{day}.json', 'w'))

if __name__ == '__main__':
    houses = load_houses_by_run()
    if '--all' in sys.argv: run_all(); sys.exit()
    if '--all' not in sys.argv:
        pdf, page = sys.argv[1], int(sys.argv[2])
        day = next(d for d in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'] if d in pdf)
        run = next(x[3] for x in all_pages() if x[0] == pdf and x[1] == page)
        H = np.array(houses[(day, run)])
        res = place_by_labels(pdf, page, H, verbose=True)
        if not res: print('  not placed'); sys.exit()
        T, inl, n, med = res
        L = page_routes(pdf, page); p = densify(L['green'] + L['orange'] + L['purple'])
        print(f'  {inl} of {n} names agree (median {med:.1f} m off their street); route -> roads {road_dist(T, p):.1f} m, -> run houses {route_check(apply(T, p), H):.1f} m')
