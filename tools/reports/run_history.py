"""How each run went, day by day - for the leading hands' Run forecast page. Writes TWO files:

  data/run-history.json        (public, with the app) - per run the estimates and each day's bins and weight; no people
  run-history-drivers.json     (here, NOT in the repo) - who did each run each day: first name, truck, bins, hours, kg.
                               Upload it to the owner's Google Drive as "lukez-bunz-run-history.json"; the Apps Script
                               (History.js) hands it to the app only with the leading hand PIN. The repo and site are public,
                               so driver names and their bins per hour must never go into data/ (Fox, 27 Oct).

    python3 run_history.py <report.xlsx> [<report.xlsx> ...]

Reads the "Driver Run" and "Loads" sheets of Solo's monthly 3Logix reports ("mornington_domestic-month-*.xlsx").

Per run (key as the app writes it: Garbage#Monday#201, Recycling#Tuesday#B#220, FOGO#Tuesday#A#351, summer recycle
SummerRecycling#Tuesday#232):
  d   - the last 400 days: { "YYYY-MM-DD": [bins, kg, flag] } for the whole run that day. flag 1 = the lift counter was wrong (bins
        far over the run's usual and not matching the weight - truck 3466 counted about double in Oct-Dec 2025): bins is what the
        weight works out to; flag 2 = the weight looks short (a load not weighed?), bins as counted.
  (drivers file) d = { "YYYY-MM-DD": [[first name, truck, bins, hours flipping (breaks out), kg, fault], ...] } one row per driver.
  n/h - bins on a normal day: median and 1 day in 10 (90th percentile), last 6 months, school / public holidays left out.
  hn/hh - the same for holidays (last 13 months), when there were at least 2.
  kg  - median kg per bin (last 6 months).
Summer recycle runs only run in the summer holidays: n/h are from all their days.
"""
import sys, os, re, json, glob, statistics as st, datetime
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hols import hol, SCHOOL, PH

DAYS = {'Mon': 'Monday', 'Tue': 'Tuesday', 'Wed': 'Wednesday', 'Thu': 'Thursday', 'Fri': 'Friday'}
STREAM = {'Domestic Garbage': 'Garbage', 'Domestic Recycling': 'Recycling', 'Domestic Organics': 'FOGO'}
FIX = {'Lieve, Steve': 'Liebe, Steven'}


def sheet(wb, name, first):
    hdr, out = None, []
    if name not in wb.sheetnames: return out
    for r in wb[name].iter_rows(values_only=True):
        if hdr is None:
            if r and r[0] == first: hdr = list(r)
            continue
        if r and r[0]: out.append(dict(zip(hdr, r)))
    return out


def load(files):
    if len(files) == 1 and files[0].endswith('.json'):   # (a cache of both sheets: {"DR": [...], "LD": [...]})
        d = json.load(open(files[0])); return d['DR'], d['LD']
    import openpyxl
    DR, LD = [], []
    for f in files:
        wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        DR += sheet(wb, 'Driver Run', 'Driver Name'); LD += sheet(wb, 'Loads', 'Run Name')
    return DR, LD


def dt(s):
    if isinstance(s, (datetime.datetime, date)): return s if isinstance(s, date) and not isinstance(s, datetime.datetime) else s.date()
    try: return datetime.datetime.strptime(str(s).strip()[:10], '%d/%m/%Y').date()
    except Exception: return None


def mins(s):
    try: h, m = str(s).strip()[:5].split(':'); return int(h) * 60 + int(m)
    except Exception: return None


def num(x):
    try: return float(x)
    except Exception: return None


def key_of(stream, name):
    name = str(name).strip()
    m = re.match(r'^Summer[- ](\d+)[- ](Mon|Tue|Wed|Thu|Fri)', name, re.I)
    if stream == 'Recycling' and m: return 'SummerRecycling#%s#%s' % (DAYS[m.group(2).title()], m.group(1))
    m = re.match(r'^(\d+) (Monday|Tuesday|Wednesday|Thursday|Friday)(?: Week ([AB]))?$', name)
    if not m: return None
    n, d, w = m.groups()
    if stream == 'Garbage': return 'Garbage#%s#%s' % (d, n)
    return '%s#%s#%s#%s' % (stream, d, w, n) if w else None


def first(name):
    s = ', '.join(p.strip().title() for p in str(name).split(','))
    s = FIX.get(s, s)
    return (s.split(',', 1)[1] if ',' in s else s).strip().split(' ')[0]


