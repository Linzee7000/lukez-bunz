"""Read each Garbage route-map page's run number off the page, and fit that page's route to the ground.

The Garbage PDFs export with a broken font: every character comes out as an unrelated codepoint, so
"Monday Run 201 Garbage" extracts as "DŽŶĚĂǇZƵŶϮϬϭ'ĂƌďĂŐĞ". That used to mean the run number couldn't
be read at all, and this script instead *guessed* it by fitting each page's route against every run
that services that day and keeping only unambiguous winners - which worked, but could only place
about a quarter of the pages.

The substitution turned out to be consistent and identical across all five day files, so
garbage_font.py simply undoes it and the run number is read directly. Geometry is now only used to
place the page on the ground, not to work out which run it is. Pages whose title can't be read
(detail/inset pages with no title block) fall back to the old geometric identification.

    python identify_garbage.py             # every Garbage PDF found
    python identify_garbage.py Monday      # just one day, for a quicker test run

Writes work/compare-results-GAR.json and work/routes-m-GAR.json, in the same shape compare.py writes for
REC/ORG, so modes_export.py and extend_boundaries.py pick this up automatically alongside them.
"""
import csv, json, re, sys, os
import numpy as np
from lib import S, DL, current_and_prior_boundaries, geom_for, page_routes, densify, fit, \
    coarse_candidates, transform_routes, measure, routes_to_ll, page_count, drop_stray_pieces, to_m
from garbage_font import read_title, page_texts

DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
MAX_FIT_M = 15.0
SHORTLIST_N = 3        # candidates worth a precise (expensive) fit, by coarse score
MIN_FIT_GAP = 1.6      # the winning candidate's precise fit cost must be this many times BETTER (lower) than the runner-up's

def find_pdfs():
    out = {}
    for f in os.listdir(DL):
        if not f.lower().endswith('.pdf') or 'garbage' not in f.lower(): continue
        day = next((d for d in DAYS if d.lower() in f.lower()), None)
        if day: out[day] = f
    return out

def load_houses_by_run():
    houses = {}
    with open(f'{S}/master.csv', newline='', encoding='utf8') as f:
        for row in csv.DictReader(f):
            run = (row.get('Solo Garbage Run') or '').strip()
            if not run: continue
            try: lat, lng = float(row['Lat']), float(row['Lng'])
            except Exception: continue
            houses.setdefault((row['Solo Collection Day'].strip(), run), []).append(to_m(lat, lng))
    return houses

