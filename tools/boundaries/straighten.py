"""Stage 2: straighten the shared edges of the cleaned atom partition (several passes), then build every run from its atoms."""
import sys, time, pickle
import neat
from neat import *; from houses import *
t0=time.time()
def log(*a): print('[%5.0fs]'%(time.time()-t0),*a,flush=True)
PASSES=int(sys.argv[2]) if len(sys.argv)>2 else 3
if len(sys.argv)>3: neat.A_MAX=float(sys.argv[3])
if len(sys.argv)>4: neat.CLEAR=float(sys.argv[4])
if len(sys.argv)>5: neat.SPIKE_DEG=float(sys.argv[5])
d,runs=load(); H=load_houses()
hx=np.array([h['x'] for h in H]); hy=np.array([h['y'] for h in H])
htree=STRtree(mkpoints(np.c_[hx,hy]))
D=pickle.load(open('cl.pkl','rb')); P=D['cl']; keys=D['keys']; names=D['names']; tk=D['tk']; HT=D['HT']
def pts(Pd): return sum(len(p.exterior.coords) for g in Pd.values() for p in polys_of(g))
log('atoms',len(keys),'points',pts(P))
for pas in range(PASSES):
    live=[k for k in keys if not P[k].is_empty]
    bnd=unary_union([P[k].boundary for k in live])
    merged=linemerge(bnd)
    lines=list(merged.geoms) if merged.geom_type=='MultiLineString' else [merged]
    simp=simplify_lines(lines,htree,hx,hy)
    faces=list(polygonize(unary_union(simp)))
    tree=STRtree([P[k] for k in live]); out={k:[] for k in keys}
    for f in faces:
        best=None; ba=0
        for i in tree.query(f):
            a=f.intersection(P[live[int(i)]]).area
            if a>ba: ba=a; best=live[int(i)]
        if best and ba>0.5*f.area: out[best].append(f)
    P={k:(mp(unary_union(v)) if v else Polygon()) for k,v in out.items()}
    log('pass',pas+1,'lines',len(lines),'points',pts(P))
LAYERS=['Garbage','Recycling','FOGO']
res={}
for li,layer in enumerate(LAYERS):
    by=collections.defaultdict(list)
    for t in tk:
        if t[li] and not P[names[t]].is_empty: by[t[li]].append(P[names[t]])
    for k in runs:
        if k.startswith(layer+'#'): res[k]=mp(unary_union(by[k])) if by.get(k) else Polygon()
# crumbs: tiny loose parts with none of the run's houses in them
E=np.array([])
idx_by=[collections.defaultdict(list) for _ in LAYERS]
for i,t in enumerate(HT):
    for li in range(3):
        if t[li]: idx_by[li][t[li]].append(i)
for li,layer in enumerate(LAYERS):
    b=a=tot=0; lost=[]; npt=0
    for k in list(res):
        if not k.startswith(layer+'#'): continue
        ii=idx_by[li].get(k,[]); xs,ys=(hx[ii],hy[ii]) if ii else (E,E)
        ps=polys_of(res[k])
        if len(ps)>1:
            big=max(p.area for p in ps)
            ps=[p for p in ps if p.area==big or p.area>=1500 or count_in(p,xs,ys)>0]
            res[k]=mp(unary_union(ps))
        tot+=len(ii); b+=count_in(runs[k],xs,ys); a+=count_in(res[k],xs,ys)
        npt+=sum(len(p.exterior.coords) for p in polys_of(res[k]))
        if res[k].is_empty: lost.append(k)
    log(layer,'houses inside own run: before %d after %d of %d'%(b,a,tot),'points',npt,'empty',lost)
for k in runs:
    if res.get(k) is None or res[k].is_empty:
        res[k]=mp(runs[k].simplify(3)); log('kept as drawn (no houses to go by):',k)
pickle.dump(res,open('res_final.pkl','wb'))
out={'boundaries':{},'extras':{}}
for k,g in res.items():
    ps=sorted(polys_of(g),key=lambda p:-p.area)
    if not ps: continue
    out['boundaries'][k]=to_ll(list(ps[0].exterior.coords)[:-1])
    if len(ps)>1: out['extras'][k]=[to_ll(list(p.exterior.coords)[:-1]) for p in ps[1:]]
json.dump(out,open(sys.argv[1] if len(sys.argv)>1 else 'final.json','w'))
n=sum(len(v) for v in out['boundaries'].values())+sum(len(r) for v in out['extras'].values() for r in v)
log('done; runs',len(out['boundaries']),'points',n,'extra rings',sum(len(v) for v in out['extras'].values()))
