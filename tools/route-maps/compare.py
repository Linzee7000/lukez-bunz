"""Compare run boundaries with the recycling/FOGO route maps (PDF, title text is readable): place each
page's route lines on the map by fitting them to that run's houses, then measure how much of the route
lies inside the boundary. Garbage's route maps have unreadable title text - see identify_garbage.py.

    python compare.py             # every Recycle + Organics PDF found
    python compare.py "2.1 "      # only tags containing this text (handy for one file while testing)

Writes work/compare-results-{REC,ORG}.json and work/routes-m-{REC,ORG}.json (or with $ROUTEMAP_SUFFIX
appended, so several copies can run side by side, one per PDF - modes_export.py/extend_boundaries.py
merge every work/*-{REC,ORG,GAR}*.json).
"""
import json, re, subprocess, sys, os
import numpy as np
from lib import S, DL, STREAMS, load_houses, current_and_prior_boundaries, geom_for, page_routes, \
    densify, fit, transform_routes, measure, routes_to_ll, page_count, drop_stray_pieces

SUF = os.environ.get('ROUTEMAP_SUFFIX', '')
TITLE_RE = re.compile(r'(Monday|Tuesday|Wednesday|Thursday|Friday) Run (\d+) (Recycle|Organics) W([AB])')
CODE_OF_WORD = {'Recycle': 'REC', 'Organics': 'ORG'}

def find_pdfs():
    all_pdf = [f for f in os.listdir(DL) if f.lower().endswith('.pdf')]
    only_codes = os.environ.get('ROUTEMAP_STREAMS')   # e.g. "ORG" to skip re-processing Recycling
    wanted = set(only_codes.split(',')) if only_codes else None
    return {code: sorted(f for f in all_pdf if word.upper() in f.upper())
            for word, code in CODE_OF_WORD.items() if not wanted or code in wanted}

def run(only=None):
    NEW, OLD = current_and_prior_boundaries()
    houses_by_code = {code: load_houses(s.csv_field, s.has_week) for code, s in STREAMS.items() if s.has_week}
    pdfs_by_code = find_pdfs()
    results_by_code, routes_by_code = {c: [] for c in pdfs_by_code}, {c: {} for c in pdfs_by_code}

    for code, pdfs in pdfs_by_code.items():
        stream = STREAMS[code]; houses = houses_by_code[code]
        for pdf in pdfs:
            n = page_count(pdf)
            for page in range(1, n + 1):
                txt = subprocess.run(['pdftotext', '-f', str(page), '-l', str(page), os.path.join(DL, pdf), '-'],
                                      capture_output=True, text=True).stdout
                m = TITLE_RE.search(txt)
                if not m or CODE_OF_WORD[m.group(3)] != code: continue
                day, run_no, week = m.group(1), m.group(2), m.group(4)
                tag = f'{code}|{day}|{week}|{run_no}|{pdf} p{page}'
                if only and only not in tag: continue
                H = np.array(houses.get((day, week, run_no), []))
                lines = page_routes(pdf, page)
                allpolys = lines['green'] + lines['orange'] + lines['purple']
                if len(H) < 20 or not allpolys:
                    results_by_code[code].append(dict(tag=tag, note=f'skipped ({len(H)} houses, {len(allpolys)} route lines)'))
                    print(tag, 'skipped', len(H), len(allpolys), flush=True); continue
                pts = densify(allpolys)
                f, p = fit(pts, H)
                rm = transform_routes(lines, p)
                rm, n_dropped, len_dropped = drop_stray_pieces(rm)
                if n_dropped: print(f"  ({tag}: dropped {n_dropped} stray piece(s), {len_dropped:.0f} m - likely a legend swatch, not a street)")
                key = stream.key(day, week, run_no)
                gn, go = measure(rm, geom_for(NEW, key)), measure(rm, geom_for(OLD, key))
                rec = dict(tag=tag, houses=len(H), fit_m=round(float(f), 1), scale_m_per_pt=round(float(p[0]), 2), new=gn, old=go)
                results_by_code[code].append(rec); routes_by_code[code][tag] = routes_to_ll(rm)
                fmt = lambda g: 'n/a' if not g else f"in {g['inside']*100:4.0f}%  ≤15m {g['w15']*100:4.0f}%  ≤30m {g['w30']*100:4.0f}%  far {g['far_m']:5.0f}m"
                print(f"{tag:34s} fit {f:5.1f}m ({len(H)} houses) {gn['km'] if gn else 0:.1f}km | NEW {fmt(gn)} | OLD {fmt(go)}", flush=True)

    for code in pdfs_by_code:
        json.dump(results_by_code[code], open(f'{S}/compare-results-{code}{SUF}.json', 'w'), indent=1)
        json.dump(routes_by_code[code], open(f'{S}/routes-m-{code}{SUF}.json', 'w'))

if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else None)
