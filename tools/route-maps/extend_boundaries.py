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
# Two runs of the same stream, day AND week can't both service the same ground, so with the split no
# longer zigzagging there's no reason to leave those overlaps alone just because they came in with
# the base shapes rather than from the street extension. Runs of different weeks (A vs B) are
# different fortnights and may legitimately sit on top of each other, so they're never split.
RESOLVE_ALL = os.environ.get('RESOLVE_ALL_OVERLAPS', '1') != '0'
RESOLVE_ALL_MIN_M2 = 2000.0    # only worth reshaping a run for a substantial shared area
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

# Two tag formats can be present in work/: the original Recycling-only "1.1 p1 Mon A 219" (space-separated,
# from before compare.py grew to handle several streams) and the newer "REC|Monday|A|219|..." (pipe-delimited,
# stream-coded). Recycling done the old way is already folded into BASE, so only the new-format tags (any
# stream not yet extended) are turned into route lines here.
STREAM_OF_CODE = {'REC': 'Recycling', 'ORG': 'FOGO', 'GAR': 'Garbage'}
NO_WEEK_STREAMS = {'Garbage'}

def key_of_tag(tag):
    if '|' not in tag: return None   # old-format Recycling tag - already handled, skip
    code, day, week, run_no, _src = tag.split('|', 4)
    stream = STREAM_OF_CODE.get(code)
    if not stream: return None
    return f'{stream}#{day}#{run_no}' if stream in NO_WEEK_STREAMS else f'{stream}#{day}#{week}#{run_no}'

# route lines per run key (all pages of that run that were placed well)
per_run = {}
for tag, cols in routes.items():
    if fits.get(tag, 999) > MAX_FIT_M: continue
    key = key_of_tag(tag)
    if key is None: continue
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

# ---------------------------------------------------------------------------------------------
# The lots each run services.
#
# Splitting disputed road by nearest HOUSE PIN is what made the boundaries zigzag: houses on
# opposite sides of a street are staggered, so the bisector between two rows of points is a
# sawtooth of perpendicular bisectors rather than a line down the road. Between two rows of
# *frontages* - straight lines - the bisector is the road's centreline, which is what the maps
# actually mean and what a driver expects to see.
#
# So the sites for the split are dense samples along each run's own lot outlines (from the shipped
# data/parcels.json), not its house pins. This also means a run's edge follows real property lines
# rather than cutting through back yards.
_lots_by_key = {}      # run key -> [parcel id, ...]
_lot_ring = {}         # parcel id -> [(x, y), ...] in metres, decoded on demand
_lot_bbox = {}         # parcel id -> (minx, miny, maxx, maxy) in metres
_parcel_src = {}


def _load_parcels():
    """Read data/parcels.json: every lot's outline, and which lot each house sits on."""
    path = os.path.abspath(os.path.join(HERE, '..', '..', 'data', 'parcels.json'))
    try:
        pj = json.load(open(path))
    except FileNotFoundError:
        print('  (no data/parcels.json - overlap split will fall back to house pins)')
        return None
    sc = pj.get('scale', 100000)
    for pid, rec in pj['parcels'].items():
        _parcel_src[pid] = (rec[0], sc)
        # bbox straight off the deltas, without building the ring - most lots are nowhere near a
        # dispute and never need decoding at all
        x = y = 0; xs0 = ys0 = 10 ** 9; xs1 = ys1 = -10 ** 9
        d = rec[0]
        for i in range(0, len(d) - 1, 2):
            x += d[i]; y += d[i + 1]
            if x < xs0: xs0 = x
            if x > xs1: xs1 = x
            if y < ys0: ys0 = y
            if y > ys1: ys1 = y
        a = to_m(ys0 / sc, xs0 / sc); b = to_m(ys1 / sc, xs1 / sc)
        _lot_bbox[pid] = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
    return {k: (v[0] if v != 0 else None) for k, v in pj['sites'].items()}


def _ring_of(pid):
    if pid not in _lot_ring:
        d, sc = _parcel_src[pid]
        pts = []; x = y = 0
        for i in range(0, len(d) - 1, 2):
            x += d[i]; y += d[i + 1]
            pts.append(to_m(y / sc, x / sc))
        _lot_ring[pid] = pts
    return _lot_ring[pid]


_houses_by_key = {}
CSV_FIELD_OF_STREAM = {'Recycling': 'Solo Recycling Run', 'FOGO': 'Solo FOGO Run', 'Garbage': 'Solo Garbage Run'}
_site_lot = _load_parcels()
_no_lot = 0
try:
    with open(f'{WORK}/master.csv', newline='', encoding='utf8') as f:
        for row in csv.DictReader(f):
            try: lat, lng = float(row['Lat']), float(row['Lng'])
            except Exception: continue
            day = row['Solo Collection Day'].strip(); week = row['Solo Week Cycle'].strip().upper()
            # the app keys a house by Property ID, falling back to Site Id - match that exactly, or
            # the lot lookup silently misses
            site_key = (row.get('Property ID') or '').strip() or (row.get('Site Id') or '').strip()
            lot = _site_lot.get(site_key) if _site_lot else None
            if _site_lot is not None and not lot: _no_lot += 1
            for stream, field in CSV_FIELD_OF_STREAM.items():
                run = (row.get(field) or '').strip()
                if not run: continue
                k = f'{stream}#{day}#{run}' if stream in NO_WEEK_STREAMS else f'{stream}#{day}#{week}#{run}'
                _houses_by_key.setdefault(k, []).append(to_m(lat, lng))
                if lot: _lots_by_key.setdefault(k, []).append(lot)
