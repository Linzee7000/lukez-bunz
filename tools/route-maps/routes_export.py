"""Build data/run-routes.json: every run's route as the real streets it drives, for the app's own run maps.

For each run, all of its placed route-map pages (best placement per page - see picture_place.py, label_place.py,
replace_rec_org.py) are merged, and the route is redrawn on the OpenStreetMap road centrelines it follows: a stretch
of road counts as driven where the page's route lines run within 15 m of it for at least 35 m. So the app draws
clean streets, not a traced scan, and knows each street's name. Pages still more than 12 m from the roads are left
out rather than guessed.

    python routes_export.py            # report
    python routes_export.py --write    # ...and write ../../data/run-routes.json
"""
import csv, datetime, json, os, re, sys
import numpy as np
from shapely.geometry import LineString, MultiLineString, MultiPoint, Point
from shapely.ops import unary_union, linemerge, substring
from shapely.strtree import STRtree
from lib import S, REPO, KX, KY, LAT0, LNG0, to_m, load_results
from picture_place import road_dist, apply

NAME = {'REC': 'Recycling', 'ORG': 'FOGO', 'GAR': 'Garbage'}
NEAR_M, MIN_PIECE_M, MAX_PAGE_ROAD_M = 16.0, 20.0, 12.0

def key_of(tag):
    code, day, week, run, _ = tag.split('|')
    return f'{NAME[code]}#{day}#{run}' if code == 'GAR' else f'{NAME[code]}#{day}#{week}#{run}'

def ll(x, y): return [round(LAT0 + y / KY, 5), round(LNG0 + x / KX, 5)]

def norm_street(t):
    t = re.sub(r'[^a-z ]', ' ', str(t).lower().replace('-', ' '))
    w = [ABBR.get(x, x) for x in t.split()]
    return ' '.join(w)
ABBR = {'rd': 'road', 'st': 'street', 'ct': 'court', 'ave': 'avenue', 'av': 'avenue', 'dr': 'drive', 'cres': 'crescent', 'pde': 'parade', 'pl': 'place',
        'gr': 'grove', 'cl': 'close', 'hwy': 'highway', 'tce': 'terrace', 'la': 'lane', 'cct': 'circuit', 'bvd': 'boulevard', 'esp': 'esplanade'}

def houses_by_run():
    """{run key: {normalised street: [(x, y), ...]}} from the master list, for every stream"""
    out = {}
    with open(f'{S}/master.csv', newline='', encoding='utf8') as f:
        for row in csv.DictReader(f):
            try: x, y = to_m(float(row['Lat']), float(row['Lng']))
            except Exception: continue
            addr = row['Address'].split(',')[0]
            addr = re.sub(r'^(unit|shop|flat|apt|suite|villa|lot)\s*[\w/-]*\s*', '', addr, flags=re.I)
            street = norm_street(re.sub(r'^[\d\s/\-A-Za-z]*?\d+[A-Za-z]?\s+', '', addr))
            if not street: continue
            day, wk = row['Solo Collection Day'].strip(), row['Solo Week Cycle'].strip().upper()
            for col, name, has_week in (('Solo Garbage Run', 'Garbage', False), ('Solo Recycling Run', 'Recycling', True), ('Solo FOGO Run', 'FOGO', True)):
                r = (row.get(col) or '').strip()
                if not r or not day: continue
                key = f'{name}#{day}#{wk}#{r}' if has_week else f'{name}#{day}#{r}'
                out.setdefault(key, {}).setdefault(street, []).append((x, y))
    return out

def _group(pieces):
    d = {}
    for nm, g in pieces: d.setdefault(nm, []).append(g)
    return d

def _merge(u):
    return linemerge(u) if u.geom_type in ('MultiLineString', 'GeometryCollection') else u

def _flat(g): return [x for x in getattr(g, 'geoms', [g]) if x.geom_type == 'LineString' and x.length >= 5]

