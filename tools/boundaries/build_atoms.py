"""Step 1 of 2 (then straighten.py). All streams, days and weeks neatened as ONE map, so that wherever two runs (of any stream) run along the same road
   they use the very same line. See neat.py for the per-partition steps."""
import sys, time, pickle
from neat import *; from houses import *
t0=time.time()
def log(*a): print('[%5.0fs]'%(time.time()-t0),*a,flush=True)
d,runs=load(); H=load_houses()
hx=np.array([h['x'] for h in H]); hy=np.array([h['y'] for h in H])
# runs with (almost) no houses in the csv cannot be checked against anything: they stay exactly as drawn and take no part here
_c=collections.Counter()
for h in H:
    _c[f"Garbage#{h['day']}#{h['g']}"]+=1; _c[f"Recycling#{h['day']}#{h['wk']}#{h['rc']}"]+=1; _c[f"FOGO#{h['day']}#{h['wk']}#{h['fg']}"]+=1
KEEP=set(k for k in runs if _c.get(k,0)<30)
runs={k:v for k,v in runs.items() if k not in KEEP}
log('kept as drawn:',sorted(KEEP))
htree=STRtree(mkpoints(np.c_[hx,hy]))
def hkeys(h):
    g=f"Garbage#{h['day']}#{h['g']}" if h['g'] else None
    r=f"Recycling#{h['day']}#{h['wk']}#{h['rc']}" if h['rc'] else None
    f=f"FOGO#{h['day']}#{h['wk']}#{h['fg']}" if h['fg'] else None
    return tuple(k if (k in runs) else None for k in (g,r,f))
HT=[hkeys(h) for h in H]
E=np.array([])
LAYERS=['Garbage','Recycling','FOGO']
def arrs(pred):
    idx=[i for i in range(len(H)) if pred(i)]
    return hx[idx],hy[idx]
# 1. each stream cleaned as one partition
stage1='stage1.pkl'
try:
    L={layer:pickle.load(open('layer_%s.pkl'%layer,'rb')) for layer in LAYERS}; log('layers loaded')
except Exception:
    L={}
    for li,layer in enumerate(LAYERS):
        ks=sorted(k for k in runs if k.startswith(layer+'#'))
        by=collections.defaultdict(list)
        for i,t in enumerate(HT):
            if t[li]: by[t[li]].append(i)
        HX={k:hx[by[k]] if by[k] else E for k in ks}; HY={k:hy[by[k]] if by[k] else E for k in ks}
        L[layer]=clean_group(ks,{k:runs[k] for k in ks},HX,HY)
        log(layer,'cleaned',len(ks))
        pickle.dump(L[layer],open('layer_%s.pkl'%layer,'wb'))
    pickle.dump(L,open(stage1,'wb'))
# 2. overlay -> atoms
allb=unary_union([g.boundary for layer in LAYERS for g in L[layer].values() if not g.is_empty])
faces=list(polygonize(allb)); log('faces',len(faces))
trees={layer:(list(L[layer].keys()),STRtree([L[layer][k] for k in L[layer]])) for layer in LAYERS}
atoms=collections.defaultdict(list)
for f in faces:
    rp=f.representative_point(); t=[]
    for layer in LAYERS:
        ks,tr=trees[layer]; hit=None
        for i in tr.query(rp,predicate='within'): hit=ks[i]; break
        t.append(hit)
    t=tuple(t)
    if t!=(None,None,None): atoms[t].append(f)
A={t:mp(unary_union(v)) for t,v in atoms.items()}
log('atoms',len(A))
# houses per atom
hby=collections.defaultdict(list)
for i,t in enumerate(HT):
    if t in A: hby[t].append(i)
AX={t:(hx[hby[t]] if hby[t] else E) for t in A}; AY={t:(hy[hby[t]] if hby[t] else E) for t in A}
def nh(t): return count_in(A[t],AX[t],AY[t])
# 3. atoms nobody lives in are only the slivers between two streams' lines: fold each into the neighbour it shares most edge with
changed=True; rounds=0
while changed and rounds<6:
    changed=False; rounds+=1
    keys=list(A.keys()); tr=STRtree([A[t] for t in keys])
    empty=[t for t in keys if nh(t)==0]
    empty.sort(key=lambda t:A[t].area)
    gone=set()
    for t in empty:
        if t in gone or A[t].is_empty: continue
        best=None; bl=0
        for i in tr.query(A[t].buffer(0.5)):
            u=keys[i]
            if u==t or u in gone or A[u].is_empty: continue
            try: sl=A[t].buffer(0.5).intersection(A[u].boundary).length
            except Exception: sl=0
            if nh(u)>0: sl*=4      # prefer a neighbour that really has houses
            if sl>bl: bl=sl; best=u
        if best is not None and bl>1:
            A[best]=mp(A[best].union(A[t])); gone.add(t); changed=True
    for t in gone: del A[t]
    log('merge round',rounds,'gone',len(gone),'left',len(A))
tk=list(A.keys())
names={t:'|'.join(str(x) for x in t) for t in tk}
P={names[t]:A[t] for t in tk}
HX={names[t]:AX[t] for t in tk}; HY={names[t]:AY[t] for t in tk}
keys=sorted(P.keys())
# 4. one partition: fingers and gaps
cl=clean_group(keys,P,HX,HY)
log('atoms cleaned')
pickle.dump(dict(cl=cl,keys=keys,names=names,tk=tk,HX=HX,HY=HY,HT=HT),open('cl.pkl','wb'))
log('saved cl.pkl')
