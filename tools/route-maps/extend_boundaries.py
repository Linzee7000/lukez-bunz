"""Stretch each run's boundary so it also covers the streets the truck drives (read off the route-map PDFs),
then fix any overlap that stretching creates between two runs of the same stream and day: where they now
share ground, split it down the middle between them (nearest to each run's own pre-extension boundary).

Only route that is more than GAP_M outside the current boundary is added (as a corridor BUFFER_M each side), so the
parts of a boundary that already fit are left exactly as they are. Only pages that were placed well (fit <= MAX_FIT_M)
are used. Writes data/run-boundaries.json with a new `generated` value so devices pick it up.

Run from this folder after compare.py (needs work/routes-m*.json and work/compare-results*.json):
    python extend_boundaries.py            # writes work/run-boundaries.extended.json and prints a report
    python extend_boundaries.py --write    # ...and replaces ../../data/run-boundaries.json

ROUTEMAP_BASE_BOUNDARIES can point at a different starting run-boundaries.json (e.g. a pre-extension
snapshot) instead of the live data/run-boundaries.json - use this to redo the extension from scratch
rather than stacking it on an already-extended file.
"""
import csv, glob, json, math, os, sys, datetime
from shapely.geometry import LineString, Polygon, Point, MultiPoint
from shapely.ops import unary_union, voronoi_diagram
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, 'work')
DATA = os.path.abspath(os.path.join(HERE, '..', '..', 'data', 'run-boundaries.json'))
BASE = os.environ.get('ROUTEMAP_BASE_BOUNDARIES', DATA)
LAT0, LNG0 = -38.30, 144.95
KX = 111320 * math.cos(math.radians(LAT0)); KY = 110540.0
GAP_M, MIN_PIECE_M, BUFFER_M, MAX_FIT_M, MAX_GROWTH = 8.0, 15.0, 14.0, 15.0, 0.6
OVERLAP_MIN_M2, OVERLAP_GROWTH_M2 = 50.0, 100.0   # ignore trivial overlaps, and ones extension didn't meaningfully worsen
DAY = {'Mon': 'Monday', 'Tue': 'Tuesday', 'Wed': 'Wednesday', 'Thu': 'Thursday', 'Fri': 'Friday'}

def to_m(lat, lng): return ((lng - LNG0) * KX, (lat - LAT0) * KY)
def to_ll(x, y): return [round(LAT0 + y / KY, 5), round(LNG0 + x / KX, 5)]

routes, fits = {}, {}
for f in sorted(glob.glob(f'{WORK}/routes-m*.json')): routes.update(json.load(open(f)))
for f in sorted(glob.glob(f'{WORK}/compare-results*.json')):
    for r in json.load(open(f)):
        if 'fit_m' in r: fits[r['tag']] = r['fit_m']

bd = json.load(open(BASE))
_geom_cache = {}
def run_geom(key):
    """This run's boundary as it is in BASE (the pre-extension "ground truth" for that run)."""
    if key in _geom_cache: return _geom_cache[key]
    if key not in bd['boundaries']: _geom_cache[key] = None; return None
    rings = [bd['boundaries'][key]] + bd.get('extras', {}).get(key, [])
    polys = []
    for r in rings:
        pts = [to_m(p[0], p[1]) for p in r]
        if len(pts) >= 3:
            pg = Polygon(pts)
            if not pg.is_valid: pg = pg.buffer(0)
            if not pg.is_empty: polys.append(pg)
    g = unary_union(polys) if polys else None
    _geom_cache[key] = g
    return g

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
    polys = sorted([p for p in polys if not p.is_empty and p.area > 1], key=lambda p: -p.area)
    return [[to_ll(x, y) for x, y in p.simplify(1.0).exterior.coords[:-1]] for p in polys]

# ---- step 1: grow each run to cover the streets its own route map(s) drive ----
final_by_key, skipped, report = {}, [], []
for key, lines in sorted(per_run.items()):
    g = run_geom(key)
    if g is None: skipped.append((key, 'no boundary for this key')); continue
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
    final_by_key[key] = grown
    report.append((key, len(pieces), sum(p.length for p in pieces), growth))

