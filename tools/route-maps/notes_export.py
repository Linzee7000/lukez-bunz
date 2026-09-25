"""Read the "Drivers Notes" box off every route-map page -> data/run-notes.json.

Each page has a notes box under the map, two halves side by side, each half a street column and a note column:
    Higgins, Tucks, Frankston– Flinders, Viewbank,
    Lexington, Seychelles               One-Sided        | Point Ct     Tight access Back In
    Shands rd—NO ENTRY bet              Tucks and Shoreham| Blake St     Tight access
These are keyed to street names, so the app can show them when the truck is on that street during that run -
no need to place the page on the ground (which only works for some pages; see README).

Run identity comes from the page title: readable on Recycling / FOGO pages, decoded with garbage_font.py on
Garbage pages. Pages with no readable title (detail pages) are skipped.

    python notes_export.py            # print what was found
    python notes_export.py --write    # also write data/run-notes.json
"""
import json, os, re, subprocess, sys, datetime
from lib import DL, REPO, page_count
from garbage_font import decode, read_title

TITLE_RE = re.compile(r'(Monday|Tuesday|Wednesday|Thursday|Friday) Run (\d+) (Recycle|Organics) W([AB])')
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
SUFFIX = {'rd': 'road', 'road': 'road', 'st': 'street', 'street': 'street', 'ct': 'court', 'court': 'court', 'crt': 'court',
          'ave': 'avenue', 'av': 'avenue', 'avenue': 'avenue', 'dr': 'drive', 'drive': 'drive', 'cres': 'crescent', 'crescent': 'crescent',
          'pde': 'parade', 'parade': 'parade', 'pl': 'place', 'place': 'place', 'gr': 'grove', 'grove': 'grove', 'cl': 'close',
          'close': 'close', 'wy': 'way', 'way': 'way', 'tce': 'terrace', 'terrace': 'terrace', 'la': 'lane', 'lane': 'lane',
          'hwy': 'highway', 'highway': 'highway', 'bvd': 'boulevard', 'blvd': 'boulevard', 'boulevard': 'boulevard', 'cct': 'circuit',
          'circuit': 'circuit', 'rise': 'rise', 'mews': 'mews', 'walk': 'walk', 'esp': 'esplanade', 'esplanade': 'esplanade', 'gdns': 'gardens',
          'sq': 'square', 'track': 'track', 'trk': 'track'}

