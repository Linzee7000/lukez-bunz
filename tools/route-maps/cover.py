import csv, json, math, sys, collections, subprocess
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
from shapely import prepared, contains_xy
import numpy as np
LAT0, LNG0 = -38.30, 144.95
KX = 111320*math.cos(math.radians(LAT0)); KY = 110540.0
def to_m(lat, lng): return ((lng-LNG0)*KX, (lat-LAT0)*KY)
NEW = json.load(open('/Users/bigsms/Projects/binz/data/run-boundaries.json'))
OLD = json.loads(subprocess.run(['git','-C','/Users/bigsms/Projects/binz','show','5d2c3bc:data/run-boundaries.json'],capture_output=True,text=True).stdout)
def geom(bd, key):
    k = key if key in bd['boundaries'] else bd.get('aliases',{}).get(key)
    if not k or k not in bd['boundaries']: return None
    polys=[]
    for r in [bd['boundaries'][k]] + bd.get('extras',{}).get(k,[]):
        pts=[to_m(p[0],p[1]) for p in r]
        if len(pts)>=3:
            pg=Polygon(pts)
            if not pg.is_valid: pg=pg.buffer(0)
            if not pg.is_empty: polys.append(pg)
    return unary_union(polys) if polys else None
groups = collections.defaultdict(list)
with open('master.csv', newline='', encoding='utf8') as f:
    for row in csv.DictReader(f):
        try: lat,lng=float(row['Lat']),float(row['Lng'])
        except: continue
        d=row['Solo Collection Day'].strip(); w=row['Solo Week Cycle'].strip().upper(); p=to_m(lat,lng)
        g=row['Solo Garbage Run'].strip(); r=row['Solo Recycling Run'].strip(); fo=row['Solo FOGO Run'].strip()
        if g: groups[f'Garbage#{d}#{g.lower()}'].append(p)
        if r: groups[f'Recycling#{d}#{w}#{r.lower()}'].append(p)
        if fo: groups[f'FOGO#{d}#{w}#{fo.lower()}'].append(p)
def cov(g, pts):
    if g is None or not len(pts): return None
    a=np.array(pts); g2=g.buffer(8)
    return float(contains_xy(g2, a[:,0], a[:,1]).mean())
rows=[]
for key in NEW['boundaries']:
    parts=key.split('#'); k2='#'.join(parts[:-1]+[parts[-1].lower()])
    pts=groups.get(k2) or groups.get(key) or []
    if len(pts)<15: continue
    gn,go=geom(NEW,key),geom(OLD,key)
    rows.append((key,len(pts),cov(gn,pts),cov(go,pts)))
rows.sort(key=lambda r:(r[2] if r[2] is not None else 0))
n=len(rows); print('runs checked:',n)
print('mean houses inside  NEW %.1f%%   OLD %.1f%%'%(100*np.mean([r[2] for r in rows]),100*np.mean([r[3] for r in rows if r[3] is not None])))
bad=[r for r in rows if r[2] is not None and r[3] is not None and r[2] < 0.90 and r[3]-r[2] > 0.05]
print('runs where NEW covers <90%% of houses and OLD covers 5+ points more: %d'%len(bad))
for r in rows[:25]: print('  %-32s %5d houses  NEW %5.1f%%  OLD %5.1f%%'%(r[0],r[1],100*r[2],100*(r[3] or 0)))
json.dump([dict(key=r[0],houses=r[1],new=r[2],old=r[3]) for r in rows], open('cover.json','w'))
