"""Stretch each run's boundary so it also covers the streets the truck drives (read off the route-map PDFs).

Only route that is more than GAP_M outside the current boundary is added (as a corridor BUFFER_M each side), so the
parts of a boundary that already fit are left exactly as they are. Only pages that were placed well (fit <= MAX_FIT_M)
are used. Writes data/run-boundaries.json with a new `generated` value so devices pick it up.

Run from this folder after compare.py (needs work/routes-m*.json and work/compare-results*.json):
    python extend_boundaries.py            # writes work/run-boundaries.extended.json and prints a report
    python extend_boundaries.py --write    # ...and replaces ../../data/run-boundaries.json
"""
import glob, json, math, os, sys, datetime
from shapely.geometry import LineString, Polygon, MultiPolygon
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, 'work')
DATA = os.path.abspath(os.path.join(HERE, '..', '..', 'data', 'run-boundaries.json'))
LAT0, LNG0 = -38.30, 144.95
KX = 111320 * math.cos(math.radians(LAT0)); KY = 110540.0
GAP_M, MIN_PIECE_M, BUFFER_M, MAX_FIT_M, MAX_GROWTH = 8.0, 15.0, 14.0, 15.0, 0.6
DAY = {'Mon': 'Monday', 'Tue': 'Tuesday', 'Wed': 'Wednesday', 'Thu': 'Thursday', 'Fri': 'Friday'}

def to_m(lat, lng): return ((lng - LNG0) * KX, (lat - LAT0) * KY)
def to_ll(x, y): return [round(LAT0 + y / KY, 5), round(LNG0 + x / KX, 5)]

routes, fits = {}, {}
for f in sorted(glob.glob(f'{WORK}/routes-m*.json')): routes.update(json.load(open(f)))
for f in sorted(glob.glob(f'{WORK}/compare-results*.json')):
    for r in json.load(open(f)):
        if 'fit_m' in r: fits[r['tag']] = r['fit_m']

bd = json.load(open(DATA))
def run_geom(key):
    rings = [bd['boundaries'][key]] + bd.get('extras', {}).get(key, [])
    polys = []
    for r in rings:
        pts = [to_m(p[0], p[1]) for p in r]
        if len(pts) >= 3:
            pg = Polygon(pts)
            if not pg.is_valid: pg = pg.buffer(0)
            if not pg.is_empty: polys.append(pg)
    return unary_union(polys) if polys else None

# route lines per run key (all pages of that run that were placed well)
per_run = {}
for tag, cols in routes.items():
    if fits.get(tag, 999) > MAX_FIT_M: continue
    parts = tag.split()                      # e.g. "1.1 p1 Mon A 219"
    key = f'Recycling#{DAY[parts[2]]}#{parts[3]}#{parts[4]}'
    for name, polys in cols.items():
        for pl in polys:
            xy = [(x * KX, y * KY) for x, y in pl]
            if len(xy) >= 2: per_run.setdefault(key, []).append(LineString(xy))

def rings_of(geom):
    polys = [geom] if isinstance(geom, Polygon) else [g for g in getattr(geom, 'geoms', []) if isinstance(g, Polygon)]
    polys = sorted([p for p in polys if not p.is_empty], key=lambda p: -p.area)
    return [[to_ll(x, y) for x, y in p.simplify(1.0).exterior.coords[:-1]] for p in polys]

changed, skipped, report = {}, [], []
for key, lines in sorted(per_run.items()):
    if key not in bd['boundaries']: skipped.append((key, 'no boundary for this key')); continue
    g = run_geom(key)
    if g is None: skipped.append((key, 'empty boundary')); continue
    route = unary_union(lines)
    outside = route.difference(g.buffer(GAP_M))
    pieces = [outside] if outside.geom_type == 'LineString' else list(getattr(outside, 'geoms', []))
    pieces = [p for p in pieces if p.geom_type == 'LineString' and p.length >= MIN_PIECE_M]
    if not pieces: report.append((key, 0, 0.0, 0.0)); continue
    added = unary_union([p.buffer(BUFFER_M) for p in pieces])
    grown = unary_union([g, added])
    if not grown.is_valid: grown = grown.buffer(0)
    growth = (grown.area - g.area) / g.area
    if growth > MAX_GROWTH: skipped.append((key, f'would grow {growth*100:.0f}% - left alone')); continue
    rs = rings_of(grown)
    if not rs: skipped.append((key, 'no rings')); continue
    changed[key] = rs
    report.append((key, len(pieces), sum(p.length for p in pieces), growth))

out = json.loads(json.dumps(bd))
for key, rs in changed.items():
    out['boundaries'][key] = rs[0]
    if len(rs) > 1: out['extras'][key] = rs[1:]
    else: out.get('extras', {}).pop(key, None)
out['version'] = 4
out['generated'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
out['note'] = ('Run boundaries from Vicmap property lines (each run covers its own lots and meets its neighbour down the middle of the road), '
               'stretched to include the streets the recycling trucks drive, read off the route-map PDFs. Keys are stream#day#week#run. Loaded by the app on start.')

for key, n, length, growth in report:
    if n: print(f'{key:34s} +{n:2d} street pieces ({length:6.0f} m)  area +{growth*100:4.0f}%')
print(f'\nruns with a route map: {len(per_run)}   extended: {len(changed)}   already covered: {len([r for r in report if not r[1]])}   left alone: {len(skipped)}')
for k, why in skipped: print('  skipped', k, '-', why)
dest = os.path.join(WORK, 'run-boundaries.extended.json')
json.dump(out, open(dest, 'w'), separators=(',', ':'))
print('wrote', dest, os.path.getsize(dest), 'bytes')
if '--write' in sys.argv:
    json.dump(out, open(DATA, 'w'), separators=(',', ':')); print('replaced', DATA)
