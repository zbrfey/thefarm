# -*- coding: utf-8 -*-
"""
final_rank.py — combine stage-1 signals + real NIBIO land data + stage-2b
geographic/cost enrichment into the final weighted ranking.

Components (weights sum 100):
  price 18, anchor_proximity 10, region 10, coast 10, forest 9, shading 9,
  dyrka 8, slope 7, total_size 6, creek 5, isolation 3, water_power 2,
  konsesjon 2, losore 1
coast & creek are still ad-text signals (unverified geometry) -> modest weight.
"""
import pandas as pd
from score_farms import band

W = {'price':15,'anchor':10,'region':9,'coast':9,'forest':11,'shading':8,
     'dyrka':10,'slope':6,'condition':9,'productive':5,'creek':4,'isolation':2,
     'water_power':1,'konsesjon':1}

def clamp(x, lo=0.0, hi=1.0): return max(lo, min(hi, x))
def forest_score(x): return (1.0 if x <= 250 else 0.9) if x >= 150 else round(x/150, 2)
def anchor_score(dmin):
    if dmin is None: return 0.3
    return round(clamp(1 - (dmin-60)/540), 2)          # 60km->1.0, 600km->0
def slope_score(s):
    if s is None: return 0.5
    return round(clamp(1 - (s-8)/27), 2)               # <=8%->1.0, 35%->0
def shading_score(h, winter):
    if h is None: return 0.5
    sc = clamp(1 - (h-5)/20)                            # <=5deg open->1.0, 25deg->0
    if winter is not None and h > winter: sc *= 0.7     # loses winter midday sun
    return round(sc, 2)

sc = pd.read_csv("data/farms_scored.csv", index_col=0); sc['finnkode']=sc['finnkode'].astype(str)
ni = pd.read_csv("data/land_all.csv"); ni['finnkode']=ni['finnkode'].astype(str)
ni = ni.rename(columns={'total_daa':'total_daa_ni'})
for _c in ['fulldyrka','overflatedyrka','beite','skog','annet','total_daa_ni']:
    ni[_c] = pd.to_numeric(ni[_c], errors='coerce')
gb = pd.read_csv("data/stage2b.csv"); gb['finnkode']=gb['finnkode'].astype(str)
import json as _json, os as _os
COND = _json.load(open("data/condition.json",encoding="utf-8")) if _os.path.exists("data/condition.json") else {}
d = sc.merge(ni, on='finnkode').merge(gb, on='finnkode', suffixes=('','_gb'))

rows=[]
for _, r in d.iterrows():
    v=lambda x: None if pd.isna(x) else float(x)
    fd,of,sk,be,an,tot = v(r['fulldyrka']),v(r['overflatedyrka']),v(r['skog']),v(r['beite']),v(r['annet']),v(r['total_daa_ni'])
    arable = ((fd or 0)+(of or 0)) if (fd is not None or of is not None) else None
    src = r.get('source','nibio')
    dmin = None if pd.isna(r['km_Storas']) else float(r['km_Storas'])
    cc = COND.get(r['finnkode'], {})
    if cc.get('tg_score') is not None:
        cond = float(cc['tg_score'])
    else:
        cond = min(1.0, cc.get('bath_score',0.5) + 0.08*cc.get('kitchen_new',False) + 0.08*cc.get('modern',False))
    if sk is None and arable is None:                 # split unknown -> bound by known total
        prod_sc = band(tot, 200, 350, 200) if tot is not None else 0.4
    else:
        prod_sc = band((fd or 0)+(of or 0)+(sk or 0)+(be or 0)+0.075*(an or 0), 200, 350, 200)
    forest_sc = 0.4 if sk is None else forest_score(sk)
    dyrka_sc = ((0.15 if (tot is not None and tot < 8) else 0.4) if arable is None
                else (band(arable, 60, 140, 90) if arable >= 5 else max(0.15, arable/60*0.5)))
    s = {
        'price': r['p_price'], 'region': r['p_region'], 'coast': r['p_coast'],
        'creek': r['p_creek'], 'isolation': r['p_isolation'], 'water_power': r['p_water_power'],
        'konsesjon': r['p_konsesjon'], 'losore': r['p_losore'],
        'productive': prod_sc, 'forest': forest_sc, 'dyrka': dyrka_sc,
        'anchor': anchor_score(dmin),
        'slope': slope_score(r['slope_pct']),
        'shading': shading_score(r['south_horizon_deg'], r.get('sun_winterish_deg')),
        'condition': cond,
    }
    total = round(sum(s[k]*W[k] for k in W), 1)
    flags=[]
    if arable is not None and arable < 5: flags.append('LOW-ARABLE')
    if src != 'nibio': flags.append('land-est')
    if pd.notna(r['slope_pct']) and r['slope_pct'] > 25: flags.append('STEEP')
    if pd.notna(r['south_horizon_deg']) and pd.notna(r.get('sun_winterish_deg')) and r['south_horizon_deg'] > r['sun_winterish_deg']: flags.append('WINTER-SHADE')
    if r.get('reno_needed'): flags.append('reno')
    if r.get('road_fee'): flags.append('road-fee')
    if cc.get('bath_neg'): flags.append('BAD-VÅTROM')
    if cc.get('bath_pos'): flags.append('NYTT-BAD')
    tg = cc.get('tg') or {}
    tg3 = tg.get('tg3')
    if tg3 is not None and tg3 >= 5: flags.append('TG3-HEAVY')
    elif tg.get('tg0') is not None and tg.get('tg3', 0) == 0 and tg.get('tg2', 0) <= 2: flags.append('TG-OK')
    rows.append({
        'score': total, 'finnkode': r['finnkode'], 'place': r['place'], 'fylke': r['fylke'],
        'pris_kr': int(r['pris_kr']), 'total_daa': (round(tot) if tot is not None else None),
        'arable': (round(arable,1) if arable is not None else None), 'forest': (round(sk,1) if sk is not None else None),
        'land_src': src,
        'km_anchor': round(dmin) if dmin else None,
        'slope_%': r['slope_pct'], 'S_horiz': r['south_horizon_deg'], 'elev': r['elev_m'],
        'coast': r['coast'], 'creek': r['creek'],
        'flags': ' '.join(flags), 'url': r['url'],
        'listing_kind': r['listing_kind'] if 'listing_kind' in r and pd.notna(r['listing_kind']) else 'farm',
    })
out = pd.DataFrame(rows).sort_values('score', ascending=False).reset_index(drop=True)
out.index += 1
out.to_csv("data/farms_ranked_final.csv", encoding="utf-8-sig")
cols=['score','place','fylke','pris_kr','total_daa','arable','forest','km_anchor','slope_%','S_horiz','coast','flags']
with pd.option_context('display.width',220,'display.max_colwidth',30):
    print(out[cols].to_string())