# ---- step 2: where growing two runs made them overlap, split the overlap down the middle ----
def group_key(k):
    parts = k.split('#'); return (parts[0], parts[1])   # stream, day - runs of the same day share physical roads regardless of week

by_group = {}
for key in bd['boundaries']:
    by_group.setdefault(group_key(key), []).append(key)

# This run's own houses - the boundary this app uses everywhere else is itself a nearest-HOUSE tessellation,
# so splitting disputed ground by nearest house (not nearest boundary edge) matches that and never reassigns
# a house that is genuinely this run's own to a neighbour just because the neighbour's edge is a bit closer.
_houses_by_key = {}
try:
    with open(f'{WORK}/master.csv', newline='', encoding='utf8') as f:
        for row in csv.DictReader(f):
            run = (row.get('Solo Recycling Run') or '').strip()
            if not run: continue
            try: lat, lng = float(row['Lat']), float(row['Lng'])
            except Exception: continue
            k = f"Recycling#{row['Solo Collection Day'].strip()}#{row['Solo Week Cycle'].strip().upper()}#{run}"
            _houses_by_key.setdefault(k, []).append(to_m(lat, lng))
except FileNotFoundError:
    print('  (no work/master.csv - overlap split will use boundary edges only, not houses)')

def sample_boundary(poly, near, step=5.0):
    """Points every `step` m along poly's exterior(s), kept only where they fall inside `near`."""
    rings = ([poly.exterior] + list(poly.interiors)) if poly.geom_type == 'Polygon' \
        else [r for p in poly.geoms if p.geom_type == 'Polygon' for r in ([p.exterior] + list(p.interiors))]
    pts = []
    for ring in rings:
        coords = list(ring.coords)
        for (x0, y0), (x1, y1) in zip(coords[:-1], coords[1:]):
            L = math.hypot(x1 - x0, y1 - y0); n = max(1, int(L / step))
            for k in range(n):
                x, y = x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n
                if near.contains(Point(x, y)): pts.append((x, y))
    return pts

def generator_points(key, near):
    """Points that stand for "this is run `key`'s own ground" near the disputed area: its own houses first
    (matching the nearest-house tessellation the rest of the app's boundaries are built from), topped up with
    a sparse sample of its original boundary so the split still has something to go on wherever a run's
    houses don't quite reach the disputed edge (e.g. the edge is a street with no houses on this side)."""
    pts = [(x, y) for x, y in _houses_by_key.get(key, []) if near.contains(Point(x, y))]
    ok = run_geom(key)
    if ok is not None: pts += sample_boundary(ok, near, step=15.0)
    return pts

