# -*- coding: utf-8 -*-
"""
land_rescore.py — merge authoritative NIBIO AR5 land data (data/nibio_land.csv)
into the stage-1 scores for the top-20 shortlist and recompute the size / forest
/ dyrka components with real numbers. Other components (price, region, coast,
creek, isolation, water/power, konsesjon, losore) keep their stage-1 values.
Flags farms below the 5-daa arable (fulldyrka+overflatedyrka) floor.
"""
import pandas as pd
from score_farms import WEIGHTS, band

s = pd.read_csv("data/farms_scored.csv", index_col=0)
s['finnkode'] = s['finnkode'].astype(str)
n = pd.read_csv("data/nibio_land.csv"); n['finnkode'] = n['finnkode'].astype(str)
d = s.merge(n[['finnkode','fulldyrka','overflatedyrka','beite','skog','annet','total_daa']],
            on='finnkode', how='inner', suffixes=('','_ni'))

def forest_score(x):
    if x >= 150: return 1.0 if x <= 250 else 0.9   # lots of forest still a plus
    return round(x/150, 2)

rows = []
for _, r in d.iterrows():
    arable = r['fulldyrka'] + r['overflatedyrka']
    tot = r['total_daa_ni']
    p_size = band(tot, 250, 400, 250)
    p_forest = forest_score(r['skog'])
    p_dyrka = band(arable, 60, 140, 90) if arable >= 5 else max(0.15, arable/60*0.5)
    s_new = {k: r[f'p_{k}'] for k in WEIGHTS}
    s_new['total_size'] = p_size; s_new['forest'] = p_forest; s_new['dyrka'] = p_dyrka
    total = round(sum(s_new[k]*WEIGHTS[k] for k in WEIGHTS), 1)
    rows.append({
        'score': total, 'finnkode': r['finnkode'], 'place': r['place'], 'fylke': r['fylke'],
        'pris_kr': int(r['pris_kr']), 'total_daa': round(tot),
        'arable_daa': round(arable,1), 'forest_daa': round(r['skog'],1),
        'beite': round(r['beite'],1), 'annet': round(r['annet'],1),
        'arable_ok': 'OK' if arable >= 5 else 'LOW(<5)',
        'coast': r['coast'], 'creek': r['creek'], 'iso': r['iso'],
        'water_power': r['water_power'], 'konsesjon': r['konsesjon'], 'losore': r['losore'],
        'url': r['url'],
    })
out = pd.DataFrame(rows).sort_values('score', ascending=False).reset_index(drop=True)
out.index += 1
out.to_csv("data/farms_final.csv", encoding="utf-8-sig")
cols = ['score','place','fylke','pris_kr','total_daa','arable_daa','forest_daa','arable_ok','coast','creek','iso']
with pd.option_context('display.width', 200):
    print(out[cols].to_string())
