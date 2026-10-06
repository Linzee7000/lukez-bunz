import json, math, collections
ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from shapely.validation import make_valid
LAT0=-38.35; KX=111320*math.cos(math.radians(LAT0)); KY=110574
def to_m(ring): return [((p[1]-144.9)*KX,(p[0]-LAT0)*KY) for p in ring]
def to_ll(coords): return [[round(y/KY+LAT0,6), round(x/KX+144.9,6)] for x,y in coords]
def poly(ring):
    p=Polygon(to_m(ring))
    if not p.is_valid: p=make_valid(p)
    if p.geom_type!='Polygon' and p.geom_type!='MultiPolygon':
        p=unary_union([g for g in getattr(p,'geoms',[p]) if g.geom_type in('Polygon','MultiPolygon')])
    return p
def load(path=None):
    path=path or str(ROOT/'data'/'run-boundaries.json')
    d=json.load(open(path))
    runs={}
    for k,ring in d['boundaries'].items():
        parts=[poly(ring)]+[poly(r) for r in d.get('extras',{}).get(k,[]) if len(r)>=3]
        runs[k]=unary_union(parts)
    return d,runs
def group(k):
    a=k.split('#'); return tuple(a[:-1])
