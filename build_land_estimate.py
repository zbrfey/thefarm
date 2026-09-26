# -*- coding: utf-8 -*-
"""build_land_estimate.py — text-estimate fulldyrka/skog for farms without NIBIO
data (the pool tail). Total daa comes from the scraped tomteareal. These rows are
marked source='text' so the dashboard/score can flag them; contenders get
NIBIO-verified via the browser afterwards. -> data/land_est.csv"""
import re, os
import pandas as pd
ADS="data/ads"
need=pd.read_csv("data/need_nibio.csv")
raw=pd.read_csv("data/farms_raw.csv").drop_duplicates("finnkode")
raw["finnkode"]=raw["finnkode"].astype(str)
tot=raw.set_index("finnkode")["tomteareal_dekar"]
DAA=r'(\d[\d\s.,]*)\s*(?:daa|dekar|mål|maal)\b'
def num(s):
    n=re.sub(r"[^\d]","",s.split(",")[0].split(".")[0]); return int(n) if n else None
def find_daa(t, kws):
    best=None
    for kw in kws:
        for m in re.finditer(kw, t):
            for dm in re.finditer(DAA, t[max(0,m.start()-35):m.end()+35]):
                v=num(dm.group(1))
                if v and 0<v<100000: best=v if best is None else max(best,v)
    return best
rows=[]
for _,r in need.iterrows():
    fk=str(r["finnkode"]); p=f"{ADS}/{fk}.txt"
    t=open(p,encoding="utf-8").read().lower() if os.path.exists(p) else ""
    dy=find_daa(t,["fulldyrka","dyrka mark","dyrket mark","dyrka jord","jordbruksareal"])
    sk=find_daa(t,["produktiv skog","skogareal"," skog"])
    total=tot.get(fk); total=float(total) if pd.notna(total) else None
    rows.append({"finnkode":fk,"knr":r["knr"],"gnr":r["gnr"],"bnr":r["bnr"],"place":r["place"],
        "fulldyrka":dy if dy else "","overflatedyrka":"","beite":"","skog":sk if sk else "",
        "annet":"","bebygd_vann":"","ikke_klass":"","total_daa":round(total,1) if total else "","source":"text"})
pd.DataFrame(rows).to_csv("data/land_est.csv",index=False)
print("estimated",len(rows),"| with dyrka:",sum(1 for x in rows if x['fulldyrka']!=''),"| with skog:",sum(1 for x in rows if x['skog']!=''))
