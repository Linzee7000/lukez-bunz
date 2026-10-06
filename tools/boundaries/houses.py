import csv, collections
from geo import *
def load_houses(path=None):
    path=path or str(ROOT/'master_combined_with_metadata_complete_v3.csv')
    out=[]
    with open(path,encoding='utf-8',errors='replace') as f:
        r=csv.reader(f); h=next(r)
        for row in r:
            try: la=float(row[20]); ln=float(row[21])
            except: continue
            if not(-39<la<-37.9 and 144.5<ln<145.6): continue
            day=row[5].strip(); wk=row[6].strip().upper()[:1]
            g=row[7].split('|')[0].strip(); rc=row[8].split('|')[0].strip(); fg=row[10].split('|')[0].strip()
            out.append(dict(x=(ln-144.9)*KX,y=(la-LAT0)*KY,day=day,wk=wk,g=g,rc=rc,fg=fg))
    return out
