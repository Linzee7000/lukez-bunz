"""Neaten run boundaries: one clean partition per (stream, day, week).
   thin road stubs with no houses go, overlaps and gaps are resolved (by the houses, then by nearest run),
   and the shared edges are straightened as far as they can go without any house changing side."""
import heapq, numpy as np
from geo import *
from shapely.geometry import Polygon, MultiPolygon, LineString, Point, GeometryCollection
from shapely.ops import unary_union, linemerge, polygonize
from shapely import STRtree, contains_xy, points as mkpoints
import shapely

OPEN_W=6.0       # fingers narrower than 2*OPEN_W with no houses are removed
CLOSE_R=22.0     # gaps / notches narrower than 2*CLOSE_R are filled
STEP=2.5; NSTEP=14
A_MAX=1800.0     # biggest triangle a vertex removal may sweep (m2)
SPIKE_A=40000.0
SPIKE_DEG=40.0
CLEAR=5.0        # a straightened edge stays this far from every house

def polys_of(g):
    if g is None or g.is_empty: return []
    if g.geom_type=='Polygon': return [g]
    if g.geom_type in('MultiPolygon','GeometryCollection'): return [p for x in g.geoms for p in polys_of(x)]
    return []
def mp(g):
    ps=[p for p in polys_of(g) if p.area>0.5]
    return unary_union(ps) if ps else Polygon()
def count_in(geom, xs, ys):
    if geom.is_empty or len(xs)==0: return 0
    return int(contains_xy(geom, xs, ys).sum())

def clean_group(keys, P, HX, HY):
    """P: key->geom, HX/HY: key->np arrays of that run's houses"""
    P={k:mp(P[k]) for k in keys}
    # A. thin house-less fingers
    for k in keys:
        g=P[k]
        if g.is_empty: continue
        op=mp(g.buffer(-OPEN_W,join_style=2,mitre_limit=3).buffer(OPEN_W,join_style=2,mitre_limit=3).intersection(g))
        rem=g.difference(op)
        keep=[p for p in polys_of(rem) if p.area>20 and count_in(p,HX[k],HY[k])>=3]
        P[k]=mp(unary_union([op]+keep)) if keep else op
    # B. overlaps: to the run with more of its own houses there, else the one with more ground around it
    trB=STRtree([P[k] for k in keys]); pairs=set()
    for a in range(len(keys)):
        if P[keys[a]].is_empty: continue
        for b in trB.query(P[keys[a]],predicate='intersects'):
            b=int(b)
            if b>a: pairs.add((a,b))
    for a,b in sorted(pairs):
            ka,kb=keys[a],keys[b]
            if P[ka].is_empty or P[kb].is_empty or not P[ka].intersects(P[kb]): continue
            O=P[ka].intersection(P[kb])
            for part in polys_of(O):
                if part.area<0.5: continue
                na=count_in(part,HX[ka],HY[ka]); nb=count_in(part,HX[kb],HY[kb])
                if na==nb:
                    ring=part.buffer(20).difference(part)
                    na=ring.intersection(P[ka]).area; nb=ring.intersection(P[kb]).area
                loser=kb if na>=nb else ka
                P[loser]=mp(P[loser].difference(part.buffer(0.01)))
    # C. crumbs with no houses
    for k in keys:
        ps=polys_of(P[k])
        if len(ps)>1:
            big=max(p.area for p in ps)
            ps=[p for p in ps if p.area==big or p.area>=600 or count_in(p,HX[k],HY[k])>0]
            P[k]=mp(unary_union(ps))
    # D. gaps: every run grows into the free ground between them at the same pace, so they meet in the middle
    U=unary_union([P[k] for k in keys])
    closed=U.buffer(CLOSE_R).buffer(-CLOSE_R)
    holes=[Polygon(r) for p in polys_of(closed) for r in p.interiors]
    closed=unary_union([closed]+[h for h in holes if h.area<20000])
    free=closed.difference(U)
    # worked gap by gap, on just the ground around each gap, so a big partition stays quick
    live=[k for k in keys if not P[k].is_empty]
    trD=STRtree([P[k] for k in live]); adds={k:[] for k in keys}
    for F in polys_of(free):
        if F.area<0.5: continue
        near=[live[int(i)] for i in trD.query(F.buffer(STEP*1.5),predicate='intersects')]
        if not near: continue
        if len(near)==1: adds[near[0]].append(F); continue
        box=F.buffer(NSTEP*STEP+6).envelope
        loc={k:P[k].intersection(box) for k in near}
        rem=F
        for it in range(NSTEP):
            if rem.is_empty or rem.area<0.5: break
            near=near[1:]+near[:1]
            for k in near:
                if loc[k].is_empty: continue
                g=loc[k].buffer(STEP,join_style=2,mitre_limit=2).intersection(rem)
                if g.is_empty or g.area<0.01: continue
                loc[k]=loc[k].union(g); adds[k].append(g); rem=rem.difference(g)
    for k in keys:
        if adds[k]: P[k]=mp(unary_union([P[k]]+adds[k]))
    return P

