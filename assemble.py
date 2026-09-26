# -*- coding: utf-8 -*-
"""assemble.py — merge all sources into data/farms.json for the dashboard."""
import os, json, re, html
import pandas as pd

fr = pd.read_csv("data/farms_ranked_final.csv", index_col=0); fr['finnkode']=fr['finnkode'].astype(str)
ni = pd.read_csv("data/land_all.csv"); ni['finnkode']=ni['finnkode'].astype(str)
for _c in ['fulldyrka','overflatedyrka','beite','skog','annet','bebygd_vann','ikke_klass','total_daa']:
    if _c in ni.columns: ni[_c]=pd.to_numeric(ni[_c],errors='coerce')
gb = pd.read_csv("data/stage2b.csv"); gb['finnkode']=gb['finnkode'].astype(str)
rw_farm = pd.read_csv("data/farms_raw.csv")
rw_house = pd.read_csv("data/houses_raw.csv") if os.path.exists("data/houses_raw.csv") else pd.DataFrame()
rw = pd.concat([rw_farm, rw_house], ignore_index=True).drop_duplicates('finnkode')
rw['finnkode']=rw['finnkode'].astype(str)
photos = json.load(open("data/photos.json", encoding="utf-8"))
meta = json.load(open("data/meta.json", encoding="utf-8")) if os.path.exists("data/meta.json") else {}
cond = json.load(open("data/condition.json", encoding="utf-8")) if os.path.exists("data/condition.json") else {}
climate = json.load(open("data/climate.json", encoding="utf-8")) if os.path.exists("data/climate.json") else {}

def clean_urls(lst):
    out, seen = [], set()
    for u in lst or []:
        u = re.split(r'\s', u.strip())[0]          # drop srcset " 1280w,..."
        m = re.match(r'(https://images\.finncdn\.no/\S+?\.(?:jpg|jpeg|png|webp))', u, re.I)
        u = m.group(1) if m else u
        if u not in seen:
            seen.add(u); out.append(u)
    return out[:10]

def tidy_sog(u):
    if not u:
        return None
    u = html.unescape(str(u)).replace("&amp;", "&")
    if "meglervisning.no/salgsoppgave/bestill" in u.lower():
        u = re.sub(r"/bestill", "/hent", u, count=1, flags=re.I)
    return u

def ok_doc(u):
    if not u:
        return False
    ul = u.lower()
    if ul.endswith(".css") or ul.endswith(".js") or "/dist/" in ul:
        return False
    if "hem.no/" in ul and not re.search(r"hem\.no/[0-9a-f-]{20,}", ul):
        return False
    if "meglervisning.no/salgsoppgave/hent" in ul and "estateid=" not in ul:
        return False
    return True

def docs_of(fk):
    raw = (cond.get(fk) or {}).get("docs") or []
    out, seen = [], set()
    for d in raw:
        u = tidy_sog(d.get("url"))
        if not ok_doc(u):
            continue
        k = re.sub(r"[?#].*$", "", u.lower())
        if k in seen:
            continue
        seen.add(k)
        out.append({"url": u, "kind": d.get("kind") or "salgsoppgave"})
        if len(out) >= 6:
            break
    return out

ni_i = ni.set_index('finnkode'); gb_i = gb.set_index('finnkode'); rw_i = rw.set_index('finnkode')
farms = []
for rank, r in fr.iterrows():
    fk = r['finnkode']; n = ni_i.loc[fk]; g = gb_i.loc[fk]; w = rw_i.loc[fk] if fk in rw_i.index else None
    def gv(x, d=None):
        try:
            v = g[x]; return None if pd.isna(v) else (v.item() if hasattr(v,'item') else v)
        except Exception: return d
    def wv(x, d=""):
        if w is None: return d
        v = w[x]; return d if pd.isna(v) else v
    def nl(x):
        try:
            v = n[x]; return None if pd.isna(v) else float(v)
        except Exception: return None
    def ni_int(k):
        try:
            v = n[k]
            if pd.isna(v): return None
            return int(float(v))
        except Exception:
            return None
    knr, gnr, bnr = ni_int("knr"), ni_int("gnr"), ni_int("bnr")
    docs = docs_of(fk)
    sog = tidy_sog((cond.get(fk) or {}).get("salgsoppgave") or (meta.get(fk, {}) or {}).get("salgsoppgave"))
    if not ok_doc(sog):
        sog = docs[0]["url"] if docs else None
    farms.append({
        "rank": int(rank), "score": float(r['score']), "finnkode": fk, "url": r['url'],
        "title": str(wv('title')), "address": str(wv('address')), "place": r['place'], "fylke": r['fylke'],
        "byggeaar": str(wv('byggeaar')), "bruksareal": str(wv('bruksareal')), "soverom": str(wv('soverom')),
        "boligtype": str(wv('boligtype')),
        "listing_kind": (r['listing_kind'] if 'listing_kind' in r and pd.notna(r['listing_kind']) else
                         ("house" if str(wv('boligtype')).lower().startswith("enebolig") else "farm")),
        "prisantydning": str(wv('prisantydning')), "totalpris": str(wv('totalpris')),
        "pris_kr": int(r['pris_kr']),
        "description": str(wv('description'))[:1500],
        "land": {
            "fulldyrka": nl('fulldyrka'), "overflatedyrka": nl('overflatedyrka'),
            "beite": nl('beite'), "skog": nl('skog'), "annet": nl('annet'),
            "bebygd_vann": nl('bebygd_vann'), "ikke_klass": nl('ikke_klass'),
            "total_daa": nl('total_daa'), "source": (None if 'source' not in n or pd.isna(n['source']) else n['source']),
        },
        "geo": {
            "lat": gv('lat'), "lon": gv('lon'), "elev_m": gv('elev_m'),
            "slope_pct": gv('slope_pct'), "south_horizon_deg": gv('south_horizon_deg'),
            "sun_equinox_deg": gv('sun_equinox_deg'), "sun_winterish_deg": gv('sun_winterish_deg'),
        },
        "anchors": {
            "storas_km": gv('km_Storas'), "storas_h": gv('h_Storas'),
        },
        "costs": {
            "reno_needed": bool(gv('reno_needed')), "road_fee": bool(gv('road_fee')),
            "kommunale_avg": gv('kommunale_avg'), "eiendomsskatt": gv('eiendomsskatt'),
        },
        "climate": climate.get(fk) or None,
        "coast": r['coast'], "creek": r['creek'], "flags": r['flags'] if pd.notna(r['flags']) else "",
        "matrikkel": None if knr is None else {"knr": knr, "gnr": gnr or 0, "bnr": bnr or 0},
        "gardskart": None if knr is None else f"https://gardskart.nibio.no/grunneiendom/{knr}/{gnr or 0}/{bnr or 0}/0",
        "photos": clean_urls(photos.get(fk, [])),
        "sales": (meta.get(fk, {}) or {}).get("sales", []),
        "salgsoppgave": sog,
        "docs": docs,
        "condition": cond.get(fk, {}),
    })

json.dump(farms, open("data/farms.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"wrote data/farms.json with {len(farms)} farms")
print("sample photo:", farms[0]['photos'][0] if farms[0]['photos'] else None)
print("first farm keys:", list(farms[0].keys()))
