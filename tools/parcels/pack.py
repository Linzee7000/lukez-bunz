"""Pack the exported parcel cache into the small file the app ships (data/parcels.json).

Why this exists: the property-boundaries layer gets its lot geometry from the Vicmap Parcel
ArcGIS service, one ~440x550m tile at a time, and caches what it matches in IndexedDB. That
works, but the cache only ever lives on the phone that did the fetching - a new phone, a new
driver or a cleared browser has to grind through thousands of ArcGIS calls again, which is
slow, needs signal, and is the one part of the app that can be rate-limited by someone else.
Lot boundaries barely change, so we ship them instead.

The saving comes from two things: coordinates are stored as deltas between consecutive points
(neighbouring points differ in the 5th decimal, so the deltas are small integers that gzip
flattens), and everything derivable is dropped - the bounding box is recomputed from the ring,
and the SPI is usually just "lot\\plan" so it's only stored for the ~5% where it isn't.

    python3 receive.py                          # then, in the app's console:
    #   await fetch('http://127.0.0.1:8765/save',{method:'POST',body:JSON.stringify(lbParcels._t.getStore())})
    python3 pack.py                             # work/store-raw.json -> work/parcels.json
    python3 pack.py --write                     # ...and copy to ../../data/parcels.json
"""
import datetime, gzip, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
SRC = os.path.join(HERE, 'work', 'store-raw.json')
OUT = os.path.join(HERE, 'work', 'parcels.json')
LIVE = os.path.join(REPO, 'data', 'parcels.json')

SCALE = 100000      # ~1m; measured worst round-trip error 0.42m, far under what a phone map shows
NOTE = ('Vicmap property lot boundaries for the service area, and which lot each house sits on. '
        'Shipped so the boundaries layer works offline and on a fresh phone without re-fetching '
        'from the Vicmap Parcel ArcGIS service. Coordinates are deltas scaled by 1e5 (~1m). '
        'Regenerate with tools/parcels/ (see its README) when lots change.')
ATTRIB = 'Lot boundaries from Vicmap Parcel, State Government of Victoria.'


def enc(flat):
    """[lng,lat,lng,lat,...] floats -> delta-encoded ints."""
    out, px, py = [], 0, 0
    for i in range(0, len(flat) - 1, 2):
        x = round(flat[i] * SCALE); y = round(flat[i + 1] * SCALE)
        out.append(x - px); out.append(y - py)
        px, py = x, y
    return out


def run(write=False):
    store = json.load(open(SRC))
    parcels, sites = store['parcels'], store['sites']

    P = {}
    for pid, p in parcels.items():
        lot, plan = p.get('l', ''), p.get('n', '')
        rec = [enc(p['o']), p.get('a', 0), lot, plan]
        spi = p.get('s', '')
        holes = [enc(h) for h in (p.get('h') or [])]
        # Trailing fields only where they're actually needed - the SPI is "lot\plan" for 95% of
        # lots, and fewer than 100 have a hole in them.
        if holes: rec += [spi if spi != lot + '\\' + plan else '', holes]
        elif spi != lot + '\\' + plan: rec.append(spi)
        P[pid] = rec

    S = {}
    for key, e in sites.items():
        if e.get('x'): S[key] = 0          # known to have no lot - remember, don't re-try forever
        else: S[key] = [e['p'], e.get('m', 0), e.get('d', 0)]

    out = {
        'version': 1,
        'generated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
        'note': NOTE,
        'attribution': ATTRIB,
        'scale': SCALE,
        'parcels': P,
        'sites': S,
    }
    blob = json.dumps(out, separators=(',', ':'))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'w').write(blob)
    gz = len(gzip.compress(blob.encode(), 6))
    print(f'parcels {len(P)}  sites {len(S)} ({sum(1 for v in S.values() if v == 0)} with no lot)')
    print(f'{len(blob)/1048576:.1f} MB raw, {gz/1048576:.2f} MB gzipped -> {OUT}')
    if write:
        open(LIVE, 'w').write(blob)
        print('wrote', LIVE)


if __name__ == '__main__':
    run(write='--write' in sys.argv)
