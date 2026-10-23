"""Street shapes for the run maps, from OpenStreetMap.

The route data (data/run-routes.json) only has the stretches of each street read off the route PDFs, and many stop short of
the street they meet (Charles St, Coles Ct on 219A Friday). The run map makes a hanging street follow its own street, by name,
to the next street of the route; this file gives it the real shape of every street named in any run, so that works with no
signal and can be tested. Run by the "Run map streets" GitHub workflow (the build machine can reach Overpass).

    python3 tools/streets/fetch_streets.py            # writes data/run-streets.json
Format: {version, generated, ways: [[name, [lat, lng, lat, lng, ...]], ...]}  (5 decimals, ~1 m)
"""
import json, re, time, urllib.request, urllib.parse, datetime, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
URLS = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter', 'https://overpass.private.coffee/api/interpreter']

def norm(n):   # the run map's normSt
    s = str(n or '').lower()
    for a, b in [(r'\bstreet\b', 'st'), (r'\broad\b', 'rd'), (r'\bavenue\b', 'ave'), (r'\bcourt\b', 'ct'), (r'\bdrive\b', 'dr'), (r'\bcrescent\b', 'cres'), (r'\bplace\b', 'pl'), (r'\bboulevard\b', 'bvd')]:
        s = re.sub(a, b, s)
    return re.sub(r'[^a-z0-9]+', '', s)

def overpass(q):
    for attempt in range(6):
        url = URLS[attempt % len(URLS)]
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode({'data': q}).encode(), headers={'User-Agent': 'lukez-bunz run map streets'})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)['elements']
        except Exception as e:
            print('  retry', url, e, file=sys.stderr); time.sleep(10 + attempt * 10)
    raise SystemExit('overpass failed')

def main():
    runs = json.load(open(os.path.join(ROOT, 'data/run-routes.json')))['runs']
    names = set()
    la, lo = [], []
    for r in runs.values():
        for l in r['lines']:
            if l.get('n'): names.add(norm(l['n']))
            for p in l['c']: la.append(p[0]); lo.append(p[1])
    s, n, w, e = min(la) - 0.01, max(la) + 0.01, min(lo) - 0.01, max(lo) + 0.01
    step = 0.1; ways = {}
    y = s
    while y < n:
        x = w
        while x < e:
            q = '[out:json][timeout:170];way["highway"]["name"]["highway"!~"footway|path|steps|cycleway|pedestrian|bridleway|corridor|proposed|construction|platform"](%.4f,%.4f,%.4f,%.4f);out geom;' % (y, x, min(n, y + step), min(e, x + step))
            els = overpass(q)
            for el in els:
                nm = el.get('tags', {}).get('name')
                if not nm or norm(nm) not in names or len(el.get('geometry') or []) < 2: continue
                flat = []
                for p in el['geometry']: flat += [round(p['lat'], 5), round(p['lon'], 5)]
                ways[el['id']] = [nm, flat]
            print('tile', round(y, 2), round(x, 2), len(els), 'kept so far', len(ways))
            time.sleep(3); x += step
        y += step
    out = {'version': 1, 'generated': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'),
           'note': 'OpenStreetMap ways named like a street of any run (tools/streets/fetch_streets.py). (c) OpenStreetMap contributors, ODbL.',
           'ways': [ways[k] for k in sorted(ways)]}
    json.dump(out, open(os.path.join(ROOT, 'data/run-streets.json'), 'w'), separators=(',', ':'))
    print('ways', len(out['ways']))

if __name__ == '__main__':
    main()
