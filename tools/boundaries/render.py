import sys, json, math, colorsys
from PIL import Image, ImageDraw
def render(path, out, bbox=(-38.352,144.885,-38.372,144.915), W=1400, only=None, houses=None):
    d=json.load(open(path))
    lat1,lng1,lat0,lng0=bbox[0],bbox[1],bbox[2],bbox[3]
    kx=math.cos(math.radians(lat1)); H=int(W*(lat1-lat0)/((lng0-lng1)*kx))
    im=Image.new('RGB',(W,H),(24,26,30)); dr=ImageDraw.Draw(im)
    def P(p): return ((p[1]-lng1)/(lng0-lng1)*W, (lat1-p[0])/(lat1-lat0)*H)
    if houses:
        for la,ln in houses:
            if lat0<la<lat1 and lng1<ln<lng0:
                x,y=P((la,ln)); dr.ellipse([x-1.5,y-1.5,x+1.5,y+1.5],fill=(90,90,90))
    ks=sorted(d['boundaries'])
    for i,k in enumerate(ks):
        if only and not only(k): continue
        h=(i*0.6180339)%1; c=tuple(int(v*255) for v in colorsys.hsv_to_rgb(h,0.85,1))
        for ring in [d['boundaries'][k]]+d.get('extras',{}).get(k,[]):
            pts=[P(p) for p in ring]
            if len(pts)>2: dr.line(pts+[pts[0]],fill=c,width=2)
    im.save(out); print(out, im.size)
if __name__=='__main__':
    sel=sys.argv[3] if len(sys.argv)>3 else ''
    render(sys.argv[1], sys.argv[2], only=(lambda k: k.startswith(sel)) if sel else None)
