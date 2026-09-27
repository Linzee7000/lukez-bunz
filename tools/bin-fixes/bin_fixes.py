"""Find bins whose map dot is nowhere near their own house, work out why, and fix the dot.

Each Solo bin in the master CSV carries its last lift: `serial|f:<date>|...|lat:<lat>|lng:<lng>`. Those lift
positions were merged into the bins by serial number alone somewhere upstream, and serial numbers are not unique
across bin types: FOGO bin 13510 at a Rosebud unit shares its number with council GARBAGE bin 13510 at a house in
Mount Eliza, so the FOGO bin got the garbage bin's lift position, 24 km from its house. Thousands of dots like that
drag run boundaries all over the peninsula.

For every Solo bin whose dot is more than 150 m from its house AND more than 40 m outside its own lot (so rural
gates and long driveways are left alone), the reason is worked out:
  GPS default spot   the dot sits on one of the two points hundreds of bins share (a GPS default, not a house)
  number clash       a DIFFERENT bin with the same number (any stream, Solo or council, or a stand-in serial that
                     is the property ID) is registered at a house beside the dot - the dot is that bin's lift
  no match, far      the dot is 1 km+ away and no bin there has this number - the dot is wrong either way; the
                     bin may also be registered to the wrong house (flagged to check)
  no match, near     150 m - 1 km and no clear cause - listed only, not changed (could be a shared bin spot)
The fix is the same for the first three: the dot goes back to the bin's own house. No bin is moved between houses
- the registrations are Solo's to fix at the source, and the CSV lists every case for that.

    python bin_fixes.py <master.csv>      # -> ../../data/bin-fixes.json (applied by the app at load) + a CSV report
"""
import csv, datetime, json, math, os, re, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
SOLO = {'Garbage': [11, 12, 13], 'Recycling': [14, 15], 'FOGO': [16]}          # CSV column indexes (as the app reads them)
SOLO_SIZE = {11: '80L', 12: '120L', 13: '240L', 14: '120L', 15: '240L', 16: '240L'}
COUNCIL = {'Garbage': [25, 26, 27], 'Recycling': [28, 29], 'FOGO': [30]}
FAR_M, LOT_M, CLASH_M, NEAR_REVIEW_M = 150.0, 40.0, 35.0, 1000.0
PILES = [(-38.2537, 145.1218), (-38.3713, 144.8536)]       # points hundreds of bins share: GPS defaults, not houses

def dist(a, b, c, d):
    kx = 111320 * math.cos(math.radians(a))
    return math.hypot((d - b) * kx, (c - a) * 110540)

def weekday(f):
    m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', f or '')
    if not m: return ''
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3)); y += 2000 if y < 100 else 0
    try: return datetime.date(y, mo, d).strftime('%A')
    except ValueError: return ''

def solo_bins(cell):
    out = []
    for it in (cell or '').split(';;'):
        it = it.strip()
        if not it: continue
        parts = it.split('|'); meta = {}
        for p in parts[1:]:
            if ':' in p: k, v = p.split(':', 1); meta[k.strip()] = v.strip()
        try: lat, lng = float(meta.get('lat', '')), float(meta.get('lng', ''))
        except ValueError: lat = lng = None
        out.append(dict(serial=parts[0].strip().upper(), lat=lat, lng=lng, f=meta.get('f', '')))
    return out

def council_bins(cell):
    return [s.strip().upper() for s in (cell or '').split(';') if s.strip() and s.strip().upper() != 'NAN']

def load_lots():
    d = json.load(open(os.path.join(REPO, 'data', 'parcels.json')))
    scale, parcels = d['scale'], d['parcels']
    def ring(pid):
        rec = parcels.get(pid)
        if not rec: return None
        dl, x, y, pts = rec[0], 0, 0, []
        for i in range(0, len(dl), 2):
            x += dl[i]; y += dl[i + 1]; pts.append((y / scale, x / scale))   # (lat, lng)
        return pts
    return {k: v[0] for k, v in d['sites'].items() if isinstance(v, list) and v}, ring

