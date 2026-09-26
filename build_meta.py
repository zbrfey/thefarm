# -*- coding: utf-8 -*-
"""build_meta.py — per farm: prior sale history (finn ownershiphistory table)
and the best salgsoppgave/prospekt link from the ad page."""
import os, re, json, time
import requests
import pandas as pd
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36","Accept-Language":"nb-NO"}
codes=[str(c) for c in pd.read_csv("data/pool69.csv")["finnkode"]]

def num(s):
    d=re.sub(r"[^\d]","",s); return int(d) if d else None

def sales(code):
    r=requests.get(f"https://www.finn.no/realestate/ownershiphistory.html?finnkode={code}",headers=H,timeout=25)
    h=r.text
    out=[]
    # table rows: <td>dd.mm.yyyy</td><td ...>price ,−</td>
    for m in re.finditer(r'<td[^>]*>\s*(\d{2}\.\d{2}\.\d{4})\s*</td>\s*<td[^>]*>(.*?)</td>', h, re.S):
        date=m.group(1); praw=re.sub(r"<[^>]+>","",m.group(2)).strip()
        p=num(praw) if re.search(r"\d", praw) else None
        if p and p>10000: out.append({"date":date,"price":p})
    # de-dup, newest first
    seen=set(); dd=[]
    for s in out:
        k=(s["date"],s["price"])
        if k not in seen: seen.add(k); dd.append(s)
    dd.sort(key=lambda s:s["date"].split(".")[::-1], reverse=True)
    return dd

def salgsoppgave(code):
    h=requests.get(f"https://www.finn.no/realestate/homes/ad.html?finnkode={code}",headers=H,timeout=25).text
    cands=re.findall(r'https?://[^"\'\\\s]*(?:bestill-salgsoppgave|digitalsalgsoppgave|salgsoppgave|prospekt)[^"\'\\\s]*', h, re.I)
    cands=[c.rstrip("\\/") for c in cands if "finn.no" not in c]
    if cands: return sorted(set(cands), key=len, reverse=True)[0]
    pdfs=re.findall(r'https?://[^"\'\\\s]+\.pdf[^"\'\\\s]*', h)
    return pdfs[0] if pdfs else None

meta={}
if os.path.exists("data/meta.json"):
    meta=json.load(open("data/meta.json",encoding="utf-8"))
todo=[c for c in codes if c not in meta]
print(f"meta cached {len(meta)}, todo {len(todo)}")
for c in todo:
    try:
        s=sales(c); sg=salgsoppgave(c)
        meta[c]={"sales":s,"salgsoppgave":sg}
        print(c,"sales",len(s), s[0] if s else "-", "| sog:", (sg[:55] if sg else None))
    except Exception as e:
        print(c,"ERR",e); meta[c]={"sales":[],"salgsoppgave":None}
    time.sleep(0.4)
json.dump(meta, open("data/meta.json","w",encoding="utf-8"), ensure_ascii=False)
print("done")
