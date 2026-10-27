"""How many bins each run really lifts, from Solo's monthly 3Logix reports ("mornington_domestic-month-*.xlsx", Runs sheet).
Writes data/run-lifts.json, which the run maps show in their key ("Usually lifted").

    python3 run_lifts.py <report.xlsx> [<report.xlsx> ...]

Per run (garbage, recycle Week A/B, FOGO; summer recycle runs are left out - they are different runs):
  normal  - median bins lifted on a normal day in the last 6 months of the reports (not in school holidays or on a public holiday)
  busy    - 90th percentile of those (1 day in 10 is bigger)
  hol     - median in holidays (the holiday-home areas, Monday and Tuesday Week B, about double)
  kg      - median kg per bin
A day whose lift count doesn't match its weight (kg per bin under 75% of the run's usual - a faulty lift counter, e.g. truck 3466
counted about double in Nov-Dec 2025) is left out. "Not presented" isn't used: it relies on the driver pressing a button."""
import sys, re, json, os, statistics as st, datetime
from datetime import date
import openpyxl

def school_hols(y):
    # Victorian government school holidays (approximate; good enough to keep holiday peaks out of the normal-day figure)
    return {2024: [(date(2024, 9, 21), date(2024, 10, 6)), (date(2024, 12, 21), date(2025, 1, 27))],
            2025: [(date(2025, 4, 5), date(2025, 4, 21)), (date(2025, 6, 28), date(2025, 7, 13)), (date(2025, 9, 20), date(2025, 10, 5)), (date(2025, 12, 20), date(2026, 1, 27))],
            2026: [(date(2026, 4, 3), date(2026, 4, 19)), (date(2026, 6, 27), date(2026, 7, 12)), (date(2026, 9, 19), date(2026, 10, 4)), (date(2026, 12, 19), date(2027, 1, 27))]}.get(y, [])
PH = {date(2024, 11, 5), date(2024, 12, 25), date(2024, 12, 26), date(2025, 1, 1), date(2025, 1, 27), date(2025, 3, 10), date(2025, 4, 18), date(2025, 4, 21), date(2025, 4, 25), date(2025, 6, 9), date(2025, 9, 26), date(2025, 11, 4),
      date(2025, 12, 25), date(2025, 12, 26), date(2026, 1, 1), date(2026, 1, 26), date(2026, 3, 9), date(2026, 4, 3), date(2026, 4, 6), date(2026, 6, 8), date(2026, 9, 25), date(2026, 11, 3)}
def hol(d): return d in PH or any(a <= d <= b for y in (d.year - 1, d.year) for a, b in school_hols(y))

rows = []
for f in sys.argv[1:]:
    wb = openpyxl.load_workbook(f, read_only=True, data_only=True); hdr = None
    for r in wb['Runs'].iter_rows(values_only=True):
        if hdr is None:
            if r and r[0] == 'Id': hdr = list(r)
            continue
        if not r or not r[2]: continue
        d = dict(zip(hdr, r))
        try: day = datetime.datetime.strptime(str(d['Date']), '%d/%m/%Y').date()
        except Exception: continue
        rows.append((day, str(d['Run']).strip(), d['Service Type'], d['Collections Performed'] or 0, d['Total Weight'] or 0))
last = max(r[0] for r in rows); since = last - datetime.timedelta(days=183)
runs = {}
for day, name, typ, lifts, kg in rows:
    m = re.match(r'^(\d+) (Monday|Tuesday|Wednesday|Thursday|Friday)(?: Week ([AB]))?$', name)
    if not m or lifts < 50: continue
    n, dname, wk = m.groups()
    stream = {'Domestic Garbage': 'Garbage', 'Domestic Recycling': 'Recycling', 'Domestic Organics': 'FOGO'}.get(typ)
    if not stream or (stream != 'Garbage' and not wk): continue
    key = f'Garbage#{dname}#{n}' if stream == 'Garbage' else f'{stream}#{dname}#{wk}#{n}'
    runs.setdefault(key, []).append((day, lifts, kg))
out = {}
for key, v in runs.items():
    kpl = [kg / l for d, l, kg in v if kg > 0]
    if not kpl: continue
    km = st.median(kpl)
    ok = [(d, l, kg) for d, l, kg in v if kg > 0 and kg / l >= 0.75 * km and d >= since]
    norm = sorted(l for d, l, kg in ok if not hol(d)); hl = sorted(l for d, l, kg in ok if hol(d))
    if len(norm) < 3: continue
    out[key] = {'normal': int(st.median(norm)), 'busy': norm[int(0.9 * (len(norm) - 1))], 'days': len(norm),
                'hol': int(st.median(hl)) if len(hl) >= 2 else None, 'kg': round(st.median(kg / l for d, l, kg in ok), 1)}
p = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'run-lifts.json')
json.dump({'version': 1, 'generated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'from': str(since), 'to': str(last),
           'note': 'Bins really lifted per run (Solo monthly reports): normal = median normal day, busy = 1 day in 10, hol = holidays. Made by tools/reports/run_lifts.py.',
           'runs': dict(sorted(out.items()))}, open(p, 'w'), indent=0)
print(len(out), 'runs,', since, '-', last)