except FileNotFoundError:
    print('  (no work/master.csv - overlap split will use boundary edges only, not houses)')
if _site_lot is not None:
    have = sum(len(set(v)) for v in _lots_by_key.values())
    print(f'  lots: {len(_lot_bbox)} known, {have} run-lot links, {_no_lot} houses with no matched lot')

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

LOT_STEP_M = 2.0     # how finely a lot outline is sampled; the finer this is, the closer the split
                     # sits to the true middle of the road (2m is well under a lane width)

def lot_points(key, near):
    """Dense points along this run's own lot outlines, within `near`.

    These are what make the split follow the road: sampled finely enough, a straight frontage
    behaves like a line rather than a point, so the bisector between the frontages facing each
    other across a street lands on the street's centreline instead of zigzagging between houses."""
    b = near.bounds
    pts = []
    for pid in set(_lots_by_key.get(key, ())):
        lb = _lot_bbox.get(pid)
        if not lb or lb[2] < b[0] or lb[0] > b[2] or lb[3] < b[1] or lb[1] > b[3]: continue
        ring = _ring_of(pid)
        for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
            L = math.hypot(x1 - x0, y1 - y0)
            n = max(1, int(L / LOT_STEP_M))
            for k in range(n):
                x, y = x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n
                if b[0] <= x <= b[2] and b[1] <= y <= b[3] and near.contains(Point(x, y)):
                    pts.append((x, y))
    return pts

def generator_points(key, near):
    """Points that stand for "this is run `key`'s own ground" near the disputed area.

    Its own lots, sampled densely, so the resulting edge follows property lines and runs down the
    middle of shared roads. Where a run has no matched lots near the dispute (an unmatched new
    estate, or a stretch of road with no houses on this side at all) this falls back to the old
    behaviour - house pins plus a sparse sample of the run's own pre-extension boundary - so those
    places are no worse than before rather than left with nothing to go on."""
    pts = lot_points(key, near)
    if len(pts) >= 20: return pts
    pts += [(x, y) for x, y in _houses_by_key.get(key, []) if near.contains(Point(x, y))]
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
            pa, pb = a.split('#'), b.split('#')
            same_week = (len(pa) != 4 and len(pb) != 4) or (len(pa) == 4 and len(pb) == 4 and pa[2] == pb[2])
            if a not in extended and b not in extended and not (RESOLVE_ALL and same_week):
                continue   # extension touched neither, and we're not sweeping pre-existing overlaps
            ga, gb = shapes[a], shapes[b]
            if not ga.intersects(gb): continue
            new_ov = ga.intersection(gb)
            if new_ov.is_empty or new_ov.area < OVERLAP_MIN_M2: continue
            oa, ob = run_geom(a), run_geom(b)
            old_ov = oa.intersection(ob).area if (oa is not None and ob is not None) else 0.0
            if new_ov.area - old_ov < OVERLAP_GROWTH_M2:
                # not something our extension introduced - only take it on if it's a real same-week
                # conflict big enough to be worth reshaping for
                if not (RESOLVE_ALL and same_week and new_ov.area >= RESOLVE_ALL_MIN_M2): continue
            disputes.append((a, b, new_ov))
    if not disputes: return 0, []

    dispute_zone = unary_union([d[2] for d in disputes]).buffer(120)
    in_play = sorted({k for a, b, _ in disputes for k in (a, b)})
    near = dispute_zone.buffer(300)
    # Adjacent lots share an edge, so sampling lot outlines produces the same point twice - and a
    # duplicate point makes shapely's Voronoi fail outright ("Invalid number of points in
    # LinearRing found 2"), which silently left whole groups unsplit. Snap to 10cm and drop any
    # point two runs both claim: that's a shared property line, where neither side has a better
    # claim than the other, so it shouldn't vote either way.
    owner = {}
    for k in in_play:
        for x, y in generator_points(k, near):
            q = (round(x, 1), round(y, 1))
            if q in owner and owner[q] != k: owner[q] = None
            elif q not in owner: owner[q] = k
    pts = [(q[0], q[1], k) for q, k in owner.items() if k is not None]
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