def resolve_group(keys):
    """Where growing runs of this (stream, day) group made any of them overlap, split the disputed ground
    down the middle: a proper N-way Voronoi partition (by nearest own house / original boundary), so -
    unlike fixing one pair at a time - a fix for one pair can never quietly reopen another. Only the actual
    disputed ground (the overlaps themselves, plus a small margin for context) is ever touched; the rest of
    every run's shape - the overwhelming majority of it - is left exactly as extended. Returns the number of
    keys whose shape changed."""
    extended = [k for k in keys if k in final_by_key]
    if not extended: return 0, []
    shapes = {k: (final_by_key.get(k) or run_geom(k)) for k in keys}
    shapes = {k: g for k, g in shapes.items() if g is not None}
    disputes = []   # each new-overlap region, plus which keys it's between
    for i, a in enumerate(keys):
        if a not in shapes: continue
        for b in keys[i + 1:]:
            if b not in shapes: continue
            if a not in extended and b not in extended: continue   # extension touched neither - nothing to fix
            ga, gb = shapes[a], shapes[b]
            if not ga.intersects(gb): continue
            new_ov = ga.intersection(gb)
            if new_ov.is_empty or new_ov.area < OVERLAP_MIN_M2: continue
            oa, ob = run_geom(a), run_geom(b)
            old_ov = oa.intersection(ob).area if (oa is not None and ob is not None) else 0.0
            if new_ov.area - old_ov < OVERLAP_GROWTH_M2: continue   # not something our extension introduced
            disputes.append((a, b, new_ov))
    if not disputes: return 0, []

    dispute_zone = unary_union([d[2] for d in disputes]).buffer(120)
    in_play = sorted({k for a, b, _ in disputes for k in (a, b)})
    near = dispute_zone.buffer(300)
    pts = []
    for k in in_play:
        for x, y in generator_points(k, near): pts.append((x, y, k))
    if len(pts) < 2 * len(in_play): return 0, []   # too sparse to trust a partition here
    try:
        vd = voronoi_diagram(MultiPoint([(x, y) for x, y, _ in pts]), envelope=dispute_zone.buffer(50))
        tree = STRtree([Point(x, y) for x, y, _ in pts])
        cells_by_key = {k: [] for k in in_play}
        for cell in vd.geoms:
            if not cell.is_valid: cell = cell.buffer(0)
            if cell.is_empty: continue
            lbl = None
            for idx in tree.query(cell):
                x, y, l = pts[idx]
                if cell.buffer(1e-6).contains(Point(x, y)): lbl = l; break
            if lbl is not None: cells_by_key[lbl].append(cell)
    except Exception as e:
        print('  (group voronoi split failed, leaving this group as-is:', e, ')'); return 0, []

    changed_keys = []
    for k in in_play:
        cells = cells_by_key.get(k) or []
        if not cells: continue
        # shrink each side's share by a touch: rounding coordinates to 5 dp for storage (~1m) and the
        # simplify() below can otherwise let two adjacent, freshly-split shares touch or re-overlap by a
        # sliver once written out and reloaded - an invisible gap here is cheaper than a re-opened overlap.
        own_cell = unary_union(cells).buffer(-1.5)
        cur = shapes[k]
        # only the part of this run's shape that lies IN the disputed ground is ever touched
        new_shape = unary_union([cur.difference(dispute_zone), cur.intersection(dispute_zone).intersection(own_cell)])
        if not new_shape.is_valid: new_shape = new_shape.buffer(0)
        if abs(new_shape.area - cur.area) > 1:
            final_by_key[k] = new_shape; changed_keys.append(k)
    return len(changed_keys), changed_keys

overlap_report = []
for gk, keys in by_group.items():
    n, touched = resolve_group(keys)
    if n: overlap_report.append((gk, touched))

# ---- write out ----
changed = {}
for key, g in final_by_key.items():
    rs = rings_of(g)
    if rs: changed[key] = rs

out = json.loads(json.dumps(bd))
for key, rs in changed.items():
    out['boundaries'][key] = rs[0]
    if len(rs) > 1: out['extras'][key] = rs[1:]
    else: out.get('extras', {}).pop(key, None)
out['version'] = 5
out['generated'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
out['note'] = ('Run boundaries from Vicmap property lines (each run covers its own lots and meets its neighbour down the middle of the road), '
               'stretched to include the streets the recycling trucks drive, read off the route-map PDFs; where two runs\' streets share the '
               'same road, that stretch is split down the middle. Keys are stream#day#week#run. Loaded by the app on start.')

for key, n, length, growth in report:
    if n: print(f'{key:34s} +{n:2d} street pieces ({length:6.0f} m)  area +{growth*100:4.0f}%')
print(f'\nruns with a route map: {len(per_run)}   grown: {len(report) - len([r for r in report if not r[1]])}   already covered: {len([r for r in report if not r[1]])}   left alone: {len(skipped)}')
for k, why in skipped: print('  skipped', k, '-', why)
print(f'\n(stream, day) groups with an overlap from extension, split down the middle: {len(overlap_report)}')
for gk, touched in overlap_report:
    print(f'  {gk[0]} {gk[1]}: {len(touched)} run(s) reshaped - {", ".join(touched)}')
dest = os.path.join(WORK, 'run-boundaries.extended.json')
json.dump(out, open(dest, 'w'), separators=(',', ':'))
print('\nwrote', dest, os.path.getsize(dest), 'bytes')
if '--write' in sys.argv:
    json.dump(out, open(DATA, 'w'), separators=(',', ':')); print('replaced', DATA)
