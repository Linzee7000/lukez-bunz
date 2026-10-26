"""A run made of bits of other runs (227B Monday: when there are drivers enough it takes parts of 219B, 220B, 221B and 223B;
when short a driver the full runs do it all and 227B doesn't run). The master list keeps those houses in their full runs, so
227B had 3 houses and no route.

The full-run pages ("FULL RUN") show the part that goes to the split run in a section colour (#ff9900). Each full-run page is
placed by its own run's houses (fit, as compare.py does), its #ff9900 lines taken out; the split run's own page is then placed
by the houses along those lines, and its route (green / purple / orange) kept. The split run's houses are the full runs'
houses within 25 m of its route.

    ROUTEMAP_PDF_DIR=<folder with the PDF> venv/bin/python split_run.py "<pdf>" Monday B 227 219,220,221,223 [page of the split run]

Writes work/split-<day><week>-<run>.json: { key, from: [run...], lines: {green, orange, purple: [[[lat,lng]...]]},
houses: {run: [site id...]}, fit_m }."""
import json, sys, csv, math, subprocess, os, re
import numpy as np
from scipy.spatial import cKDTree
from lib import S, DL, page_routes, page_count, densify, fit, transform_routes, drop_stray_pieces, routes_to_ll, to_m

pdf, day, week, run, froms = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5].split(',')
TITLE = re.compile(r'(Monday|Tuesday|Wednesday|Thursday|Friday) Run (\d+) Recycle W([AB])')
SEC = '#ff9900'

# every house of that day and week, by run code (the bits a split run takes can also be under codes of their own that the
# app doesn't show - on Monday B: 222, 232, 234)
H = {}
with open(f'{S}/master.csv', newline='', encoding='utf8') as f:
    for row in csv.DictReader(f):
        r = (row.get('Solo Recycling Run') or '').strip()
        if r and row['Solo Collection Day'].strip() == day and row['Solo Week Cycle'].strip().upper() == week:
            try: H.setdefault(r, []).append((row['Site Id'], to_m(float(row['Lat']), float(row['Lng']))))
            except Exception: pass
for r in froms: H.setdefault(r, [])
ADDR = {}
with open(f'{S}/master.csv', newline='', encoding='utf8') as f:
    for row in csv.DictReader(f): ADDR[row['Site Id']] = row['Address'].upper()
# --keep 226:ERLANDSEN AVENUE,HOLYROOD AVENUE,... : streets the full run keeps although its page draws them in the split run's
# colour (Fox: 226 does Terry, Erlandsen, Holyrood, Mendes, Kinneil - 227A doesn't)
KEEP = {}
if '--keep' in sys.argv:
    kr, ks = sys.argv[sys.argv.index('--keep') + 1].split(':', 1)
    for st in ks.split(','): KEEP[st.strip().upper()] = kr
def kept(sid):
    a = ADDR.get(sid, '')
    for st, kr in KEEP.items():
        if re.search(r'\b' + re.escape(st) + r',', a): return kr
    return None

pages = {}
for p in range(1, page_count(pdf) + 1):
    t = subprocess.run(['pdftotext', '-f', str(p), '-l', str(p), os.path.join(DL, pdf), '-'], capture_output=True, text=True).stdout
    m = TITLE.search(t)
    if m and m.group(1) == day and m.group(3) == week: pages.setdefault(m.group(2), p)
split_page = int(sys.argv[6]) if len(sys.argv) > 6 and sys.argv[6].isdigit() else pages.get(run)
print('pages', pages, 'split page', split_page)

