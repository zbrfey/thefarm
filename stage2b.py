# -*- coding: utf-8 -*-
"""
stage2b.py — geographic + cost enrichment for the shortlist.

Per farm (keyed off matrikkel knr/gnr/bnr):
  - coordinates: Geonorge adresser representasjonspunkt (on-property), Nominatim fallback
  - elevation (m) at the farm point (Kartverket hoydedata dtm1)
  - slope %: gradient from a 100 m cross around the point
  - south-horizon angle (deg): max terrain elevation angle toward S/SE/SW out to 2.5 km
        -> "mountain shading". Compared to solar-noon sun altitude (equinox & ~winter).
  - driving distance + time to Snausvegen 623, 7334 Storås (OSRM)
  - cost signals mined from ad text: renovation need, private-road fee, kommunale avg, eiendomsskatt

Output: data/stage2b.csv
"""
import os, re, json, time, math
import requests
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ADS = os.path.join(HERE, "data", "ads")
H = {"User-Agent": "thefarm-research/1.0 (husebyja@gmail.com)"}

# Snausvegen 623, 7334 Storås (Orkland). Geonorge representasjonspunkt.
ANCHORS = {"Storas": (63.05328925246673, 9.44455188639208)}

def get(url, params=None, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=H, timeout=25)
            if r.status_code == 200:
                return r
        except Exception:
            pass
        time.sleep(0.5 * (i + 1))
    return None

def coords(knr, gnr, bnr, place):
    r = get("https://ws.geonorge.no/adresser/v1/sok",
            {"kommunenummer": int(knr), "gardsnummer": int(gnr), "bruksnummer": int(bnr), "treffPerSide": 5})
    if r:
        ads = r.json().get("adresser") or []
        if ads:
            pts = [a["representasjonspunkt"] for a in ads if a.get("representasjonspunkt")]
            if pts:
                return (sum(p["lat"] for p in pts)/len(pts), sum(p["lon"] for p in pts)/len(pts), "geonorge")
    # fallback: matrikkel WFS point via nominatim on place
    r = get("https://nominatim.openstreetmap.org/search", {"q": f"{place}, Norway", "format": "json", "limit": 1})
    time.sleep(1.0)
    if r and r.json():
        j = r.json()[0]
        return (float(j["lat"]), float(j["lon"]), "nominatim(place)")
    return (None, None, "none")

def elev(lat, lon):
    r = get("https://ws.geonorge.no/hoydedata/v1/punkt",
            {"koordsys": 4258, "nord": round(lat, 6), "ost": round(lon, 6), "geojson": "false"})
    time.sleep(0.05)
    if r:
        p = r.json().get("punkter") or []
        if p and p[0].get("z") is not None:
            return float(p[0]["z"])
    return None

