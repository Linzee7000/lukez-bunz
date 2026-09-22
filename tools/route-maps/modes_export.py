"""Build data/street-modes.json (the "reverse in / drive in" overlay) from every stream's route-map results:
purple = reverse in / drive out, orange = drive in / reverse out. Reads every work/routes-m-*.json +
work/compare-results-*.json (Recycling, FOGO, Garbage - whichever have been run), keeps only the best-placed
page for each stretch of road when pages overlap, and writes work/street-modes.json.

    python modes_export.py
    python modes_export.py --write     # ...and copies it to ../../data/street-modes.json
"""
import csv, datetime, json, re, sys
from shapely.geometry import LineString
from shapely.ops import unary_union
from lib import S, REPO, KX, KY, LAT0, LNG0, house_tree, street_for, load_results

MAX_FIT_M = 20.0
TYPE_OF_COLOUR = {'purple': 'reverse-in-drive-out', 'orange': 'drive-reverse-out'}

def run(write=False):
    tree, addrs = house_tree()
    routes, results = {}, {}
    for code in ('REC', 'ORG', 'GAR'):
        r, res = load_results(code)
        routes.update(r); results.update(res)
    print(f'{len(results)} pages with a usable fit, across {len({t.split("|")[0] for t in results})} stream(s)')

    cover = {'purple': None, 'orange': None}
    kept = []
    order = sorted(results, key=lambda t: results[t]['fit_m'])   # best-placed pages first, so they win where pages overlap
    for tag in order:
        if results[tag]['fit_m'] > MAX_FIT_M: continue
        for colour in TYPE_OF_COLOUR:
            for pl in routes[tag].get(colour, []):
                xy = [(x * KX, y * KY) for x, y in pl]   # stored as (dlng, dlat) offsets -> metres
                if len(xy) < 2: continue
                ln = LineString(xy)
                if cover[colour] is not None: ln = ln.difference(cover[colour])
                parts = [ln] if ln.geom_type == 'LineString' else list(getattr(ln, 'geoms', []))
                for p in parts:
                    if p.is_empty or p.length < 12 or p.geom_type != 'LineString': continue
                    kept.append((colour, p, tag))
                    b = p.buffer(10)
                    cover[colour] = b if cover[colour] is None else unary_union([cover[colour], b])

    segs = []
    for colour, p, tag in kept:
        p2 = p.simplify(0.8)   # keep the file small
        mid = p.interpolate(0.5, normalized=True)
        st = street_for(mid.x, mid.y, tree, addrs)
        src = tag.split('|')[-1] if '|' in tag else tag   # the "<pdf> p<page>" part, for provenance only
        segs.append({'type': TYPE_OF_COLOUR[colour], 'street': st, 'src': src,
                     'points': [[round(LAT0 + y / KY, 5), round(LNG0 + x / KX, 5)] for x, y in p2.coords]})

    out = {'version': 1, 'generated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
           'note': 'Street driving modes read from the run route maps (PDF): purple = reverse in / drive out, orange = '
                   'drive in / reverse out. Position is approximate (placed by matching each map to its houses). Applies to all kerbside streams.',
           'segments': segs}
    dest = f'{S}/street-modes.json'
    json.dump(out, open(dest, 'w'), separators=(',', ':'))
    L = {t: sum(p.length for c, p, _ in kept if TYPE_OF_COLOUR[c] == t) / 1000 for t in TYPE_OF_COLOUR.values()}
    print(f"segments {len(segs)}  reverse-in km {L['reverse-in-drive-out']:.1f}  drive-in km {L['drive-reverse-out']:.1f}  "
          f"file bytes {len(json.dumps(out, separators=(',', ':')))}")
    if write:
        live = f'{REPO}/data/street-modes.json'
        json.dump(out, open(live, 'w'), separators=(',', ':'))
        print('replaced', live)

if __name__ == '__main__':
    run(write='--write' in sys.argv)