parts, greens, PARTS = [], [], {}
for r in froms:
    p = pages.get(r)
    if not p: print('no page for', r); continue
    L = page_routes(pdf, p, sections=True)
    pts_h = np.array([h[1] for h in H[r]])
    allp = L['green'] + L['orange'] + L['purple'] + L.get(SEC, [])
    fm, prm = fit(densify(allp), pts_h)
    # refit with the split run's own coded houses that lie on this page's lines too: the page draws the orange bits as well,
    # and fitted by the full run's houses alone the orange could sit 15-25 m off (225A Monday's Wanda Cl / Yerlata Ct block)
    if H.get(run):
        t0 = cKDTree(densify(transform_routes({'a': allp}, prm)['a'], 3.0))
        extra_h = [h[1] for h in H[run] if t0.query(h[1])[0] <= 40]
        if extra_h:
            fm2_, prm2_ = fit(densify(allp), np.array(list(pts_h) + extra_h), top_n=1, _cands=[(0, prm)])
            print(f'  {r}: refit with {len(extra_h)} houses coded {run}: {fm:.1f} -> {fm2_:.1f} m'); fm, prm = fm2_, prm2_
    rm = transform_routes({SEC: L.get(SEC, []), 'green': L['green']}, prm)
    print(f'{r}: page {p}, fit {fm:.1f} m, {len(rm[SEC])} split lines')
    if fm <= 20: parts += rm[SEC]; greens += rm['green']; PARTS[r] = rm[SEC]
if not parts: sys.exit('no split lines placed')

def street_of(sid):
    m_ = re.search(r'^[^,]*?\s([A-Z][A-Z ]+?),', ADDR.get(sid, ''))
    return re.sub(r'^ST ', 'SAINT ', m_.group(1).strip()) if m_ else ''
# --orange-names <json> {run: {street name: weight}} (the streets each page's orange pieces follow, by name): a full-run house
# counts with the split run when its street is one of those names and it is within 25 m of that page's orange - by NAME, so a
# piece placed 10-20 m off can't take the next street over (Wilson Rd, Allan St, Ibis Way did)
NAMED = {}
if '--orange-names' in sys.argv:
    ON = json.load(open(sys.argv[sys.argv.index('--orange-names') + 1]))
    SKIP = {'SAINT JOHNS WOOD ROAD'}   # (runs right beside Melbourne Rd: an orange Melbourne Rd reads as it too)
    for r, names in ON.items():
        if r not in PARTS or not PARTS[r]: continue
        tp = cKDTree(densify(PARTS[r], 2.0)); nm = {re.sub(r'^ST ', 'SAINT ', n.upper()) for n in names} - SKIP
        NAMED[r] = [sid for sid, xy in H.get(r, []) if street_of(sid) in nm and tp.query(xy)[0] <= 25 and not kept(sid)]
    print('by street name:', {r: len(v) for r, v in NAMED.items()})

# --homes: houses the master list keeps under the split run's own code (227A Monday: 1,102 of them) go back to the full run
# whose page draws their street - every full-run page of that day and week is placed by its own run's houses and each such
# house goes to the run with the nearest line. Then they are treated like the full runs' own houses (227A takes the ones
# along its orange bits), and the app shows them in that full run (split-runs.json "homes").
homes = {}
if '--homes' in sys.argv and H.get(run):
    trees = {}
    for r, p in pages.items():
        if r == run or not H.get(r): continue
        L = page_routes(pdf, p, sections=True)
        allp = L['green'] + L['orange'] + L['purple'] + L.get(SEC, [])
        fm, prm = fit(densify(allp), np.array([h[1] for h in H[r]]))
        if fm > 20: print('homes: page', p, 'for', r, 'fits badly', round(fm, 1)); continue
        rm = transform_routes({'all': allp}, prm)
        trees[r] = cKDTree(densify(rm['all'], 3.0))
    for sid, xy in H[run]:
        d = {r: t.query(xy)[0] for r, t in trees.items()}
        if kept(sid): homes[sid] = kept(sid)
        elif d: homes[sid] = min(d, key=d.get)
    from collections import Counter
    print('homes:', dict(Counter(homes.values())))
    for sid, xy in H[run]:
        if sid in homes: H.setdefault(homes[sid], []).append((sid, xy))

