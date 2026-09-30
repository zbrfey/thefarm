# -*- coding: utf-8 -*-
"""
score_farms.py — Stage 1 triage ranking of scraped farms against the buyer's
profile. Hard-filters on budget, then scores each surviving farm on price,
region, coast, land composition, water, isolation, and bonuses. Land/forest/
dyrka and coast/creek signals are TEXT-MINED from the ad body here; they get
replaced with authoritative NIBIO/Kartverket/OSM values in stage 2 for the
shortlist. Unknown-from-text factors score neutral (0.5) so a farm isn't
buried just because its ad was terse.

Buyer profile (2026-09, budget raised 2026-09-28):
  budget total <= 5.0M NOK (best < 1.5M); min 5 daa dyrka (verified stage 2)
  ideal: Moere og Romsdal > Troendelag, coastal, 250-400 daa total,
         150-250 forest, ~100 dyrka, creek on property, isolated, water+power,
         short driveway, not mountain-shaded. Konsesjon/boplikt = cheaper = plus.
         Loesoere/tractor included = bonus.
"""
import os, re, json
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ADS = os.path.join(HERE, "data", "ads")
BUDGET = 5_000_000

FYLKE = {
    '15':'Møre og Romsdal','50':'Trøndelag','16':'Trøndelag','17':'Trøndelag',
    '18':'Nordland','11':'Rogaland','46':'Vestland','12':'Vestland','14':'Vestland',
    '33':'Buskerud','06':'Buskerud','34':'Innlandet','04':'Innlandet','05':'Innlandet',
    '39':'Vestfold','07':'Vestfold','40':'Telemark','08':'Telemark','42':'Agder',
    '09':'Agder','10':'Agder','31':'Østfold','01':'Østfold','32':'Akershus','02':'Akershus',
    '03':'Oslo','55':'Troms','19':'Troms','56':'Finnmark','20':'Finnmark','30':'Akershus',
}
COASTAL_FYLKE = {'15','50','18','55','56','46','11','42','39','40','31','03'}  # have coastline

DAA = r'(\d[\d\s.,]*)\s*(?:daa|dekar|mål|maal)\b'

def num(s):
    if pd.isna(s): return None
    n = re.sub(r'[^\d]', '', str(s)); return int(n) if n else None

def load_text(code):
    p = os.path.join(ADS, f"{code}.txt")
    if os.path.exists(p):
        return open(p, encoding="utf-8").read().lower()
    return ""

def find_daa(text, keywords):
    """Largest daa figure appearing within ~30 chars of any keyword."""
    best = None
    for kw in keywords:
        for m in re.finditer(kw, text):
            a, b = max(0, m.start()-35), m.end()+35
            for dm in re.finditer(DAA, text[a:b]):
                v = num(dm.group(1))
                if v and 0 < v < 100000:
                    best = v if best is None else max(best, v)
    return best

def has(text, terms):
    return any(t in text for t in terms)

def band(x, lo, hi, soft):
    """1.0 inside [lo,hi], linear decay over `soft` on each side, floor 0."""
    if x is None: return None
    if lo <= x <= hi: return 1.0
    d = (lo - x) if x < lo else (x - hi)
    return max(0.0, 1 - d / soft)

def score_row(r, text):
    s, why = {}, {}

    # --- price: <=1.5M full, decay to 0 at budget cap (5.0M) ---
    eff = r['eff']
    cap = BUDGET
    s['price'] = 1.0 if eff <= 1_500_000 else max(0.0, 1 - (eff-1_500_000)/(cap-1_500_000))
    why['price'] = f"{int(eff):,} kr"

    # --- region ---
    f = r['fylke']
    s['region'] = {'15':1.0,'50':0.8}.get(f, 0.45 if f in COASTAL_FYLKE else 0.30)
    why['region'] = r['fylkenavn']

    # --- coast / sea (text signal) ---
    strong_sea = has(text, ['strandlinje','sjøtomt','egen strand','naust','sjøhus','ved sjøen','sjøen i'])
    some_sea   = has(text, ['sjø','kyst','havet','fjord','båt'])
    s['coast'] = 1.0 if strong_sea else (0.6 if some_sea else (0.5 if f in COASTAL_FYLKE else 0.15))
    why['coast'] = 'strandlinje/naust' if strong_sea else ('sjø nevnt' if some_sea else '-')

    # --- land total size (reliable from scrape) ---
    tot = r['daa']
    s['total_size'] = band(tot, 250, 400, 250) if pd.notna(tot) else 0.5
    why['total_size'] = f"{tot:.0f} daa" if pd.notna(tot) else "?"

    # --- forest (text) ---
    forest = find_daa(text, ['produktiv skog','skogareal',' skog'])
    s['forest'] = band(forest, 150, 250, 200) if forest else 0.5
    why['forest'] = f"{forest} daa" if forest else "?"

    # --- dyrka (text; hard min handled as flag) ---
    dyrka = find_daa(text, ['fulldyrka','dyrka mark','dyrket mark','jordbruksareal','dyrka jord'])
    s['dyrka'] = band(dyrka, 60, 140, 90) if dyrka else 0.5
    why['dyrka'] = f"{dyrka} daa" if dyrka else "?"

    # --- creek / river on property ---
    creek = has(text, ['bekk','elv gjennom','elv renner','vassdrag','elvestrekning','bekkefar'])
    river = has(text, ['elv','å ','tjern','vann på'])
    s['creek'] = 1.0 if creek else (0.5 if river else 0.15)
    why['creek'] = 'bekk/vassdrag' if creek else ('elv/vann' if river else '-')

    # --- isolation ---
    iso = has(text, ['usjenert','landlig','fritt og','avsides','skjermet','ingen nære nabo',
                     'enden av veien','ugenert','naturskjønn'])
    s['isolation'] = 1.0 if iso else 0.4
    why['isolation'] = 'ja' if iso else '-'

    # --- water + power ---
    water = has(text, ['innlagt vann','offentlig vann','egen brønn','borehull','vannverk'])
    power = has(text, ['strøm','elektrisitet','nettleie','innlagt strøm'])
    s['water_power'] = 1.0 if (water and power) else (0.6 if (water or power) else 0.3)
    why['water_power'] = ('vann+strøm' if water and power else ('vann' if water else ('strøm' if power else '-')))

    # --- konsesjon / boplikt (cheaper => plus) ---
    kons = has(text, ['konsesjon','boplikt','driveplikt','odel'])
    s['konsesjon'] = 1.0 if kons else 0.4
    why['konsesjon'] = 'ja' if kons else '-'

    # --- loesoere / tractor bonus ---
    los = has(text, ['løsøre','traktor','redskap','driftsutstyr','maskiner følger','inventar følger'])
    s['losore'] = 1.0 if los else 0.3
    why['losore'] = 'ja' if los else '-'

    return s, why, dict(forest=forest, dyrka=dyrka, tot=(None if pd.isna(tot) else tot))

