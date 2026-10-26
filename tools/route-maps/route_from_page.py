"""Rebuild one run's route in data/run-routes.json from one route-map page (or several), for when a run's page title is wrong
(Friday Week A, from May 2026: 219 and 225 swapped, so the page titled 219 is 225's run and the one titled 225 is 219's).

    ROUTEMAP_PDF_DIR=<dir> venv/bin/python route_from_page.py <pdf> <page[,page]> <Stream#Day#Week#Run> [--write]

Each page is placed by the run's own houses (fit, as compare.py does), every route line on it kept, and the route redrawn
on the street centrelines (data/run-streets.json): a named street piece within 18 m of a page line, at least 30 m long."""
import json, sys, csv, math, os, datetime
import numpy as np
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree
from lib import S, REPO, page_routes, densify, fit, transform_routes, to_m, to_ll

pdf, pages, key = sys.argv[1], [int(p) for p in sys.argv[2].split(',')], sys.argv[3]
stream, day, week, run = key.split('#')
H = []
for r in csv.DictReader(open(f'{S}/master.csv', encoding='utf8')):
    if r['Solo Collection Day'].strip() == day and r['Solo Week Cycle'].strip() == week and r['Solo Recycling Run'].strip() == run:
        try: H.append(to_m(float(r['Lat']), float(r['Lng'])))
        except Exception: pass
H = np.array(H)
own = []
for p in pages:
    L = page_routes(pdf, p, sections=True); allp = [l for v in L.values() for l in v]
    fm, prm = fit(densify(allp), H)
    print(f'page {p}: fit {fm:.1f} m ({len(H)} houses)')
    if fm > 20: sys.exit('fit too poor to use')
    own += [LineString(pl) for pl in transform_routes({'a': allp}, prm)['a'] if len(pl) > 1]
tr = STRtree(own)
ways = json.load(open(os.path.join(REPO, 'data', 'run-streets.json')))['ways']
lines_out, streets, km = [], set(), 0.0
for name, flat in ways:
    if not name: continue
    pts = [to_m(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]
    if len(pts) < 2: continue
    sm = []
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / 5))
        for k in range(n): sm.append((x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n))
    sm.append(pts[-1])
    ok = [min((own[i].distance(Point(q)) for i in tr.query(Point(q).buffer(18))), default=99) <= 18 for q in sm]
    cur = []
    def flush():
        global km
        if len(cur) < 2: return
        L0 = sum(math.hypot(cur[i + 1][0] - cur[i][0], cur[i + 1][1] - cur[i][1]) for i in range(len(cur) - 1))
        if L0 < 30: return
        lines_out.append({'n': name, 'c': [to_ll(x, y) for x, y in cur]}); streets.add(name); km += L0
    for q, o in zip(sm, ok):
        if o: cur.append(q)
        else: flush(); cur = []
    flush()
print(f'{key}: {len(lines_out)} street pieces, {km / 1000:.1f} km, {len(streets)} streets')
d = np.array([0])
if '--write' in sys.argv:
    p = os.path.join(REPO, 'data', 'run-routes.json'); rr = json.load(open(p))
    rr['runs'][key] = {'lines': lines_out, 'km': round(km / 1000, 1), 'streets': sorted(streets)}
    rr['generated'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    json.dump(rr, open(p, 'w'), separators=(',', ':'))
    print('written')