# houses along the split lines (from the full-run pages)
seg = densify(parts, 2.0); tree = cKDTree(seg)
near = [(r, sid, xy) for r in froms for sid, xy in H[r] if tree.query(xy)[0] <= 25]
print('houses along the split lines:', len(near))

out_lines = {'green': [], 'orange': [], 'purple': []}
fm2 = None
if split_page:
    L = page_routes(pdf, split_page)
    allp = L['green'] + L['orange'] + L['purple']
    Hn = np.array([x[2] for x in near])
    fm2, prm = fit(densify(allp), Hn)
    rm = transform_routes(L, prm); rm, nd, ld = drop_stray_pieces(rm)
    print(f'split page {split_page}: fit {fm2:.1f} m ({len(Hn)} houses)')
    if fm2 <= 20:
        out_lines = rm
        seg = densify(rm['green'] + rm['orange'] + rm['purple'], 2.0); tree = cKDTree(seg)
        near = [(r, sid, xy) for r in froms for sid, xy in H[r] if tree.query(xy)[0] <= 25]
        print('houses along its own route:', len(near))
if not any(out_lines.values()): out_lines = {'green': parts, 'orange': [], 'purple': []}
houses = {}
for r, sid, xy in near: houses.setdefault(r, []).append(sid)
res = dict(key=f'Recycling#{day}#{week}#{run}', **{'from': froms}, fit_m=None if fm2 is None else round(float(fm2), 1),
           lines=routes_to_ll(out_lines), houses=houses)
json.dump(res, open(f'{S}/split-{day}{week}-{run}.json', 'w'))
print({r: len(v) for r, v in houses.items()})

