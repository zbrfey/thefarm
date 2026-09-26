# -*- coding: utf-8 -*-
"""build_media_full.py — full pool (65). One composite aerial per farm (imagery +
cadastral boundaries + highlighted target parcel, baked = also the 3D texture),
a DEM heightmap, and 2 ad photos. Keeps files/farm = 3 to fit the 255-file cap."""
import os, io, json, math, time
import numpy as np, requests
from PIL import Image, ImageDraw, ImageFilter
from pyproj import Transformer
H={"User-Agent":"thefarm-research/1.0 (husebyja@gmail.com)"}
M="data/media"; os.makedirs(M, exist_ok=True)
T33=Transformer.from_crs(4326,25833,always_xy=True); T87=Transformer.from_crs(4326,3857,always_xy=True)
farms=json.load(open("data/farms.json",encoding="utf-8"))
photos=json.load(open("data/photos.json",encoding="utf-8"))
SZ=640
def fetch(u,tries=3):
    for i in range(tries):
        try:
            r=requests.get(u,headers=H,timeout=45)
            if r.status_code==200 and r.content: return r.content
        except Exception: pass
        time.sleep(0.5*(i+1))
    return None
def esri(bb,sr): return fetch(f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export?bbox={bb[0]},{bb[1]},{bb[2]},{bb[3]}&bboxSR={sr}&imageSR={sr}&size={SZ},{SZ}&format=jpg&f=image")
def wms(bb,sr): return fetch(f"https://wms.geonorge.no/skwms1/wms.matrikkelkart?service=WMS&version=1.1.1&request=GetMap&layers=eiendomsgrense&styles=&srs=EPSG:{sr}&bbox={bb[0]},{bb[1]},{bb[2]},{bb[3]}&width={SZ}&height={SZ}&format=image/png&transparent=true")
def dem(bb):
    c=fetch(f"https://wcs.geonorge.no/skwms1/wcs.hoyde-dtm-nhm-25833?service=WCS&version=1.0.0&request=GetCoverage&coverage=nhm_dtm_topo_25833&crs=EPSG:25833&bbox={bb[0]},{bb[1]},{bb[2]},{bb[3]}&width=64&height=64&format=GeoTIFF")
    if not c: return None
    try:
        a=np.array(Image.open(io.BytesIO(c))).astype(float); a[a<-1000]=np.nan; return a
    except Exception: return None
def yellow_lines(bnd_png):
    im=Image.open(io.BytesIO(bnd_png)).convert("RGBA"); a=np.array(im)
    mask=Image.fromarray((a[:,:,3]>40).astype(np.uint8)*255).filter(ImageFilter.MaxFilter(3)); m=np.array(mask)>0
    out=np.zeros_like(a); out[m]=(255,214,0,255); return Image.fromarray(out,"RGBA"), m
def highlight(mwall):
    W=Hh=SZ; canv=np.full((Hh,W,3),255,np.uint8); canv[mwall]=0
    canv[:2,:]=0;canv[-2:,:]=0;canv[:,:2]=0;canv[:,-2:]=0; ci=Image.fromarray(canv)
    cx=cy=SZ//2
    if mwall[cy,cx]:
        found=False
        for r in range(1,50):
            for dx in range(-r,r+1):
                for dy in range(-r,r+1):
                    x,y=cx+dx,cy+dy
                    if 0<=x<W and 0<=y<Hh and not mwall[y,x]: cx,cy=x,y; found=True; break
                if found: break
            if found: break
    ImageDraw.floodfill(ci,(cx,cy),(255,0,0),thresh=10)
    fill=np.array(ci); region=(fill[:,:,0]==255)&(fill[:,:,1]==0)&(fill[:,:,2]==0); frac=region.mean()
    ov=np.zeros((Hh,W,4),np.uint8)
    if 0.002<frac<0.7:
        ov[region]=(50,200,255,105)
        ri=Image.fromarray((region*255).astype(np.uint8))
        edge=(np.array(ri.filter(ImageFilter.MaxFilter(9)))>0)&~(np.array(ri.filter(ImageFilter.MinFilter(3)))>0)
        ov[edge]=(0,234,255,255)
    return Image.fromarray(ov,"RGBA")
def save_photo(url,path):
    url=url.split()[0]
    c=fetch(url)
    if not c: return False
    try:
        im=Image.open(io.BytesIO(c)).convert("RGB")
        if im.width>900: im=im.resize((900,round(im.height*900/im.width)),Image.LANCZOS)
        im.save(path,"JPEG",quality=72,optimize=True); return True
    except Exception: return False

terrain={}
if os.path.exists("data/terrain.json"):
    terrain=json.load(open("data/terrain.json",encoding="utf-8"))
for f in farms:
    fk=f["finnkode"]; lat=f["geo"]["lat"]; lon=f["geo"]["lon"]
    have_aer=os.path.exists(f"{M}/{fk}_aer.jpg")
    if have_aer and fk in terrain:
        ph=photos.get(fk,[]); n=sum(1 for i in range(2) if os.path.exists(f"{M}/{fk}_p{i}.jpg"))
        if n>=1:
            print(f"{fk} {f['place'][:14]:14} skip (cached)")
            continue
    if lat:
        daa=f["land"]["total_daa"] or 50; half=max(160,min(650,math.sqrt(daa*1000/math.pi)*1.35))
        x33,y33=T33.transform(lon,lat); bb33=[x33-half,y33-half,x33+half,y33+half]
        ae=esri(bb33,25833); sr=25833; bb=bb33
        if not ae:
            x87,y87=T87.transform(lon,lat); h87=half/math.cos(math.radians(lat))
            bb=[x87-h87,y87-h87,x87+h87,y87+h87]; sr=3857; ae=esri(bb,3857)
        if ae:
            base=Image.open(io.BytesIO(ae)).convert("RGB")
            bnd=wms(bb,sr)
            if bnd:
                lines,mwall=yellow_lines(bnd)
                hl=highlight(mwall)
                base.paste(hl,(0,0),hl); base.paste(lines,(0,0),lines)
            base.save(f"{M}/{fk}_aer.jpg","JPEG",quality=82,optimize=True)
        d=dem(bb33)
        if d is not None:
            zmin=float(np.nanmin(d)); zmax=float(np.nanmax(d)); d=np.where(np.isnan(d),zmin,d)
            terrain[fk]={"n":64,"span_m":round(2*half,1),"zmin":round(zmin,1),"zmax":round(zmax,1),"z":[int(round(v)) for v in d.flatten()]}
    ph=photos.get(fk,[]); n=0
    for u in ph[:4]:
        if save_photo(u,f"{M}/{fk}_p{n}.jpg"): n+=1
        if n>=2: break
    print(f"{fk} {f['place'][:14]:14} aer={os.path.exists(f'{M}/{fk}_aer.jpg')} dem={fk in terrain} photos={n}")
    time.sleep(0.1)
json.dump(terrain,open("data/terrain.json","w"),separators=(",",":"))
print("terrain",len(terrain),"| media MB",round(sum(os.path.getsize(M+'/'+x) for x in os.listdir(M))/1e6,1))
