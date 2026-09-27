"""Build data/run-routes.json: every run's route as the real streets it drives, for the app's own run maps.

For each run, all of its placed route-map pages (best placement per page - see picture_place.py, label_place.py,
replace_rec_org.py) are merged, and the route is redrawn on the OpenStreetMap road centrelines it follows: a stretch
of road counts as driven where the page's route lines run within 15 m of it for at least 35 m. So the app draws
clean streets, not a traced scan, and knows each street's name. Pages still more than 12 m from the roads are left
out rather than guessed.

    python routes_export.py            # report
    python routes_export.py --write    # ...and write ../../data/run-routes.json
"""
import datetime, json, os, sys
import numpy as np
from shapely.geometry import LineString, MultiLineString
from shapely.ops import unary_union, linemerge
from shapely.strtree import STRtree
from lib import S, REPO, KX, KY, LAT0, LNG0, to_m, load_results
from picture_place import road_dist, apply

NAME = {'REC': 'Recycling', 'ORG': 'FOGO', 'GAR': 'Garbage'}
NEAR_M, MIN_PIECE_M, MAX_PAGE_ROAD_M = 16.0, 20.0, 12.0

def key_of(tag):
    code, day, week, run, _ = tag.split('|')
    return f'{NAME[code]}#{day}#{run}' if code == 'GAR' else f'{NAME[code]}#{day}#{week}#{run}'

def ll(x, y): return [round(LAT0 + y / KY, 5), round(LNG0 + x / KX, 5)]

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
    out = {}
    for key, pls in sorted(lines_by_run.items()):
        area = unary_union([LineString(pl) for pl in pls]).buffer(NEAR_M)
        pieces, names = [], {}
        for i in tree.query(area):
            name, g = roads[i]
            inter = g.intersection(area)
            for part in getattr(inter, 'geoms', [inter]):
                if part.is_empty or part.geom_type != 'LineString' or part.length < MIN_PIECE_M: continue
                pieces.append((name, part.simplify(2.0))); names[name] = names.get(name, 0) + part.length
        if not pieces: continue
        # pieces joined up per street, each line carrying its street's name (n) for notes and the street list
        by_name = {}
        for nm, g in pieces: by_name.setdefault(nm, []).append(g)
        lines, km = [], 0.0
        for nm, gs in by_name.items():
            merged = linemerge(MultiLineString(gs)) if len(gs) > 1 else gs[0]
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