# ---------------------------------------------------------------------------------------------
# Out to the shoreline.
#
# A run's ground stops at the last property line, so along the coast it stops at the houses on the
# inland side of the beach road and leaves the foreshore - reserve, car parks, the strip of bins
# along the beach - belonging to nobody. On the map that reads as the run petering out short of the
# water. These runs do work that ground, so the boundary should reach the water.
#
# Which side of the coastline is land isn't taken from the data's winding order (easy to get
# backwards, and this coastline is 80 separate ways): the run's existing shape is known to be on
# land, so the area near the coast is cut along the coastline and only the pieces still connected to
# the run's own ground are kept. Anything on the far side of the water is a separate piece and is
# dropped. Nothing is taken from another run here - where two runs both reach the same stretch of
# foreshore they both claim it, and the overlap split below then divides it the same way it divides
# a shared road.
COAST_REACH_M = float(os.environ.get('COAST_REACH_M', 120.0))
COAST_MIN_GAIN_M2 = 300.0
COAST_MAX_GROWTH = 0.15     # a foreshore strip, not a land grab - cap what any one run can gain

def load_coastline():
    try:
        raw = json.load(open(f'{WORK}/coastline.json'))
    except FileNotFoundError:
        print('  (no work/coastline.json - skipping the shoreline step; see the README to fetch it)')
        return None
    lines = []
    for l in raw:
        pts = [to_m(la, ln) for la, ln in l]
        if len(pts) >= 2: lines.append(LineString(pts))
    return unary_union(lines) if lines else None

def geoms_of(g):
    if g.is_empty: return []
    return list(g.geoms) if g.geom_type.startswith('Multi') or g.geom_type == 'GeometryCollection' else [g]

def extend_to_coast(coast):
    """Grow every run that ends near the shoreline out to the water. Returns [(key, gained m2)]."""
    gained_report = []
    coast_band = coast.buffer(COAST_REACH_M + 50)
    cut_line = coast.buffer(0.5)
    for keys in by_group.values():
        shapes = {k: (final_by_key.get(k) or run_geom(k)) for k in keys}
        shapes = {k: g for k, g in shapes.items() if g is not None and not g.is_empty}
        for k, cur in shapes.items():
            if not cur.intersects(coast_band): continue
            # the strip that is within reach of BOTH this run's own ground and the water - i.e. the
            # foreshore in front of it, not a ring of new ground all the way around it
            candidate = cur.buffer(COAST_REACH_M).intersection(coast.buffer(COAST_REACH_M))
            if candidate.is_empty: continue
            # cut along the coastline, then keep only what is still joined to this run's own land,
            # so nothing reaches across the water to the far shore
            landward = unary_union([p for p in geoms_of(candidate.difference(cut_line))
                                    if p.geom_type == 'Polygon' and p.intersects(cur)])
            if landward.is_empty: continue
            gain = landward.difference(cur)
            gain = unary_union([p for p in geoms_of(gain)
                                if p.geom_type == 'Polygon' and p.area >= COAST_MIN_GAIN_M2])
            if gain.is_empty: continue
            if gain.area > cur.area * COAST_MAX_GROWTH: continue
            merged = unary_union([cur, gain])
            if not merged.is_valid: merged = merged.buffer(0)
            final_by_key[k] = merged
            gained_report.append((k, gain.area))
    return gained_report

coast = load_coastline()
coast_report = extend_to_coast(coast) if coast is not None else []

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
streams_touched = sorted({k.split('#')[0] for k in changed})
out['version'] = int(bd.get('version', 0)) + 1
out['generated'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
out['note'] = ('Run boundaries from Vicmap property lines (each run covers its own lots and meets its neighbour down the middle of the road), '
               f'stretched to include the streets the truck drives ({", ".join(streams_touched) or "no streams this run"}), read off the '
               'route-map PDFs; where two runs\' streets share the same road, that stretch is split down the middle. '
               'Keys are stream#day#week#run (Garbage has no week). Loaded by the app on start.')

for key, n, length, growth in report:
    if n: print(f'{key:34s} +{n:2d} street pieces ({length:6.0f} m)  area +{growth*100:4.0f}%')
print(f'\nruns with a route map: {len(per_run)}   grown: {len(report) - len([r for r in report if not r[1]])}   already covered: {len([r for r in report if not r[1]])}   left alone: {len(skipped)}')
for k, why in skipped: print('  skipped', k, '-', why)
if coast is not None:
    tot = sum(a for _, a in coast_report)
    print(f'\nreached out to the shoreline: {len(coast_report)} run(s), {tot/1e6:.2f} km2 of foreshore added')
    for k, a in sorted(coast_report, key=lambda t: -t[1])[:10]:
        print(f'  {k:34s} +{a/1e4:6.1f} ha')

print(f'\n(stream, day) groups with an overlap from extension, split down the middle: {len(overlap_report)}')
for gk, touched in overlap_report:
    print(f'  {gk[0]} {gk[1]}: {len(touched)} run(s) reshaped - {", ".join(touched)}')
dest = os.path.join(WORK, 'run-boundaries.extended.json')
json.dump(out, open(dest, 'w'), separators=(',', ':'))
print('\nwrote', dest, os.path.getsize(dest), 'bytes')
if '--write' in sys.argv:
    json.dump(out, open(DATA, 'w'), separators=(',', ':')); print('replaced', DATA)