# ---- the app's data: the route redrawn on the street centrelines (named), and the run's houses ----
if '--write' in sys.argv:
    import datetime
    from shapely.geometry import LineString
    from shapely.strtree import STRtree
    ways = json.load(open(os.path.join(os.path.dirname(S), '..', '..', 'data', 'run-streets.json')))['ways']
    own = [LineString(pl) for pl in (out_lines['green'] + out_lines['orange'] + out_lines['purple'] + parts) if len(pl) > 1]
    if '--coded' in sys.argv:
        # and the streets the split run's coded houses are on (a street piece of that name within 40 m of them)
        from shapely.geometry import MultiPoint
        bystreet = {}
        for sid, xy in H.get(run, []) + [h for r_ in NAMED for h in H.get(r_, []) if h[0] in set(NAMED[r_])]:
            if kept(sid): continue
            m_ = re.search(r'^[^,]*?\s([A-Z][A-Z ]+?),', ADDR.get(sid, ''))
            if m_: bystreet.setdefault(re.sub(r'^ST ', 'SAINT ', m_.group(1).strip()), []).append(xy)
        CODED = {k: MultiPoint(v).buffer(40) for k, v in bystreet.items()}
    else: CODED = {}
    if '--coded-only' in sys.argv: own = [LineString([(0, 0), (0, 1e-6)])]   # route: only the streets of the coded houses
    tr = STRtree(own)
    lines_out, streets, km = [], set(), 0.0
    for name, flat in ways:
        if not name or name.upper() in KEEP: continue
        pts = [to_m(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]
        if len(pts) < 2: continue
        sm = []
        for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
            L = math.hypot(x1 - x0, y1 - y0); n = max(1, int(L / 5))
            for k in range(n): sm.append((x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n))
        sm.append(pts[-1])
        from shapely.geometry import Point
        near_f = [min((g.distance(Point(p)) for g in [own[i] for i in tr.query(Point(p).buffer(18))]), default=99) <= 18 for p in sm]
        nk = re.sub(r'^ST ', 'SAINT ', name.upper())
        if nk in CODED: near_f = [ok or CODED[nk].contains(Point(p)) for ok, p in zip(near_f, sm)]
        cur = []
        def flush():
            global km
            if len(cur) < 2: return
            L0 = sum(math.hypot(cur[i + 1][0] - cur[i][0], cur[i + 1][1] - cur[i][1]) for i in range(len(cur) - 1))
            if L0 < 30: return
            from lib import to_ll
            lines_out.append({'n': name, 'c': [to_ll(x, y) for x, y in cur]}); streets.add(name); km += L0
        for p, ok in zip(sm, near_f):
            if ok: cur.append(p)
            else: flush(); cur = []
        flush()
    rr_path = os.path.join(os.path.dirname(S), '..', '..', 'data', 'run-routes.json')
    rr = json.load(open(rr_path))
    rr['runs'][res['key']] = {'lines': lines_out, 'km': round(km / 1000, 1), 'streets': sorted(streets)}
    rr['generated'] = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ')
    json.dump(rr, open(rr_path, 'w'), separators=(',', ':'))
    # houses: along the split lines on the full-run pages (they mark exactly what the split run takes), within 20 m and nearer
    # them than the full run's own (green) lines - any run code of that day and week
    tree = cKDTree(densify(parts, 2.0)); tg = cKDTree(densify(greens, 2.0)) if greens else None
    def takes(xy):
        d = tree.query(xy)[0]
        return d <= 20 and (tg is None or d < tg.query(xy)[0])
    # only the full runs' own houses: a run number with no week letter (222, 232, 234...) is a summer recycle run, not part of it
    mine = {r: [sid for sid, xy in H[r] if takes(xy) and not kept(sid)] for r in froms}
    if '--coded' in sys.argv:
        # --coded (227A Monday): the master list already codes the split run's houses under its own number - those ARE the
        # orange bits, placed better than a fitted page can (225A's page sits 20-30 m off). They stay the split run's, except
        # the --keep streets, which go to their full run; full-run houses count only when right on an orange line (15 m,
        # 5 m nearer it than any green line).
        def tight(xy):
            d = tree.query(xy)[0]
            return d <= 15 and (tg is None or d + 5 < tg.query(xy)[0])
        mine = {r: [sid for sid, xy in H[r] if tight(xy) and not kept(sid)] for r in froms}
        if '--coded-only' in sys.argv: mine = {r: list(v) for r, v in NAMED.items()}   # (the fitted orange lines land 5-25 m off and took neighbouring streets: Wilson Rd, Ibis Way... - so by name only)
        mine[run] = [sid for sid, xy in H.get(run, []) if not kept(sid)]
        homes.update({sid: kept(sid) for sid, xy in H.get(run, []) if kept(sid)})
    mine = {r: v for r, v in mine.items() if v}
    sp_path = os.path.join(os.path.dirname(S), '..', '..', 'data', 'split-runs.json')
    sp = json.load(open(sp_path)) if os.path.exists(sp_path) else {'version': 1, 'runs': {}}
    sp['note'] = 'Runs made of bits of other runs (227A / 227B Monday take parts of the full runs; short a driver, the full runs do it all). The houses stay in their own runs too. homes: houses the master list codes under the split run itself, and the full run they belong to (shown there). Made by tools/route-maps/split_run.py from the route-map PDF.'
    sp['generated'] = rr['generated']
    if '--route-only' not in sys.argv:   # (227A Monday: its houses are already under 227 in the master list - only its route is needed)
        sp['runs'][res['key']] = {'from': froms, 'sites': sorted(set(s for v in mine.values() for s in v))}
        if homes: sp['runs'][res['key']]['homes'] = {k: homes[k] for k in sorted(homes)}
        json.dump(sp, open(sp_path, 'w'), indent=0)
    print('wrote', len(lines_out), 'street pieces,', round(km / 1000, 1), 'km;', sum(len(v) for v in mine.values()), 'houses', {r: len(v) for r, v in mine.items()})
    print(sorted(streets))
