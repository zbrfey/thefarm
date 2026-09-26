# -*- coding: utf-8 -*-
"""build_dashboard.py — attach media file paths + DEM terrain to each farm and
inject into the template, producing dashboard.html."""
import json, os
farms=json.load(open("data/farms.json",encoding="utf-8"))
terrain=json.load(open("data/terrain.json",encoding="utf-8")) if os.path.exists("data/terrain.json") else {}
files=set(os.listdir("data/media"))
if not os.path.exists("media"):
    try:
        os.symlink("data/media", "media", target_is_directory=True)
    except Exception:
        pass
def p(name): return f"media/{name}" if name in files else None
for f in farms:
    fk=f["finnkode"]
    aer=p(f"{fk}_aer.jpg")
    f["media"]={
        "aer":aer, "tex":aer,   # composite (imagery+boundaries+highlight); also the 3D drape
        "photos":[f"media/{fk}_p{i}.jpg" for i in range(6) if f"{fk}_p{i}.jpg" in files],
    }
    f["terrain"]=terrain.get(fk)
tpl=open("dashboard_template.html",encoding="utf-8").read()
html=tpl.replace("__FARMS_JSON__",json.dumps(farms,ensure_ascii=False))
open("dashboard.html","w",encoding="utf-8").write(html)
print("wrote dashboard.html",round(len(html)/1024),"KB; terrain farms",len(terrain))
print("media sample:",farms[0]["media"])