def main(files):
    DR, LD = load(files)
    win = {}
    for l in LD:
        a, b = mins(l.get('Col Start Time')), mins(l.get('Col End Time'))
        if a is not None and b is not None and b > a: win.setdefault((str(l.get('Run Name')).strip(), str(l.get('Run Date')), str(l.get('Driver'))), []).append((a, b))
    rows, seen = {}, set()
    for r in DR:
        s = STREAM.get(r.get('Service Type')); d = dt(r.get('Run Date'))
        if not s or not d: continue
        k = key_of(s, r.get('Run'))
        if not k: continue
        sig = (r.get('Driver Name'), str(r.get('Run')), str(r.get('Run Date')), r.get('Collections Performed'))
        if sig in seen: continue
        seen.add(sig)
        lifts = num(r.get('Collections Performed')) or 0; hrs = num(r.get('Collection Time Hrs')) or 0; kg = num(r.get('Total Weight')) or 0
        brk = 0
        for t, du in ((r.get('Rest 1 Time'), r.get('Rest 1 Duration Mins')), (r.get('Rest 2 Time'), r.get('Rest 2 Duration Mins'))):
            t = mins(t); du = num(du)
            if t is None or not du: continue
            if any(a <= t <= b for a, b in win.get((str(r.get('Run')).strip(), str(r.get('Run Date')), str(r.get('Driver Name'))), [])): brk += du
        net = max(0.0, hrs - brk / 60) if hrs else 0
        veh = str(r.get('Vehicle') or '').split('.')[0]
        rows.setdefault(k, []).append([d, first(r.get('Driver Name')), veh, int(lifts), round(net, 2), int(round(kg))])
    last = max(x[0] for v in rows.values() for x in v)
    since6, since13, since400 = last - timedelta(days=183), last - timedelta(days=396), last - timedelta(days=400)
    out, drv = {}, {}
    for k, v in rows.items():
        kpl = [x[5] / x[3] for x in v if x[5] > 0 and x[3] >= 20]
        med = st.median(kpl) if kpl else None
        for x in v: x.append(1 if (med and x[5] > 0 and x[3] >= 20 and x[5] / x[3] < 0.6 * med) else 0)
        byday = {}
        for x in v: byday.setdefault(x[0], []).append(x)
        tot = {d: (sum(x[3] for x in xs), any(x[6] for xs2 in [xs] for x in xs2)) for d, xs in byday.items()}
        good = {d: b for d, (b, f) in tot.items() if not f and b >= 50}
        summer = k.startswith('SummerRecycling')
        if summer:
            norm = sorted(b for d, b in good.items() if d >= since13); hl = []
        else:
            norm = sorted(b for d, b in good.items() if d >= since6 and not hol(d))
            hl = sorted(b for d, b in good.items() if d >= since13 and hol(d))
        if not norm and not any(d >= since400 for d in byday): continue
        e = {}
        if norm:
            e['n'] = int(st.median(norm)); e['h'] = norm[int(0.9 * (len(norm) - 1))]; e['nd'] = len(norm)
        if len(hl) >= 2:
            e['hn'] = int(st.median(hl)); e['hh'] = hl[int(0.9 * (len(hl) - 1))]
        recent = [x[5] / x[3] for x in v if (summer or x[0] >= since6) and x[5] > 0 and x[3] >= 20 and not x[6]]
        if recent: e['kg'] = round(st.median(recent), 1)
        kg1 = e.get('kg')
        e['d'] = {}; drv[k] = {}
        for d, xs in sorted(byday.items()):
            if d < since400: continue
            xs = [x for x in xs if x[3] or x[4]]
            if not xs: continue
            b = sum(x[3] for x in xs); w = sum(x[5] for x in xs); f = 0
            if any(x[6] for x in xs):
                if e.get('n') and kg1 and b > 1.35 * e['n']: b = sum(round(x[5] / kg1) if x[6] else x[3] for x in xs); f = 1
                else: f = 2
            e['d'][str(d)] = [b, w, f]
            drv[k][str(d)] = [x[1:] for x in sorted(xs, key=lambda x: -x[3])]
        out[k] = e
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'run-history.json')
    json.dump({'version': 1, 'generated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'to': str(last),
               'note': 'Run forecast (leading hands): bins and weight per run per day, and estimates - from Solo monthly reports. No driver details (those are private, via the Apps Script). Made by tools/reports/run_history.py.',
               'cols': ['bins', 'kg', 'flag'],
               'hols': [[str(a), str(b)] for a, b in SCHOOL], 'ph': sorted(str(d) for d in PH),
               'runs': dict(sorted(out.items()))}, open(p, 'w'), separators=(',', ':'))
    q = 'run-history-drivers.json'
    json.dump({'version': 1, 'generated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'to': str(last),
               'cols': ['driver', 'truck', 'bins', 'hours', 'kg', 'fault'], 'runs': dict(sorted(drv.items()))}, open(q, 'w'), separators=(',', ':'))
    print(len(out), 'runs, up to', last, '-', round(os.path.getsize(p) / 1024), 'KB public;', os.path.abspath(q), round(os.path.getsize(q) / 1024), 'KB private (upload to Drive)')


if __name__ == '__main__':
    main(sys.argv[1:] or sorted(glob.glob('mornington_domestic-month-*.xlsx')))