def tri_area(a,b,c): return abs((b[0]-a[0])*(c[1]-a[1])-(c[0]-a[0])*(b[1]-a[1]))/2

def simplify_lines(lines, htree, hx, hy, frozen=None):
    """house-aware Visvalingam: drop a vertex only if the triangle it sweeps holds no house (with CLEAR margin)
       and no vertex of any other line. End points (junctions) never move."""
    frozen=frozen or set()
    allpts=[]; owner=[]; local=[]
    for li,l in enumerate(lines):
        for ci,c in enumerate(l.coords): allpts.append(c); owner.append(li); local.append(ci)
    owner=np.array(owner); local=np.array(local); vtree=STRtree(mkpoints(np.array(allpts)))
    out=[]
    for li,l in enumerate(lines):
        cs=[tuple(c) for c in l.coords]; n=len(cs)
        closed=cs[0]==cs[-1]
        if n<4 and closed: out.append(l); continue
        if n<3: out.append(l); continue
        prev=list(range(-1,n-1)); nxt=list(range(1,n+1)); alive=[True]*n
        lo,hi=1,n-1          # interior vertices 1..n-2 ; a closed ring keeps its start point
        ver=[0]*n; heap=[]
        def blocked(idx,i):
            for q in idx:
                if owner[q]!=li: return True
                j=int(local[q])
                if alive[j] and j not in (prev[i],i,nxt[i]): return True
            return False
        def push(i):
            a=cs[prev[i]]; b=cs[i]; c=cs[nxt[i]]
            heapq.heappush(heap,(tri_area(a,b,c),ver[i],i))
        for i in range(lo,hi): push(i)
        left=n
        while heap:
            ar,v,i=heapq.heappop(heap)
            if not alive[i] or v!=ver[i]: continue
            if ar>A_MAX: break
            if closed and left<=5: break
            if (round(cs[i][0],3),round(cs[i][1],3)) in frozen: continue
            a=cs[prev[i]]; b=cs[i]; c=cs[nxt[i]]
            ok=True
            if ar>1e-6:
                tri=Polygon([a,b,c])
                if not tri.is_valid: tri=tri.buffer(0)
                q=tri.buffer(CLEAR)
                if len(htree.query(q,predicate='intersects'))>0: ok=False
                else:
                    idx=vtree.query(tri,predicate='contains_properly')
                    if len(idx) and blocked(idx,i): ok=False
            if not ok: continue
            alive[i]=False; left-=1
            p,nx=prev[i],nxt[i]; nxt[p]=nx; prev[nx]=p
            for j in (p,nx):
                if lo<=j<hi and alive[j]: ver[j]+=1; push(j)
        # spikes: a corner sharper than 40 degrees that no house needs is cut off, whatever its size (up to SPIKE_A)
        changed=True
        while changed:
            changed=False
            i=nxt[0] if n>1 else n
            while i<n-1:
                if alive[i]:
                    a=cs[prev[i]]; b=cs[i]; c=cs[nxt[i]]
                    v1=(a[0]-b[0],a[1]-b[1]); v2=(c[0]-b[0],c[1]-b[1])
                    l1=math.hypot(*v1); l2=math.hypot(*v2)
                    if l1>0 and l2>0 and not (closed and left<=5):
                        cosang=(v1[0]*v2[0]+v1[1]*v2[1])/(l1*l2)
                        ar=tri_area(a,b,c)
                        if cosang>math.cos(math.radians(SPIKE_DEG)) and ar<SPIKE_A and (round(b[0],3),round(b[1],3)) not in frozen:
                            ok=True
                            if ar>1e-6:
                                tri=Polygon([a,b,c])
                                if not tri.is_valid: tri=tri.buffer(0)
                                if len(htree.query(tri.buffer(CLEAR),predicate='intersects'))>0: ok=False
                                else:
                                    idx=vtree.query(tri,predicate='contains_properly')
                                    if len(idx) and blocked(idx,i): ok=False
                            if ok:
                                alive[i]=False; left-=1; p,nx=prev[i],nxt[i]; nxt[p]=nx; prev[nx]=p; changed=True
                i=nxt[i] if alive[i] else nxt[i]
        out.append(LineString([cs[i] for i in range(n) if alive[i]]))
    return out

def neaten_group(keys, P, HX, HY, htree, hx, hy):
    P=clean_group(keys,P,HX,HY)
    bnd=unary_union([P[k].boundary for k in keys if not P[k].is_empty])
    merged=linemerge(bnd)
    lines=list(merged.geoms) if merged.geom_type=='MultiLineString' else [merged]
    simp=simplify_lines(lines,htree,hx,hy)
    faces=list(polygonize(unary_union(simp)))
    out={k:[] for k in keys}
    tree=STRtree([P[k] for k in keys])
    for f in faces:
        best=None; ba=0
        for i in tree.query(f):
            a=f.intersection(P[keys[i]]).area
            if a>ba: ba=a; best=keys[i]
        if best and ba>0.5*f.area: out[best].append(f)
    return {k:(unary_union(v) if v else Polygon()) for k,v in out.items()}, P
