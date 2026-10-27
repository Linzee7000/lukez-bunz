"""The day's bin estimates per run, as text - what the 5am notification sends the leading hand.

    python3 day_estimate.py [YYYY-MM-DD]      (default: today in Melbourne)

Same sums as the app's Run forecast page: normal / high (1 day in 10) from the last 6 months of Solo's reports (the holiday
figures on a school or public holiday), and what the run lifted on the same weekday 52 weeks ago (same week letter)."""
import sys, os, json, datetime
from datetime import date, timedelta

H = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'run-history.json')))
HOLS = [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in H['hols']]
PH = {date.fromisoformat(d) for d in H['ph']}
DAY = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
BASE = date(2026, 8, 31)   # (a Monday in recycle Week B - the app's BASE_WEEK_DATE / BASE_RECYCLE_WEEK)


def hol(d): return d in PH or any(a <= d <= b for a, b in HOLS)
def rec_week(d): return 'B' if ((d - timedelta(days=d.weekday()) - BASE).days // 7) % 2 == 0 else 'A'


def summer(d):
    # summer recycle: six weeks from the Monday before Christmas
    for y in (d.year, d.year - 1):
        x = date(y, 12, 25); mon = x - timedelta(days=(x.weekday() or 7))
        if mon <= d < mon + timedelta(weeks=6): return True
    return False


def runs_for(d):
    day, rw = DAY[d.weekday()], rec_week(d); fw = 'A' if rw == 'B' else 'B'; summ = summer(d)
    out = []
    for k, e in H['runs'].items():
        p = k.split('#')
        if p[1] != day: continue
        if p[0] == 'Garbage': pass
        elif p[0] == 'FOGO':
            if p[2] != fw: continue
        elif p[0] == 'Recycling':
            if summ or p[2] != rw: continue
        elif p[0] == 'SummerRecycling':
            if not summ: continue
        else: continue
        recent = [x for x in e['d'] if date.fromisoformat(x) >= d - timedelta(days=400 if p[0] == 'SummerRecycling' else 120)]
        if not recent: continue
        out.append((k, e))
    return out


def estimate(d, k, e):
    hd = hol(d)
    n = (e.get('hn') if hd else None) or e.get('n'); h = (e.get('hh') if hd else None) or e.get('h')
    ly = e['d'].get(str(d - timedelta(days=364)))   # [bins, kg, flag]; flag 1 = counter wrong, bins from the weight (marked *)
    return n, h, (str(ly[0]) + ('*' if ly[2] == 1 else '') if ly else None), e.get('kg')


def label(k):
    p = k.split('#'); return p[-1] + (p[2] if len(p) == 4 else '')


def main():
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else (datetime.datetime.utcnow() + timedelta(hours=11)).date()
    rs = runs_for(d)
    if not rs: print('%s %s: no kerbside runs.' % (DAY[d.weekday()][:3].upper(), d.strftime('%d %b').upper())); return
    head = '%s %s%s%s' % (DAY[d.weekday()][:3].upper(), d.strftime('%d %b').upper(), ' · holidays' if hol(d) else '', ' · summer recycle' if summer(d) else '')
    print(head + ' - bins: normal / high / last year')
    names = {'Garbage': 'Garbage', 'Recycling': 'Recycle', 'SummerRecycling': 'Summer recycle', 'FOGO': 'FOGO'}
    for s in ['Garbage', 'Recycling', 'SummerRecycling', 'FOGO']:
        lines, tn, th, tl, tk = [], 0, 0, 0, 0
        for k, e in sorted((x for x in rs if x[0].startswith(s + '#')), key=lambda x: int(x[0].split('#')[-1])):
            n, h, ly, kg = estimate(d, k, e)
            tn += n or 0; th += h or 0; tl += int(str(ly).rstrip('*')) if ly else 0; tk += (n or 0) * (kg or 0)
            lines.append('%s %s/%s/%s' % (label(k), n or '-', h or '-', ly if ly is not None else '-'))
        if lines:
            print('%s %s/%s/%s (~%.0f t): %s' % (names[s], tn, th, tl or '-', tk / 1000, ', '.join(lines)))


if __name__ == '__main__':
    main()
