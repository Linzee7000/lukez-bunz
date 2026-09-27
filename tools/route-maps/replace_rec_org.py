"""Re-place the Recycling and FOGO route-map pages as accurately as the Garbage ones.

compare.py placed these pages by fitting each page's route to its run's houses. Checked against the real roads,
about half of the Garbage pages placed that way were 100 m+ out (only snap_modes.py hid it), so every Recycling and
FOGO page is redone here with the two better methods:
  1. its existing fit, nudged onto the roads (picture_place.refine_to_roads)
  2. a fresh placement from the street names printed on its map (label_place.place_by_labels), nudged too
Whichever sits closer to the roads and passes the checks is kept. Written to work/compare-results-{REC,ORG}zlab.json
(+ routes-m), which sort after the originals so they replace them page by page.

    python replace_rec_org.py            # both streams
    python replace_rec_org.py REC        # one stream
"""
import json, os, re, subprocess, sys, glob
import numpy as np
from lib import S, DL, STREAMS, load_houses, page_routes, densify, current_and_prior_boundaries, geom_for, measure, routes_to_ll, drop_stray_pieces, page_count
from picture_place import page_to_m_from_saved, refine_to_roads, road_dist, route_check, apply
from label_place import place_by_labels

TITLE_RE = re.compile(r'(Monday|Tuesday|Wednesday|Thursday|Friday) Run (\d+) (Recycle|Organics) W([AB])')
WORD = {'REC': 'Recycle', 'ORG': 'Organics'}

def saved(code):
    """existing placements: {tag: routes_ll} from every compare.py output for this stream"""
    routes, ok = {}, set()
    files = glob.glob(f'{S}/compare-results-*.json')
    for f in files:
        if 'zlab' in f or 'GAR' in f: continue
        rf = f.replace('compare-results', 'routes-m')
        if not os.path.exists(rf): continue
        R = json.load(open(rf))
        for r in json.load(open(f)):
            if r['tag'].startswith(code + '|') and 'fit_m' in r and r['tag'] in R: routes[r['tag']] = R[r['tag']]
    return routes

def run(code):
    st = STREAMS[code]; houses = load_houses(st.csv_field, st.has_week); NEW, OLD = current_and_prior_boundaries()
    old = saved(code)
    pdfs = sorted(f for f in os.listdir(DL) if f.lower().endswith('.pdf') and WORD[code].upper() in f.upper())
    results, routes_out, stats = [], {}, {'kept': 0, 'names': 0, 'nudged': 0, 'dropped': 0}
    for pdf in pdfs:
        for page in range(1, page_count(pdf) + 1):
            txt = subprocess.run(['pdftotext', '-f', str(page), '-l', str(page), os.path.join(DL, pdf), '-'], capture_output=True, text=True).stdout
            m = TITLE_RE.search(txt)
            if not m or m.group(3) != WORD[code]: continue
            day, run_no, week = m.group(1), m.group(2), m.group(4)
            tag = f'{code}|{day}|{week}|{run_no}|{pdf} p{page}'
            Hl = houses.get((day, week, run_no))
            L = page_routes(pdf, page)
            if not Hl or len(Hl) < 20 or not any(L.values()): continue
            H = np.array(Hl); p = densify(L['green'] + L['orange'] + L['purple'])
            cands = []
            if tag in old:
                T0 = page_to_m_from_saved(pdf, page, old[tag])
                if T0 is not None:
                    d0 = road_dist(T0, p); T1 = refine_to_roads(T0, p); d1 = road_dist(T1, p)
                    mv = float(np.sqrt(((apply(T1, p) - apply(T0, p)) ** 2).sum(1)).mean())
                    if mv < 250: cands.append(('fit, nudged' if d1 < d0 - 0.5 else 'fit', T1 if d1 < d0 else T0, min(d0, d1)))
            try: res = place_by_labels(pdf, page, H)
            except Exception as e: res = None
            if res:
                T, inl, n, med = res
                T2 = refine_to_roads(T, p); d2 = road_dist(T2, p)
                mv = float(np.sqrt(((apply(T2, p) - apply(T, p)) ** 2).sum(1)).mean())
                if moved_ok(mv) and inl >= 8 and inl >= 0.5 * n: cands.append((f'street names {inl}/{n}', T2, d2))
            good = []
            for how, T, d in cands:
                dh = route_check(apply(T, p), H)
                if d <= 10.0 and (dh <= 40.0 or how.startswith('street')): good.append((d, how, T, dh))
            if not good:
                stats['dropped'] += 1
                print(f'  {tag}: nothing placed it well ({", ".join(f"{h} {d:.1f} m" for h, _, d in cands) or "no candidate"})', flush=True)
                results.append(dict(tag=tag, note='skipped (not within 10 m of the roads either way)')); continue
            d, how, T, dh = min(good, key=lambda g: g[0])
            stats['names' if how.startswith('street') else 'nudged' if 'nudged' in how else 'kept'] += 1
            print(f'  {tag}: {how} -> {d:.1f} m from roads, {dh:.1f} m from houses', flush=True)
            rm = {k: [apply(T, pl).tolist() for pl in v] for k, v in L.items()}
            rm, _, _ = drop_stray_pieces(rm)
            key = st.key(day, week, run_no)
            results.append(dict(tag=tag, houses=len(H), fit_m=round(min(dh, 15.0), 1), road_m=round(d, 1), run_from=how,
                                new=measure(rm, geom_for(NEW, key)), old=measure(rm, geom_for(OLD, key))))
            routes_out[tag] = routes_to_ll(rm)
    json.dump(results, open(f'{S}/compare-results-{code}zlab.json', 'w'), indent=1)
    json.dump(routes_out, open(f'{S}/routes-m-{code}zlab.json', 'w'))
    print(code, stats, flush=True)

