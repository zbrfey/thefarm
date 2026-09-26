# -*- coding: utf-8 -*-
"""build_land_combined.py — merge NIBIO-verified land (nibio_land.csv) with the
text estimates (land_est.csv) into one table, NIBIO taking precedence.
-> data/land_all.csv  (source column: 'nibio' | 'text')"""
import pandas as pd
ni=pd.read_csv("data/nibio_land.csv"); ni["source"]="nibio"
es=pd.read_csv("data/land_est.csv")
cols=["finnkode","knr","gnr","bnr","place","fulldyrka","overflatedyrka","beite","skog","annet","bebygd_vann","ikke_klass","total_daa","source"]
for c in cols:
    if c not in ni.columns: ni[c]=None
    if c not in es.columns: es[c]=None
both=pd.concat([ni[cols],es[cols]],ignore_index=True)
both["finnkode"]=both["finnkode"].astype(str)
both=both.drop_duplicates("finnkode",keep="first")  # nibio first -> wins
both.to_csv("data/land_all.csv",index=False)
print("land_all:",len(both),"| nibio:",(both.source=='nibio').sum(),"| text:",(both.source=='text').sum())