def words(pdf, page, garbage):
    out = subprocess.run(['pdftotext', '-bbox', '-f', str(page), '-l', str(page), os.path.join(DL, pdf), '-'], capture_output=True, text=True).stdout
    ws = []
    for m in re.finditer(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', out):
        t = m.group(5).replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&apos;', "'")
        if garbage: t = decode(t)
        ws.append(dict(x0=float(m.group(1)), y0=float(m.group(2)), x1=float(m.group(3)), y1=float(m.group(4)), t=t))
    return ws, out

def rows_of(ws):
    rows = []
    for w in sorted(ws, key=lambda w: (w['y0'], w['x0'])):
        if rows and abs(rows[-1][0]['y0'] - w['y0']) <= 3: rows[-1].append(w)
        else: rows.append([w])
    return [sorted(r, key=lambda w: w['x0']) for r in rows]

# bits of the page footer that can sit level with the notes box: bin count / loads / run / dates / map n of n
NOISE = re.compile(r'^(bin count( est\.?)?|count|est\.?|load( \d+)?|run|map( \d+/\d+)?|\d+|\d{1,2}/\d{1,2}/\d{2,4}|organics|recycle|garbage|wa|wb)$', re.I)
def chunks(r):
    out, cur = [], [r[0]] if r else []
    for w in r[1:]:
        if w['x0'] - cur[-1]['x1'] >= 10: out.append(cur); cur = [w]
        else: cur.append(w)
    if cur: out.append(cur)
    keep = []
    for c in out:
        ws = [w for w in c if not NOISE.match(w['t'].strip(' .:')) and not re.match(r'^\d{1,2}/\d{1,2}/\d{2,4}$', w['t'])]
        txt = ' '.join(w['t'] for w in ws)
        if not txt or NOISE.match(txt.strip(' .:')) or re.search(r'\b(bin count|count est|run est|load \d)\b', ' '.join(w['t'] for w in c), re.I) and len(ws) <= 2: continue
        keep.append(ws)
    return keep

def split_row(r, x_lo, x_hi):
    """street part / note part of one row in one half: chunks left of 45% of the half are the street, the rest the note."""
    mid = x_lo + 0.45 * (x_hi - x_lo)
    st, nt = [], []
    for c in chunks(r):
        (nt if (c[0]['x0'] >= mid and (st or c[0]['x0'] >= mid)) else st).append(' '.join(w['t'] for w in c))
    return ' '.join(st), ' '.join(nt)

LEGEND = {'one-sided', 'one sided', 'schools', 'reverse in', 'drive in, reverse out'}
def notes_on_page(ws):
    """The notes box's entries as plain text. Each half of the box is read top to bottom; a blank line (a gap of
    more than ~1.4 lines) starts a new entry. Chunks of a row that are clearly footer (bin count, loads, dates)
    are dropped. Which streets an entry is about is worked out in the app, against the run's real streets."""
    hd = [w for w in ws if w['t'].lower() == 'drivers']
    if not hd: return []
    h = hd[0]
    legend = [w for w in ws if w['y0'] > h['y1'] and w['t'] in ('Schools', 'Reverse', 'Drive')]
    y_end = min(w['y0'] for w in legend) - 1 if legend else h['y1'] + 120
    box = [w for w in ws if h['y1'] < w['y0'] < y_end]
    if not box: return []
    nw = [w for w in ws if w['t'].lower() == 'notes' and abs(w['y0'] - h['y0']) < 3]
    centre = ((h['x0'] + (nw[0]['x1'] if nw else h['x1'])) / 2)
    x_min = min(w['x0'] for w in box) - 4; x_max = max(w['x1'] for w in box) + 4
    out = []
    for x_lo, x_hi in ((x_min, centre - 3), (centre - 3, x_max)):
        mid = x_lo + 0.4 * (x_hi - x_lo)
        rows = []
        for r in rows_of([w for w in box if x_lo <= w['x0'] < x_hi]):
            cs = chunks(r)
            if cs: rows.append((r[0]['y0'], cs[0][0]['x0'] >= mid, ' · '.join(' '.join(w['t'] for w in c) for c in cs)))
        gaps = [b[0] - a[0] for a, b in zip(rows, rows[1:]) if b[0] - a[0] > 4]
        step = min(gaps) if gaps else 14                 # the box's line spacing: a bigger gap is a blank line
        ents, cur, last_y, done = [], [], None, False
        for y, note_only, t in rows:
            near = last_y is not None and y - last_y <= 1.5 * step
            if note_only and near and (cur or ents):
                # the note wraps onto this line (nothing in the street column): it belongs to the entry above
                if cur: cur.append(t)
                else: ents[-1] += ' ' + t
            else:
                if cur and (not near or done): ents.append(' '.join(cur)); cur = []
                cur.append(t)
                done = ' · ' in t                          # street and note on one row: complete unless the note wraps
            last_y = y
        if cur: ents.append(' '.join(cur))
        out += ents
    out = [re.sub(r'\s+', ' ', t).strip(' ·') for t in out]
    return [t for t in out if len(t) >= 4 and t.lower() not in LEGEND]

def streets_in(s):
    """Street names mentioned in the street part: 'Higgins, Tucks, Frankston– Flinders' -> [{name:'higgins'}...]"""
    out = []
    s = re.sub(r'[—–]\s*', '-', s)
    for part in re.split(r',|&|/|\band\b|;', s):
        part = part.strip(' .-')
        m = re.match(r"^([A-Za-z][A-Za-z'’]*(?:[ -][A-Za-z][A-Za-z'’]*)*)", part)
        if not m: continue
        toks = m.group(1).replace('-', ' - ').split()
        name, typ = [], ''
        for t in toks:
            lt = t.lower().rstrip('.')
            if lt in SUFFIX and name: typ = SUFFIX[lt]; break
            if lt in ('no', 'entry', 'bet', 'between', 'only', 'one', 'sided', 'side', 'tight', 'access', 'back', 'in', 'out'): break
            name.append(t)
        nm = ' '.join(name).replace(' - ', '-').strip(' -').lower()
        if len(nm) >= 3: out.append(dict(name=nm, type=typ))
    return out

def find_pdfs():
    out = []
    for f in sorted(os.listdir(DL)):
        if not f.lower().endswith('.pdf'): continue
        u = f.upper()
        if 'RECYCLE' in u: out.append((f, 'REC'))
        elif 'ORGANICS' in u: out.append((f, 'ORG'))
        elif 'GARBAGE' in u and any(d.upper() in u for d in DAYS): out.append((f, 'GAR'))
    return out

def run(write):
    runs, pages, with_notes = {}, 0, 0
    for pdf, code in find_pdfs():
        garbage = code == 'GAR'
        for page in range(1, page_count(pdf) + 1):
            ws, raw = words(pdf, page, garbage)
            text = ' '.join(w['t'] for w in ws)
            if garbage:
                t = read_title(decode(re.sub(r'<[^>]+>', ' ', raw)))
                if not t: continue
                key = f'Garbage#{t[0]}#{t[1]}'
            else:
                m = TITLE_RE.search(text)
                if not m: continue
                stream = 'Recycling' if m.group(3) == 'Recycle' else 'FOGO'
                key = f'{stream}#{m.group(1)}#{m.group(4)}#{m.group(2)}'
            pages += 1
            found = notes_on_page(ws)
            if found: with_notes += 1
            lst = runs.setdefault(key, [])
            for txt in found:
                if any(e['text'] == txt for e in lst): continue
                lst.append(dict(text=txt, src=f'{pdf} p{page}'))
    runs = {k: v for k, v in runs.items() if v}
    n = sum(len(v) for v in runs.values())
    print(f'{pages} titled pages, {with_notes} with notes -> {n} notes on {len(runs)} runs')
    for k in list(runs)[:6]:
        for e in runs[k][:4]: print(f'  {k}: {e["text"]}')
    if write:
        doc = dict(version=1, generated=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
                   note='Drivers Notes read off the run route maps (PDF), keyed Stream#Day#Week#Run (Garbage: Garbage#Day#Run). '
                        'The app matches each note to the run streets it mentions.', runs=runs)
        json.dump(doc, open(os.path.join(REPO, 'data', 'run-notes.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
        print('wrote data/run-notes.json')

if __name__ == '__main__':
    run('--write' in sys.argv)
