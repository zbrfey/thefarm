# -*- coding: utf-8 -*-
"""build_geo.py — per farm: property-framed aerial (Esri, EPSG:25833), real
cadastral boundary overlay (Kartverket matrikkel WMS), wide context aerial,
a 3D-ready texture (aerial+boundary), and a DEM heightmap (Kartverket WCS).
All aligned to one square UTM33 bbox so aerial/overlay/DEM register exactly."""
import os, io, json, time, math
import requests
import numpy as np
from PIL import Image, ImageFilter
from pyproj import Transformer

H = {"User-Agent": "thefarm-research/1.0 (husebyja@gmail.com)"}
MEDIA = "data/media"; os.makedirs(MEDIA, exist_ok=True)
T = Transformer.from_crs(4326, 25833, always_xy=True)
farms = json.load(open("data/farms.json", encoding="utf-8"))
SZ = 640  # px for aerial/overlay

def fetch(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, headers=H, timeout=45)
            if r.status_code == 200 and r.content: return r.content
        except Exception: pass
        time.sleep(0.6*(i+1))
    return None

def esri(bbox, sz=SZ):
    u=(f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
       f"?bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}&bboxSR=25833&imageSR=25833&size={sz},{sz}&format=jpg&f=image")
    return fetch(u)

def wms_boundary(bbox, sz=SZ):
    u=(f"https://wms.geonorge.no/skwms1/wms.matrikkelkart?service=WMS&version=1.1.1&request=GetMap"
       f"&layers=eiendomsgrense&styles=&srs=EPSG:25833&bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
       f"&width={sz}&height={sz}&format=image/png&transparent=true")
    return fetch(u)

def recolor(png_bytes, rgb=(255,214,0)):
    im=Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    a=np.array(im); alpha=a[:,:,3]
    # thicken lines a touch
    mask=Image.fromarray((alpha>40).astype("uint8")*255).filter(ImageFilter.MaxFilter(3))
    m=np.array(mask)>0
    out=np.zeros_like(a); out[m]=[rgb[0],rgb[1],rgb[2],255]
    return Image.fromarray(out,"RGBA")

def dem(bbox, n=64):
    u=(f"https://wcs.geonorge.no/skwms1/wcs.hoyde-dtm-nhm-25833?service=WCS&version=1.0.0&request=GetCoverage"
       f"&coverage=nhm_dtm_topo_25833&crs=EPSG:25833&bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
       f"&width={n}&height={n}&format=GeoTIFF")
    c=fetch(u)
    if not c: return None
    try:
        a=np.array(Image.open(io.BytesIO(c))).astype(float)
        a[a<-1000]=np.nan
        return a
    except Exception: return None

terrain={}
for f in farms:
    fk=f["finnkode"]; lat=f["geo"]["lat"]; lon=f["geo"]["lon"]
    if not lat: print(fk,"no coord"); continue
    x,y=T.transform(lon,lat)
    daa=f["land"]["total_daa"] or 50
    half=max(160, min(650, math.sqrt(daa*1000/math.pi)*1.35))
    bbox=[x-half, y-half, x+half, y+half]
    wbbox=[x-half*3, y-half*3, x+half*3, y+half*3]
    # close aerial
    ac=esri(bbox)
    if ac: Image.open(io.BytesIO(ac)).convert("RGB").save(f"{MEDIA}/{fk}_aer.jpg","JPEG",quality=82,optimize=True)
    # boundary overlay (recolored, transparent)
    bnd=wms_boundary(bbox); ov=None
    if bnd:
        ov=recolor(bnd); ov.save(f"{MEDIA}/{fk}_bnd.png","PNG",optimize=True)
    # wide context
    aw=esri(wbbox)
    if aw: Image.open(io.BytesIO(aw)).convert("RGB").save(f"{MEDIA}/{fk}_wide.jpg","JPEG",quality=80,optimize=True)
    # 3D texture = aerial + boundary
    if ac:
        base=Image.open(io.BytesIO(ac)).convert("RGB")
        if ov is not None: base.paste(ov,(0,0),ov)
        base.save(f"{MEDIA}/{fk}_tex.jpg","JPEG",quality=82,optimize=True)
    # DEM heightmap
    d=dem(bbox,64)
    if d is not None:
        zmin=float(np.nanmin(d)); zmax=float(np.nanmax(d))
        d=np.where(np.isnan(d), zmin, d)
        terrain[fk]={"n":64,"span_m":round(2*half,1),"zmin":round(zmin,1),"zmax":round(zmax,1),
                     "z":[int(round(v)) for v in d.flatten()]}
    print(f"{fk} {f['place']:15} half={round(half)}m aer={bool(ac)} bnd={bool(bnd)} wide={bool(aw)} dem={d is not None} z={terrain.get(fk,{}).get('zmin')}-{terrain.get(fk,{}).get('zmax')}")
    time.sleep(0.15)

json.dump(terrain, open("data/terrain.json","w"), separators=(",",":"))
print(f"\nterrain.json farms: {len(terrain)}; size {os.path.getsize('data/terrain.json')/1024:.0f} KB")