WEIGHTS = {  # sum 100
    'price':22, 'region':15, 'coast':15, 'total_size':10, 'forest':9,
    'dyrka':8, 'creek':8, 'isolation':5, 'water_power':3, 'konsesjon':3, 'losore':2,
}

def load_raw():
    parts = []
    farm_p = os.path.join(HERE, "data", "farms_raw.csv")
    house_p = os.path.join(HERE, "data", "houses_raw.csv")
    if os.path.exists(farm_p):
        f = pd.read_csv(farm_p)
        if "listing_kind" not in f.columns:
            f["listing_kind"] = "farm"
        parts.append(f)
    if os.path.exists(house_p):
        h = pd.read_csv(house_p)
        if "listing_kind" not in h.columns:
            h["listing_kind"] = "house"
        parts.append(h)
    if not parts:
        raise SystemExit("no farms_raw.csv / houses_raw.csv")
    d = pd.concat(parts, ignore_index=True)
    d["listing_kind"] = d["listing_kind"].fillna("farm")
    return d


def main():
    d = load_raw()
    d['pris'] = d['prisantydning'].map(num); d['tot'] = d['totalpris'].map(num)
    d['eff'] = d['tot'].fillna((d['pris']*1.025).round())
    d['daa'] = pd.to_numeric(d['tomteareal_dekar'], errors='coerce')
    knr = d['kommunenr'].astype('Int64').astype(str).str.replace('<NA>', '', regex=False)
    d['fylke'] = knr.str.zfill(4).str[:2]
    d['fylkenavn'] = d['fylke'].map(FYLKE).fillna(d['fylke'])

    d = d.drop_duplicates('finnkode').copy()
    d = d[d['eff'].notna() & (d['eff'] <= BUDGET)].copy()

    rows = []
    for _, r in d.iterrows():
        text = load_text(r['finnkode'])
        s, why, mined = score_row(r, text)
        total = round(sum(s[k]*WEIGHTS[k] for k in WEIGHTS), 1)
        rows.append({
            'score': total, 'finnkode': r['finnkode'], 'title': r['title'],
            'place': r['place'], 'fylke': r['fylkenavn'],
            'pris_kr': int(r['eff']), 'total_daa': mined['tot'],
            'forest_daa': mined['forest'], 'dyrka_daa': mined['dyrka'],
            'coast': why['coast'], 'creek': why['creek'], 'iso': why['isolation'],
            'water_power': why['water_power'], 'konsesjon': why['konsesjon'],
            'losore': why['losore'], 'url': r['url'],
            'listing_kind': r.get('listing_kind', 'farm') if pd.notna(r.get('listing_kind', 'farm')) else 'farm',
            **{f'p_{k}': round(s[k],2) for k in WEIGHTS},
        })
    out = pd.DataFrame(rows).sort_values('score', ascending=False).reset_index(drop=True)
    out.index += 1
    out.to_csv(os.path.join(HERE, "data", "farms_scored.csv"), encoding="utf-8-sig")

    cols = ['score','title','place','fylke','pris_kr','total_daa','forest_daa','dyrka_daa','coast','creek','iso']
    with pd.option_context('display.max_colwidth', 42, 'display.width', 200):
        print(out.head(25)[cols].to_string())
    kinds = out['listing_kind'].value_counts().to_dict() if 'listing_kind' in out.columns else {}
    print(f"\nScored {len(out)} listings under budget {kinds}. Full table: data/farms_scored.csv")

if __name__ == "__main__":
    main()
