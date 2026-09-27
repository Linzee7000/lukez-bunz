"""Rebuild SOME run boundaries in data/run-boundaries.json, leaving every other run exactly as it is.

For runs whose saved boundary had gone wrong (filed under the wrong run, or holding few of its own houses):
  1. the base outline comes from the app's own property-line builder (lbParcels._t.buildRunOutlines - "runs meet
     halfway down the road between them"), exported from the app as {key: [ring, ...]} (main ring first, [lat, lng])
  2. the streets the run drives (data/run-routes.json, from the placed route maps) are added as a corridor
     BUFFER_M each side, where they run outside the base outline - the same stretch extend_boundaries.py does
  3. any ground another run of the same stream, day and week already has is cut away, so nothing overlaps - except
     right round the run's own houses (HOUSE_M), which it keeps even where a neighbour's old boundary strays over them
  4. pieces with none of the run's houses in them, and more than NEAR_M from a piece that has, are dropped (they come
     from bin dots or route pages placed far from the run)
A run with (almost) no houses of its own in the house list but a placed route map (a chopped run) is built from
its route corridor alone. Runs named with no day ("Unknown Day") are removed, with their aliases.

    python rebuild_boundaries.py <outlines.json> [--write]
"""
import csv, datetime, json, math, os, sys
from shapely.geometry import Polygon, LineString, MultiPolygon, MultiPoint
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.path.join(HERE, '..', '..', 'data'))
LAT0, LNG0 = -38.30, 144.95
KX = 111320 * math.cos(math.radians(LAT0)); KY = 110540.0
BUFFER_M, ROUTE_ONLY_M, HOUSE_M, NEAR_M = 14.0, 40.0, 15.0, 500.0
def m(lat, lng): return ((lng - LNG0) * KX, (lat - LAT0) * KY)
def ll(x, y): return [round(LAT0 + y / KY, 5), round(LNG0 + x / KX, 5)]
def poly(ring): return Polygon([m(a, b) for a, b in ring]).buffer(0) if len(ring) >= 3 else None
def group_of(key):
    p = key.split('#'); return (p[0], p[1], p[2] if len(p) == 4 else '')

def houses_by_run():
    """{run key: [(x, y), ...]} from the master house list (tools/route-maps/work/master.csv)"""
    out = {}
    with open(os.path.join(HERE, 'work', 'master.csv'), newline='', encoding='utf8') as f:
        for r in csv.DictReader(f):
            try: xy = m(float(r['Lat']), float(r['Lng']))
            except Exception: continue
            d, w = r['Solo Collection Day'].strip(), r['Solo Week Cycle'].strip().upper()
            for col, st, has_week in (('Solo Garbage Run', 'Garbage', False), ('Solo Recycling Run', 'Recycling', True), ('Solo FOGO Run', 'FOGO', True)):
                v = (r.get(col) or '').strip()
                if v and d: out.setdefault(f'{st}#{d}#{w}#{v}' if has_week else f'{st}#{d}#{v}', []).append(xy)
    return out

def main(outlines_path, write, route_only=()):
    doc = json.load(open(os.path.join(DATA, 'run-boundaries.json')))
    B, E, A = doc['boundaries'], doc.get('extras', {}), doc.get('aliases', {})
    routes = json.load(open(os.path.join(DATA, 'run-routes.json')))['runs']
    built = json.load(open(outlines_path)) if outlines_path else {}
    todo = list(built) + [k for k in route_only if k not in built]
    # everything else as it stands, to cut overlaps against
    shape = {}
    for k, ring in B.items():
        if k in todo: continue
        ps = [poly(ring)] + [poly(r) for r in E.get(k, [])]
        shape[k] = unary_union([p for p in ps if p is not None and not p.is_empty])
    report, H = [], houses_by_run()
    for key in todo:
        base = unary_union([p for p in (poly(r) for r in built.get(key, [])) if p is not None and not p.is_empty]) if key in built else None
        lines = [LineString([m(a, b) for a, b in l['c']]) for l in routes.get(key, {}).get('lines', []) if len(l['c']) > 1]
        corridor = unary_union([ln.buffer(BUFFER_M if base is not None else ROUTE_ONLY_M, cap_style=2) for ln in lines]) if lines else None
        if base is None and corridor is None: report.append((key, 'nothing to build from')); continue
        g = base if corridor is None else corridor if base is None else unary_union([base, corridor.difference(base.buffer(-1))])
        # ground another run of the same stream/day/week already covers stays theirs - except for a run built from its
        # route map alone: that's a chopped run whose houses are listed under the runs around it, so it overlaps them
        own = MultiPoint(H.get(key, [])) if H.get(key) else None
        keep = own.buffer(HOUSE_M).intersection(g) if own is not None else None
        for k2, s2 in ([] if base is None else shape.items()):
            if group_of(k2) == group_of(key) and not s2.is_empty and g.intersects(s2):
                g = g.difference(s2 if keep is None else s2.difference(keep))
        g = g.buffer(0)
        parts = [p for p in (g.geoms if isinstance(g, MultiPolygon) else [g]) if p.area > 400]
        if own is not None and base is not None:
            homed = [p for p in parts if p.buffer(1).intersects(own)]
            if homed:
                near = unary_union(homed).buffer(NEAR_M)
                parts = homed + [p for p in parts if p not in homed and p.intersects(near)]
        parts = sorted(parts, key=lambda p: -p.area)
        if not parts: report.append((key, 'nothing left after trimming')); continue
        B[key] = [ll(x, y) for x, y in parts[0].exterior.coords]
        if len(parts) > 1: E[key] = [[ll(x, y) for x, y in p.exterior.coords] for p in parts[1:]]
        else: E.pop(key, None)
        shape[key] = unary_union(parts)
        report.append((key, f'{len(parts)} piece(s), {sum(p.area for p in parts) / 1e6:.2f} km2' + (' (from base + streets driven)' if base is not None else ' (from its route map alone)')))
    for k in [k for k in list(B) if '#Unknown Day#' in k]:
        B.pop(k, None); E.pop(k, None); report.append((k, 'removed (no day, no houses)'))
    for a in [a for a, t in A.items() if t not in B]: A.pop(a); report.append((a, 'alias removed'))
    doc['generated'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    for r in report: print(' ', *r)
    if write:
        json.dump(doc, open(os.path.join(DATA, 'run-boundaries.json'), 'w'), separators=(',', ':'))
        print('wrote data/run-boundaries.json')

if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    ro = [a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--route-only=')]
    main(args[0] if args else None, '--write' in sys.argv, ro)
