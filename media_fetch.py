# -*- coding: utf-8 -*-
"""media_fetch.py — download an aerial image (Esri World Imagery export) and the
top ad photos for each farm, compress them, and save under data/media/.
These get published as the artifact's own files so they load same-origin."""
import os, io, re, json, time
import requests
from PIL import Image

H = {"User-Agent": "Mozilla/5.0 Chrome/124 Safari/537.36", "Accept-Language": "nb-NO"}
MEDIA = "data/media"; os.makedirs(MEDIA, exist_ok=True)
farms = json.load(open("data/farms.json", encoding="utf-8"))
photos = json.load(open("data/photos.json", encoding="utf-8"))

def save_jpg(img, path, maxw, q):
    if img.mode != "RGB": img = img.convert("RGB")
    if img.width > maxw:
        img = img.resize((maxw, round(img.height*maxw/img.width)), Image.LANCZOS)
    img.save(path, "JPEG", quality=q, optimize=True)
    return os.path.getsize(path)

def fetch(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, headers=H, timeout=35)
            if r.status_code == 200 and r.content: return r.content
        except Exception: pass
        time.sleep(0.5*(i+1))
    return None

total = 0
for f in farms:
    fk = f["finnkode"]; lat = f["geo"]["lat"]; lon = f["geo"]["lon"]
    # aerial (Esri export), ~700 m span
    if lat and lon:
        d = 0.0055
        bbox = f"{lon-d},{lat-d*0.55},{lon+d},{lat+d*0.55}"
        u = (f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
             f"?bbox={bbox}&bboxSR=4326&imageSR=3857&size=680,520&format=jpg&f=image")
        c = fetch(u)
        if c:
            try:
                sz = save_jpg(Image.open(io.BytesIO(c)), f"{MEDIA}/{fk}_aerial.jpg", 680, 78); total += sz
            except Exception as e: print(fk, "aerial ERR", e)
    # up to 4 ad photos
    n = 0
    for url in photos.get(fk, [])[:6]:
        url = re.split(r"\s", url.strip())[0]
        m = re.match(r"(https://images\.finncdn\.no/\S+?\.(?:jpg|jpeg|png|webp))", url, re.I)
        if m: url = m.group(1)
        c = fetch(url)
        if not c: continue
        try:
            sz = save_jpg(Image.open(io.BytesIO(c)), f"{MEDIA}/{fk}_p{n}.jpg", 900, 72); total += sz; n += 1
        except Exception as e: print(fk, "photo ERR", e)
        if n >= 4: break
    print(f"{fk} {f['place']:16} aerial+{n} photos")

print(f"\nTotal media size: {total/1e6:.1f} MB in {MEDIA}")