def run(only_day=None):
    NEW, OLD = current_and_prior_boundaries()
    houses = load_houses_by_run()
    pdfs = find_pdfs()
    if only_day: pdfs = {d: f for d, f in pdfs.items() if d == only_day}
    print('Garbage PDFs found:', pdfs)

    results, routes_out = [], {}
    for day, pdf in pdfs.items():
        candidates = sorted({run for (d, run) in houses if d == day}, key=lambda r: int(r))
        cand_H = {r: np.array(houses[(day, r)]) for r in candidates if len(houses[(day, r)]) >= 20}
        print(f'\n{day}: {len(cand_H)} candidate runs {sorted(cand_H, key=int)}')
        n = page_count(pdf)
        texts = page_texts(pdf)
        for page in range(1, n + 1):
            tag = f'GAR|{day}||?|{pdf} p{page}'
            lines = page_routes(pdf, page)
            allpolys = lines['green'] + lines['orange'] + lines['purple']
            if not allpolys:
                results.append(dict(tag=tag, note='skipped (no route lines)')); print(' ', tag, 'skipped: no route lines'); continue
            pts = densify(allpolys)

            # The run number, read straight off the page (see garbage_font.py). When it's there this
            # is the answer - no guessing, so the page just needs placing on the ground.
            title = read_title(texts.get(page, ''))
            titled = bool(title and title[1] in cand_H)
            if title and not titled:
                print(f'  p{page}: title says {title[0]} run {title[1]}, which has no houses on {day} - falling back to geometry')
            if titled:
                if title[0] != day:
                    print(f"  p{page}: title day {title[0]} != filename day {day} - trusting the title")
                best_run = title[1]
                best_H = cand_H[best_run]
                f_cost, p = fit(pts, best_H)
                runner_up = float('inf')     # nothing to be ambiguous with - the page says which run it is
                src = 'title'
            else:
                # No readable title (detail/inset pages). Fall back to identifying by geometry: fit the
                # page against every run that services this day and demand a clear, precise winner.
                coarse = []
                for r, H in cand_H.items():
                    cands = coarse_candidates(pts, H, n_scales=14, normalize=True)
                    coarse.append((cands[0][0], r, H))
                coarse.sort(key=lambda t: -t[0])
                precise = []
                for _, r, H in coarse[:SHORTLIST_N]:
                    f_cost, p = fit(pts, H)   # redo the (unnormalised) coarse search for this candidate - fit()'s own refinement needs its own starting points
                    precise.append((f_cost, r, H, p))
                precise.sort(key=lambda t: t[0])
                f_cost, best_run, best_H, p = precise[0]
                runner_up = precise[1][0] if len(precise) > 1 else 1e9
                src = 'geometry'
            tag = f'GAR|{day}||{best_run}|{pdf} p{page}'
            if runner_up < f_cost * MIN_FIT_GAP:
                results.append(dict(tag=tag, note=f'skipped (ambiguous: run {best_run} {f_cost:.1f}m vs run {precise[1][1]} {runner_up:.1f}m)'))
                print(f'  p{page}: AMBIGUOUS - run {best_run} ({f_cost:.1f}m) vs run {precise[1][1]} ({runner_up:.1f}m) - skipped')
                continue
            if f_cost > MAX_FIT_M:
                results.append(dict(tag=tag, note=f'skipped (best guess run {best_run}, fit {f_cost:.1f}m too poor)'))
                print(f'  p{page}: run {best_run} identified but fit is poor ({f_cost:.1f}m) - skipped')
                continue
            rm = transform_routes(lines, p)
            rm, n_dropped, len_dropped = drop_stray_pieces(rm)
            if n_dropped: print(f'    (dropped {n_dropped} stray piece(s), {len_dropped:.0f} m)')
            key = f'Garbage#{day}#{best_run}'
            gn, go = measure(rm, geom_for(NEW, key)), measure(rm, geom_for(OLD, key))
            rec = dict(tag=tag, houses=len(best_H), fit_m=round(float(f_cost), 1), scale_m_per_pt=round(float(p[0]), 2), run_from=src, new=gn, old=go)
            results.append(rec); routes_out[tag] = routes_to_ll(rm)
            fmt = lambda g: 'n/a' if not g else f"in {g['inside']*100:4.0f}%  ≤15m {g['w15']*100:4.0f}%  far {g['far_m']:5.0f}m"
            gap = 'from title' if src == 'title' else f'vs runner-up {runner_up:5.1f}m'
            print(f"  p{page}: run {best_run} ({gap}, fit {f_cost:5.1f}m)  ({len(best_H)} houses) {gn['km'] if gn else 0:.1f}km | NEW {fmt(gn)} | OLD {fmt(go)}")

    suf = os.environ.get('ROUTEMAP_SUFFIX', '')
    json.dump(results, open(f'{S}/compare-results-GAR{suf}.json', 'w'), indent=1)
    json.dump(routes_out, open(f'{S}/routes-m-GAR{suf}.json', 'w'))
    ok = [r for r in results if 'fit_m' in r]
    byt = sum(1 for r in ok if r.get('run_from') == 'title')
    print(f'\n{len(ok)} of {len(results)} pages identified and placed '
          f'({byt} from the page title, {len(ok)-byt} by geometry); '
          f'wrote work/compare-results-GAR.json, work/routes-m-GAR.json')

if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else None)
