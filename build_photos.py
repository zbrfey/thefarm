# -*- coding: utf-8 -*-
"""build_photos.py — scrape deduped ad photo URLs for the full pool -> photos.json"""
import os, requests, re, json, time
import pandas as pd
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36","Accept-Language":"nb-NO"}
codes=[str(c) for c in pd.read_csv("data/pool69.csv")["finnkode"]]
photos={}
if os.path.exists("data/photos.json"):
    photos=json.load(open("data/photos.json",encoding="utf-8"))
todo=[c for c in codes if c not in photos or not photos.get(c)]
print(f"photos cached {len(photos)}, todo {len(todo)}")
for code in todo:
    try:
        html=requests.get(f"https://www.finn.no/realestate/homes/ad.html?finnkode={code}",headers=H,timeout=25).text
        urls=re.findall(r'https://images\.finncdn\.no/dynamic/1280w/[^"\\\s]+', html)
        seen=set(); clean=[]
        for u in urls:
            u=re.split(r'\s', u.strip())[0]
            m=re.match(r'(https://images\.finncdn\.no/\S+?\.(?:jpg|jpeg|png|webp))', u, re.I)
            if m: u=m.group(1)
            tail=u.split('/1280w/',1)[1] if '/1280w/' in u else u
            if tail in seen: continue
            seen.add(tail); clean.append(u)
        photos[code]=clean[:6]
        print(code, len(clean))
    except Exception as e:
        print(code,"ERR",e); photos[code]=[]
    time.sleep(0.35)
json.dump(photos, open("data/photos.json","w",encoding="utf-8"), ensure_ascii=False)
print("done", sum(1 for v in photos.values() if v),"with photos")