def moved_ok(mv): return mv < 150

def run_orphans(code):
    """Pages whose run has no houses of its own in the master list (a chopped run like Thursday 228 Week B: its houses
    are listed under the runs it was chopped from). Placed by street names alone, searching round all of that day's
    houses, and kept only when the names agree strongly and the route sits on the roads. -> *-{code}zorph.json"""
    st = STREAMS[code]; houses = load_houses(st.csv_field, st.has_week); NEW, OLD = current_and_prior_boundaries()
    pdfs = sorted(f for f in os.listdir(DL) if f.lower().endswith('.pdf') and WORD[code].upper() in f.upper())
    results, routes_out = [], {}
    for pdf in pdfs:
        for page in range(1, page_count(pdf) + 1):
            txt = subprocess.run(['pdftotext', '-f', str(page), '-l', str(page), os.path.join(DL, pdf), '-'], capture_output=True, text=True).stdout
            m = TITLE_RE.search(txt)
            if not m or m.group(3) != WORD[code]: continue
            day, run_no, week = m.group(1), m.group(2), m.group(4)
            if len(houses.get((day, week, run_no), [])) >= 20: continue
            L = page_routes(pdf, page)
            if not any(L.values()): continue
            dayH = np.array([p for (d, w, r), v in houses.items() if d == day for p in v])
            tag = f'{code}|{day}|{week}|{run_no}|{pdf} p{page}'
            res = place_by_labels(pdf, page, dayH)
            if not res: print(f'  {tag}: no house list for this run, and too few street names'); continue
            T, inl, n, med = res
            p = densify(L['green'] + L['orange'] + L['purple'])
            T2 = refine_to_roads(T, p); d = road_dist(T2, p)
            ok = d <= 10 and inl >= 15 and inl >= 0.7 * n
            print(f'  {tag}: {inl}/{n} names agree, {d:.1f} m from roads -> {"PLACED" if ok else "rejected"}', flush=True)
            if not ok: continue
            rm = {k: [apply(T2, pl).tolist() for pl in v] for k, v in L.items()}
            rm, _, _ = drop_stray_pieces(rm)
            key = st.key(day, week, run_no)
            results.append(dict(tag=tag, houses=0, fit_m=round(med, 1), road_m=round(d, 1), run_from=f'street names {inl}/{n}, no house list',
                                new=measure(rm, geom_for(NEW, key)), old=measure(rm, geom_for(OLD, key))))
            routes_out[tag] = routes_to_ll(rm)
    json.dump(results, open(f'{S}/compare-results-{code}zorph.json', 'w'), indent=1)
    json.dump(routes_out, open(f'{S}/routes-m-{code}zorph.json', 'w'))

if __name__ == '__main__':
    if '--orphans' in sys.argv:
        for c in [a for a in sys.argv[1:] if a in ('REC', 'ORG')] or ['REC', 'ORG']: run_orphans(c)
    else:
        for c in (sys.argv[1:] or ['REC', 'ORG']): run(c)
