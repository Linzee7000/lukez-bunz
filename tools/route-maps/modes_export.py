import json, math, re, csv, sys, collections, datetime
import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import LineString, MultiLineString
from shapely.ops import unary_union
import os; os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'work')); sys.argv=['x','NONE']; exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'compare.py')).read().split('results = []')[0])
import glob
routes={}; res={}
for f in sorted(glob.glob('routes-m*.json')): routes.update(json.load(open(f)))
for f in sorted(glob.glob('compare-results*.json')):
    for r in json.load(open(f)):
        if 'fit_m' in r: res[r['tag']]=r
pts,addrs=[],[]
with open('master.csv',newline='',encoding='utf8') as f:
    for row in csv.DictReader(f):
        try: lat,lng=float(row['Lat']),float(row['Lng'])
        except: continue
        pts.append(to_m(lat,lng)); addrs.append(row['Address'])
tree=cKDTree(np.array(pts))
def street(a):
    a=a.split(',')[0]; a=re.sub(r'^(Unit|Shop|Lot|Suite)\s+[\w/-]+/','',a,flags=re.I); a=re.sub(r'^[\w/-]*\d[\w/-]*\s+','',a); return a.strip().title()
TYPE={'purple':'reverse-in-drive-out','orange':'drive-reverse-out'}
cover={'purple':None,'orange':None}; kept=[]
order=sorted(res, key=lambda t: res[t]['fit_m'])          # best-placed pages first, so they win when pages overlap
for tag in order:
    if res[tag]['fit_m']>20: continue
    for name in ('purple','orange'):
        for pl in routes[tag].get(name,[]):
            xy=[(x*KX,y*KY) for x,y in pl]                    # stored as (dlng,dlat) offsets -> metres
            if len(xy)<2: continue
            ln=LineString(xy)
            if cover[name] is not None: ln=ln.difference(cover[name])
            parts=[ln] if ln.geom_type=='LineString' else list(getattr(ln,'geoms',[]))
            for p in parts:
                if p.is_empty or p.length<12 or p.geom_type!='LineString': continue
                kept.append((name,p,tag))
                b=p.buffer(10)
                cover[name]=b if cover[name] is None else unary_union([cover[name],b])
segs=[]; names=collections.Counter()
for name,p,tag in kept:
    cs=list(p.coords)
    # simplify lightly (0.8 m) to keep the file small
    p2=p.simplify(0.8); cs=list(p2.coords)
    mid=p.interpolate(0.5,normalized=True); d,i=tree.query([mid.x,mid.y])
    st=street(addrs[i]) if d<60 else ''
    names[(TYPE[name],st)]+=p.length
    segs.append({'type':TYPE[name],'street':st,'src':tag.split(' ',2)[2],
                 'points':[[round(LAT0+y/KY,5),round(LNG0+x/KX,5)] for x,y in cs]})
out={'version':1,'generated':datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
     'note':'Street driving modes read from the recycle run route maps (PDF): purple = reverse in / drive out, orange = drive in / reverse out. Position is approximate (placed by matching each map to its houses). Applies to all kerbside streams.',
     'segments':segs}
json.dump(out,open('street-modes.json','w'),separators=(',',':'))
L={t:sum(p.length for n,p,_ in kept if TYPE[n]==t)/1000 for t in TYPE.values()}
print('segments',len(segs),' reverse-in km %.1f  drive-in km %.1f'%(L['reverse-in-drive-out'],L['drive-reverse-out']),' file bytes',len(json.dumps(out,separators=(',',':'))))