def run(write):
    roads = [(r.get('name') or '', LineString([to_m(a, b) for a, b in r['pts']])) for r in json.load(open(f'{S}/roads.json')) if len(r['pts']) > 1]
    tree = STRtree([g for _, g in roads])
    lines_by_run, skipped = {}, 0
    for code in ('REC', 'ORG', 'GAR'):
        routes, results = load_results(code)
        for tag, r in results.items():
            if tag not in routes: continue
            pls = [[(x * KX, y * KY) for x, y in pl] for v in routes[tag].values() for pl in v if len(pl) > 1]
            if not pls: continue
            pts = np.vstack([np.array(pl) for pl in pls])
            if road_dist(np.eye(3), pts) > MAX_PAGE_ROAD_M: skipped += 1; continue
            lines_by_run.setdefault(key_of(tag), []).extend(pls)
    houses = houses_by_run()
    out = {}
    for key in sorted(set(lines_by_run) | set(houses)):
        pls = lines_by_run.get(key, [])
        pieces, names, short = [], {}, []
        if pls:
            area = unary_union([LineString(pl) for pl in pls]).buffer(NEAR_M)
            for i in tree.query(area):
                name, g = roads[i]
                inter = g.intersection(area)
                for part in getattr(inter, 'geoms', [inter]):
                    if part.is_empty or part.geom_type != 'LineString': continue
                    if part.length < MIN_PIECE_M: short.append((name, part)); continue
                    pieces.append((name, part.simplify(2.0))); names[name] = names.get(name, 0) + part.length
        # the streets the run's houses are on (from their addresses), first house to last, so a street the
        # route map missed - or a run with no usable map page - still has its streets drawn
        for st_name, pts in houses.get(key, {}).items():
            P = np.array(pts)
            for i in tree.query(MultiPoint([tuple(q) for q in P]).buffer(60)):
                name, g = roads[i]
                if norm_street(name) != st_name: continue
                d = np.array([g.distance(Point(q)) for q in P]); near = P[d <= 45]
                if not len(near): continue
                along = sorted(g.project(Point(q)) for q in near)
                a0, a1 = max(0.0, along[0] - 20), min(g.length, along[-1] + 20)
                if a1 - a0 < 10: continue
                seg = substring(g, a0, a1)
                if seg.geom_type != 'LineString' or seg.length < 10: continue
                pieces.append((name, seg.simplify(2.0))); names[name] = names.get(name, 0) + seg.length
        if not pieces: continue
        # short bits at corners are kept when both ends meet the route
        kept = unary_union([g for _, g in pieces])
        for name, part in short:
            a, z = Point(part.coords[0]), Point(part.coords[-1])
            if kept.distance(a) < 6 and kept.distance(z) < 6: pieces.append((name, part))
        # one clean line per street (overlapping pieces from the map and from the addresses joined)
        pieces = [(nm, g) for nm, gs in _group(pieces).items() for g in _flat(_merge(unary_union(gs)))]
        # pieces joined up per street, each line carrying its street's name (n) for notes and the street list
        by_name = {}
        for nm, g in pieces: by_name.setdefault(nm, []).append(g)
        lines, km = [], 0.0
        for nm, gs in by_name.items():
            merged = _merge(MultiLineString(gs)) if len(gs) > 1 else gs[0]
            for g in getattr(merged, 'geoms', [merged]):
                km += g.length; lines.append(dict(n=nm, c=[ll(x, y) for x, y in g.coords]))
        out[key] = dict(km=round(km / 1000, 1), streets=[n for n, _ in sorted(names.items(), key=lambda kv: -kv[1]) if n], lines=lines)
    size = len(json.dumps(out, separators=(',', ':')))
    print(f'{len(out)} runs, {sum(len(v['lines']) for v in out.values())} street pieces, {sum(v["km"] for v in out.values()):.0f} km; '
          f'{skipped} pages left out (> {MAX_PAGE_ROAD_M:.0f} m from the roads); {size // 1024} KB')
    if write:
        doc = dict(version=1, generated=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
                   note='Each run\'s route as the OpenStreetMap streets it drives, from the placed run route maps (tools/route-maps/routes_export.py).',
                   runs=out)
        json.dump(doc, open(os.path.join(REPO, 'data', 'run-routes.json'), 'w'), separators=(',', ':'))
        print('wrote data/run-routes.json')

if __name__ == '__main__':
    run('--write' in sys.argv)