def in_poly(lat, lng, poly):
    c = False; j = len(poly) - 1
    for i in range(len(poly)):
        yi, xi = poly[i]; yj, xj = poly[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi: c = not c
        j = i
    return c

def poly_dist(lat, lng, poly):
    if in_poly(lat, lng, poly): return 0.0
    kx, ky = 111320 * math.cos(math.radians(lat)), 110540
    px, py, best = lng * kx, lat * ky, 1e12
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        ax, ay, bx, by = a[1] * kx, a[0] * ky, b[1] * kx, b[0] * ky
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / ((dx * dx + dy * dy) or 1)))
        best = min(best, math.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return best

def main(path):
    rows = list(csv.reader(open(path, newline='', encoding='utf8')))
    head, rows = rows[0], rows[1:]
    ci = {h: i for i, h in enumerate(head)}
    sites, grid = [], defaultdict(list)
    for r in rows:
        try: lat, lng = float(r[ci['Lat']]), float(r[ci['Lng']])
        except (ValueError, IndexError): lat = lng = None
        s = dict(key=(r[1] or r[0]), site=r[0], prop=r[1], addr=r[2], lat=lat, lng=lng, day=r[ci['Solo Collection Day']],
                 week=r[ci['Solo Week Cycle']], runs={'Garbage': r[ci['Solo Garbage Run']], 'Recycling': r[ci['Solo Recycling Run']], 'FOGO': r[ci['Solo FOGO Run']]},
                 solo={st: [dict(b, size=SOLO_SIZE[i]) for i in idx for b in solo_bins(r[i] if i < len(r) else '')] for st, idx in SOLO.items()},
                 council={st: [x for i in idx for x in council_bins(r[i] if i < len(r) else '')] for st, idx in COUNCIL.items()})
        sites.append(s)
        if lat: grid[(int(lat // 0.0005), int(lng // 0.0005))].append(s)
    def near(lat, lng, r):
        a, b, out = int(lat // 0.0005), int(lng // 0.0005), []
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for s in grid.get((a + i, b + j), []):
                    d = dist(lat, lng, s['lat'], s['lng'])
                    if d <= r: out.append((d, s))
        return sorted(out, key=lambda x: x[0])
    def serials_at(s):
        out = {s['prop'].upper(), s['site'].upper()} - {''}                 # a stand-in serial can be the property's own ID
        for st in ('Garbage', 'Recycling', 'FOGO'):
            out |= {b['serial'] for b in s['solo'][st]}; out |= set(s['council'][st])
        return out
    # the same number written differently in the two lists: GW261142 / G0261142 / 261142
    digits = lambda x: re.sub(r'^0+', '', re.sub(r'\D', '', x))
    def digit_serials_at(s): return {digits(x) for x in serials_at(s) if len(digits(x)) >= 4}
    lot_of, ring = load_lots()

    fixes, report, counts = [], [], defaultdict(int)
    for s in sites:
        if not s['lat']: continue
        for st in ('Garbage', 'Recycling', 'FOGO'):
            for b in s['solo'][st]:
                if b['lat'] is None: continue
                d_own = dist(b['lat'], b['lng'], s['lat'], s['lng'])
                if d_own <= FAR_M: continue
                pid = lot_of.get(s['key']); poly = ring(pid) if pid else None
                lot_d = poly_dist(b['lat'], b['lng'], poly) if poly else None
                if lot_d is not None and lot_d <= LOT_M: continue          # at its own gate / frontage (a big block)
                around = near(b['lat'], b['lng'], CLASH_M)
                nearest = around[0][1] if around else None
                clash = next((o for _, o in around if o is not s and b['serial'] in serials_at(o)), None)
                dg = digits(b['serial'])
                clash2 = None if clash or len(dg) < 4 else next((o for _, o in around if o is not s and dg in digit_serials_at(o)), None)
                pile = any(abs(b['lat'] - p[0]) < 0.0002 and abs(b['lng'] - p[1]) < 0.0002 for p in PILES)
                if pile: why, act, check = 'GPS default spot', 'dot moved to its house', ''
                elif clash:
                    other = [k for k in ('Garbage', 'Recycling', 'FOGO') if b['serial'] in {x['serial'] for x in clash['solo'][k]}]
                    other_c = [k for k in ('Garbage', 'Recycling', 'FOGO') if b['serial'] in set(clash['council'][k])]
                    kind = ('Solo ' + '/'.join(other)) if other else ('council ' + '/'.join(other_c)) if other_c else 'stand-in serial (property ID)'
                    why, act, check = f'number clash: {kind} bin {b["serial"]} at {clash["addr"]}', 'dot moved to its house', ''
                elif clash2:
                    why, act, check = f'number clash: a bin numbered {dg} (written differently) at {clash2["addr"]}', 'dot moved to its house', ''
                elif d_own >= NEAR_REVIEW_M:
                    # When was it lifted? On the day the house at the dot is collected -> that house's own bin (a number
                    # clash with a bin not in these lists). On this bin's own day -> it may really live at that house.
                    lift_day = weekday(b['f']); dot_day = nearest['day'] if nearest else ''
                    if lift_day and dot_day and lift_day == dot_day and lift_day != s['day']:
                        why, act, check = f'no match, far: lifted on a {lift_day}, the day {nearest["addr"]} is collected - most likely that house\'s own bin with the same number', 'dot moved to its house', ''
                    elif lift_day and lift_day == s['day'] and dot_day != lift_day:
                        why, act, check = f'no match, far: lifted on its own day ({lift_day}) at {nearest["addr"] if nearest else "a house"} {d_own / 1000:.0f} km away', 'dot moved to its house', 'Yes - it may really be at the house by the dot'
                    else:
                        why, act, check = 'no match, far: no bin at the dot has this number', 'dot moved to its house', 'Maybe - the dot is wrong; check the registration if the house reports a missing bin'
                else:
                    why, act, check = 'no match, near: no clear cause (could be a shared bin spot)', 'none - listed only', 'Yes'
                counts[why.split(':')[0]] += 1
                run = s['runs'][st]
                runlabel = f'{st} {s["day"]} {run}' + (f' Week {s["week"]}' if st != 'Garbage' and s['week'] else '') if run else ''
                report.append([act, st, b['serial'], b['size'], s['prop'], s['site'], s['addr'], runlabel,
                               f'{b["lat"]:.6f}', f'{b["lng"]:.6f}', round(d_own), '' if lot_d is None else round(lot_d),
                               nearest['addr'] if nearest else '', why, f'{s["lat"]:.6f},{s["lng"]:.6f}' if act.startswith('dot') else '', check, b['f']])
                if act.startswith('dot'):
                    fixes.append([s['site'], st[0], b['serial']])   # site ID: unique (557 property IDs are shared by several rows). No positions: the repo is public
    out = dict(version=1, generated=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
               note='Bin dots that came from a different bin (same serial number) or a GPS default spot: [site ID, stream initial, serial]. '
                    'The app puts each such dot back at its own house, only while it is still more than 150 m from the house. '
                    'Made by tools/bin-fixes/bin_fixes.py.', fixes=fixes)
    json.dump(out, open(os.path.join(REPO, 'data', 'bin-fixes.json'), 'w'), separators=(',', ':'))
    rep = os.environ.get('BIN_FIX_REPORT', os.path.join(HERE, 'bin-fixes-report.csv'))
    with open(rep, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['Change made', 'Stream', 'Bin serial', 'Bin size', 'Property ID', 'Site ID', 'Registered address', 'Registered run',
                    'Old dot lat', 'Old dot lng', 'Old dot distance from house (m)', 'Old dot distance outside its own lot (m)',
                    'House nearest the old dot', 'Why the dot was wrong', 'New dot (the house)', 'Needs checking at the source', 'Last lifted'])
        order = {'GPS': 0, 'number clash': 1, 'no match, far': 2, 'no match, near': 3}
        report.sort(key=lambda r: (order.get(r[13].split(':')[0].split(' default')[0], 9), r[1], r[6]))
        w.writerows(report)
    print(f'{len(report)} far dots: ' + ', '.join(f'{k} {v}' for k, v in counts.items()) + f'; {len(fixes)} fixed -> data/bin-fixes.json; report -> {rep}')

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, 'tools', 'route-maps', 'work', 'master.csv'))
