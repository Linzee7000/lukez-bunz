"""Pin each "reverse in / drive in" segment onto a real street, or drop it.

The segments come out of the route maps by fitting each page's picture to that run's houses, which
places them to about 5-20 m. A suburban street is only 20-60 m from the next one, so that error is
enough to put a segment in a back yard or on the wrong road - measured against the OSM road network,
28% of the segments in the first cut were more than 25 m from *any* road, the worst 500 m out, and
69 of them named a different street from the one they were actually lying on.

This snaps each segment onto the road it belongs to and throws away the ones that can't be placed
with confidence. A segment is matched to a road only if the road is close AND runs the same way
(otherwise a segment drifting off the end of a street snaps onto the cross-street it happens to
touch). Once matched, the segment is replaced by the stretch of that road's own centreline it covers,
so it lies exactly along the street, and takes that road's name from OSM rather than guessing the
name from whichever house happened to be nearest.

Dropping is deliberate: a segment on the wrong street is worse than no segment, because the driver
backs into the wrong road.

    python snap_modes.py                 # report only
    python snap_modes.py --write         # ...and rewrite ../../data/street-modes.json

Needs work/roads.json (OSM road centrelines) - see the README for the fetch.
"""
import json, math, os, sys, datetime
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree
from shapely.ops import substring

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, 'work')
LIVE = os.path.abspath(os.path.join(HERE, '..', '..', 'data', 'street-modes.json'))
LAT0, LNG0 = -38.30, 144.95
KX = 111320 * math.cos(math.radians(LAT0)); KY = 110540.0

MAX_SNAP_M = 35.0      # further than this from a road and we can't say which street it is
MAX_ANGLE_DEG = 40.0   # a segment must run roughly along the road it snaps to, not across it
MIN_KEEP_M = 10.0      # after snapping, drop slivers


def to_m(la, ln): return ((ln - LNG0) * KX, (la - LAT0) * KY)
def to_ll(x, y): return [round(LAT0 + y / KY, 5), round(LNG0 + x / KX, 5)]


def bearing(line):
    (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
    return math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180.0


def angle_gap(a, b):
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def load_roads():
    roads = json.load(open(os.path.join(WORK, 'roads.json')))
    geo, meta = [], []
    for r in roads:
        pts = [to_m(a, b) for a, b in r['pts']]
        if len(pts) < 2: continue
        ln = LineString(pts)
        if ln.length < 5: continue
        geo.append(ln); meta.append((r.get('name', ''), r.get('hw', '')))
    return geo, meta, STRtree(geo)


def snap_one(seg_line, geo, meta, tree):
    """-> (snapped LineString, street name, distance) or None."""
    b = seg_line.bounds
    pad = MAX_SNAP_M
    idxs = tree.query(Point(seg_line.centroid).buffer(0))  # cheap prefilter is done below instead
    # query by the segment's own envelope, padded
    idxs = tree.query(LineString(seg_line.coords).buffer(pad))
    best = None
    sb = bearing(seg_line)
    for i in idxs:
        road = geo[i]
        d = road.distance(seg_line)
        if d > MAX_SNAP_M: continue
        # compare against the part of the road nearest this segment, not the whole way - a long road
        # curves, and its overall bearing says little about the bit we're on
        a0 = road.project(Point(seg_line.coords[0]))
        a1 = road.project(Point(seg_line.coords[-1]))
        lo, hi = min(a0, a1), max(a0, a1)
        if hi - lo < 1.0:
            lo = max(0.0, lo - 15.0); hi = min(road.length, hi + 15.0)
        if hi - lo < 1.0: continue
        piece = substring(road, lo, hi)
        if piece.is_empty or piece.geom_type != 'LineString' or piece.length < 1.0: continue
        gap = angle_gap(sb, bearing(piece))
        if gap > MAX_ANGLE_DEG: continue
        score = d + gap * 0.5      # prefer close and aligned; 1 degree ~ half a metre of penalty
        if best is None or score < best[0]:
            best = (score, piece, meta[i][0], d)
    if best is None: return None
    _, piece, name, d = best
    if piece.length < MIN_KEEP_M: return None
    return piece, name, d


def main(write=False):
    src = json.load(open(LIVE))
    segs = src['segments']
    geo, meta, tree = load_roads()
    print(f'{len(segs)} segments, {len(geo)} road centrelines')

    out, dropped, moved = [], [], []
    renamed = 0
    for s in segs:
        pts = [to_m(a, b) for a, b in s['points']]
        if len(pts) < 2:
            dropped.append((s.get('street'), 'degenerate')); continue
        ln = LineString(pts)
        hit = snap_one(ln, geo, meta, tree)
        if hit is None:
            dropped.append((s.get('street'), f'no road within {MAX_SNAP_M:.0f}m running the same way')); continue
        piece, name, d = hit
        if not name:
            dropped.append((s.get('street'), 'road has no name in OSM')); continue
        if (s.get('street') or '').strip().lower() != name.strip().lower(): renamed += 1
        moved.append(d)
        out.append({'type': s['type'], 'street': name, 'src': s['src'],
                    'points': [to_ll(x, y) for x, y in piece.simplify(0.8).coords]})

    # The same stretch of road turns up on several pages (neighbouring runs, or a run split over two
    # map sheets), and after snapping those land on the same centreline. Merge by *where* the stretch
    # is, not by street name - a long road like Point Nepean Road genuinely has several separate
    # reverse-in spots along it, and keying on the name alone would throw all but one of them away.
    seen = {}
    for s in out:
        a, b = s['points'][0], s['points'][-1]
        ends = tuple(sorted([(round(a[0], 4), round(a[1], 4)), (round(b[0], 4), round(b[1], 4))]))
        k = (s['type'],) + ends      # 4dp ~ 10m
        if k not in seen or len(s['points']) > len(seen[k]['points']): seen[k] = s
    deduped = list(seen.values())

    moved.sort()
    print(f'kept {len(out)} ({len(deduped)} after merging repeats of the same street), dropped {len(dropped)}')
    if moved:
        print(f'  moved onto the road by: median {moved[len(moved)//2]:.0f}m  90th {moved[int(len(moved)*.9)]:.0f}m  max {moved[-1]:.0f}m')
    print(f'  took a different street name from OSM than the old guess: {renamed}')
    why = {}
    for _, r in dropped: why[r] = why.get(r, 0) + 1
    for r, n in sorted(why.items(), key=lambda t: -t[1]): print(f'  dropped {n}: {r}')

    src['segments'] = deduped
    src['version'] = int(src.get('version', 1)) + 1
    src['generated'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    src['note'] = ('Street driving modes read from the run route maps (PDF): purple = reverse in / '
                   'drive out, orange = drive in / reverse out. Each segment is snapped onto the real '
                   'street centreline it belongs to and named from OpenStreetMap; segments that could '
                   'not be placed on a street confidently are left out rather than guessed. '
                   'Applies to all kerbside streams.')
    dest = os.path.join(WORK, 'street-modes.snapped.json')
    json.dump(src, open(dest, 'w'), separators=(',', ':'))
    print('wrote', dest)
    if write:
        json.dump(src, open(LIVE, 'w'), separators=(',', ':'))
        print('wrote', LIVE)


if __name__ == '__main__':
    main(write='--write' in sys.argv)