def offset(lat, lon, north_m, east_m):
    dlat = north_m / 111200.0
    dlon = east_m / (111320.0 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon

def slope_pct(lat, lon, z0):
    d = 100.0
    zN = elev(*offset(lat, lon, d, 0)); zS = elev(*offset(lat, lon, -d, 0))
    zE = elev(*offset(lat, lon, 0, d)); zW = elev(*offset(lat, lon, 0, -d))
    if None in (zN, zS, zE, zW): return None
    gx = (zE - zW) / (2*d); gy = (zN - zS) / (2*d)
    return round(math.hypot(gx, gy) * 100, 1)

def south_horizon(lat, lon, z0):
    """Max terrain elevation angle toward S/SE/SW out to 2.5 km."""
    best = 0.0; where = "-"
    for az in (135, 160, 180, 200, 225):
        for dist in (400, 900, 1600, 2500):
            n = -dist * math.cos(math.radians(az)); e = dist * math.sin(math.radians(az))
            z = elev(*offset(lat, lon, n, e))
            if z is None: continue
            ang = math.degrees(math.atan2(z - z0, dist))
            if ang > best:
                best = ang; where = f"{az}° @ {dist}m"
    return round(best, 1), where

def drive(lat, lon, alat, alon):
    r = get(f"http://router.project-osrm.org/route/v1/driving/{lon},{lat};{alon},{alat}",
            {"overview": "false"})
    if r:
        rt = r.json().get("routes") or []
        if rt:
            return round(rt[0]["distance"]/1000, 1), round(rt[0]["duration"]/3600, 1)
    return None, None

def cost_signals(code):
    p = os.path.join(ADS, f"{code}.txt")
    t = open(p, encoding="utf-8").read().lower() if os.path.exists(p) else ""
    reno = any(k in t for k in ["oppussingsobjekt", "oppussing", "modernisering", "renovering",
                                "totalrenovering", "rehabilitering", "må påregnes", "oppgradering",
                                "behov for", "tas med i betraktning", "modernisere"])
    road = any(k in t for k in ["veiavgift", "veavgift", "veilag", "brøyting", "brøyteavgift",
                                "privat vei", "privat veg", "bomavgift", "grunneierlag"])
    def money(labels):
        for lab in labels:
            m = re.search(lab + r"[^0-9]{0,40}?([\d\s]{4,})\s*(?:kr|,-)", t)
            if m:
                n = re.sub(r"\D", "", m.group(1))
                if n: return int(n)
        return None
    komm = money(["kommunale avgifter", "kommunale avg", "off. avgifter"])
    eskatt = money(["eiendomsskatt"])
    return reno, road, komm, eskatt

def main():
    top = pd.read_csv(os.path.join(HERE, "data", "pool69.csv"))
    top['finnkode'] = top['finnkode'].astype(str)
    out_path = os.path.join(HERE, "data", "stage2b.csv")
    done = set()
    prev = None
    if os.path.exists(out_path) and os.path.getsize(out_path):
        prev = pd.read_csv(out_path)
        prev['finnkode'] = prev['finnkode'].astype(str)
        done = set(prev['finnkode'])
        print(f"stage2b resume: {len(done)} already enriched")
    rows = [] if prev is None else prev.to_dict("records")
    todo = top[~top['finnkode'].isin(done)]
    print(f"stage2b todo: {len(todo)}")
    for _, r in todo.iterrows():
        knr, gnr, bnr = r['knr'], r['gnr'], r['bnr']
        lat, lon, src = coords(knr, gnr, bnr, r['place'])
        rec = {"rank": r['rank'], "finnkode": r['finnkode'], "place": r['place'],
               "fylke": r['fylke'], "lat": lat, "lon": lon, "coord_src": src}
        if lat:
            z0 = elev(lat, lon); rec["elev_m"] = round(z0) if z0 is not None else None
            if z0 is not None:
                rec["slope_pct"] = slope_pct(lat, lon, z0)
                ang, where = south_horizon(lat, lon, z0)
                rec["south_horizon_deg"] = ang; rec["horizon_at"] = where
                rec["sun_equinox_deg"] = round(90 - lat, 1)
                rec["sun_winterish_deg"] = round(90 - lat - 13, 1)  # ~early Nov / early Feb noon
            for name, (alat, alon) in ANCHORS.items():
                dkm, dh = drive(lat, lon, alat, alon)
                rec[f"km_{name}"] = dkm; rec[f"h_{name}"] = dh
        reno, road, komm, eskatt = cost_signals(r['finnkode'])
        rec.update(reno_needed=reno, road_fee=road, kommunale_avg=komm, eiendomsskatt=eskatt)
        rows.append(rec)
        print(f"#{r['rank']:>2} {r['place'][:16]:16} z={rec.get('elev_m')} slope={rec.get('slope_pct')}% "
              f"Shoriz={rec.get('south_horizon_deg')}° Storas={rec.get('km_Storas')}km "
              f"{rec.get('h_Storas')}t reno={reno} src={src}")
        out = pd.DataFrame(rows)
        out.to_csv(os.path.join(HERE, "data", "stage2b.csv"), index=False, encoding="utf-8-sig")
    print("\nSaved data/stage2b.csv")

if __name__ == "__main__":
    main()
