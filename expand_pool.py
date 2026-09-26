# -*- coding: utf-8 -*-
"""
expand_pool.py — rebuild the geo/land pool from every scored listing that has
matrikkel, then text-estimate land for anything not already in NIBIO.
Writes data/pool69.csv (legacy name used by stage2b/photos/etc),
data/need_nibio.csv, data/land_est.csv, data/land_all.csv.
"""
import os, re
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ADS = os.path.join(DATA, "ads")
DAA = r'(\d[\d\s.,]*)\s*(?:daa|dekar|mål|maal)\b'


def num(s):
    n = re.sub(r"[^\d]", "", str(s).split(",")[0].split(".")[0])
    return int(n) if n else None


def find_daa(t, kws):
    best = None
    for kw in kws:
        for m in re.finditer(kw, t):
            for dm in re.finditer(DAA, t[max(0, m.start() - 35):m.end() + 35]):
                v = num(dm.group(1))
                if v and 0 < v < 100000:
                    best = v if best is None else max(best, v)
    return best


def load_raw():
    parts = []
    for name, default_kind in (("farms_raw.csv", "farm"), ("houses_raw.csv", "house")):
        p = os.path.join(DATA, name)
        if not os.path.exists(p):
            continue
        d = pd.read_csv(p)
        if "listing_kind" not in d.columns:
            d["listing_kind"] = default_kind
        parts.append(d)
    raw = pd.concat(parts, ignore_index=True).drop_duplicates("finnkode")
    raw["finnkode"] = raw["finnkode"].astype(str)
    return raw


def main():
    sc = pd.read_csv(os.path.join(DATA, "farms_scored.csv"))
    sc["finnkode"] = sc["finnkode"].astype(str)
    raw = load_raw()
    m = sc.merge(raw[["finnkode", "kommunenr", "gnr", "bnr", "place", "tomteareal_dekar", "listing_kind"]],
                 on="finnkode", how="left", suffixes=("", "_raw"))
    m["knr"] = pd.to_numeric(m["kommunenr"], errors="coerce")
    m["gnr"] = pd.to_numeric(m["gnr"], errors="coerce")
    m["bnr"] = pd.to_numeric(m["bnr"], errors="coerce")
    pool = m[m["knr"].notna() & m["gnr"].notna() & m["bnr"].notna()].copy()
    pool = pool.reset_index(drop=True)
    pool.insert(0, "rank", range(1, len(pool) + 1))
    out_cols = ["rank", "finnkode", "knr", "gnr", "bnr", "place", "fylke"]
    if "listing_kind" in pool.columns:
        out_cols.append("listing_kind")
    pool[out_cols].to_csv(os.path.join(DATA, "pool69.csv"), index=False)
    kinds = pool["listing_kind"].value_counts().to_dict() if "listing_kind" in pool.columns else {}
    print(f"pool {len(pool)} {kinds}")

    ni_p = os.path.join(DATA, "nibio_land.csv")
    ni_codes = set()
    if os.path.exists(ni_p):
        ni = pd.read_csv(ni_p)
        ni_codes = set(ni["finnkode"].astype(str))
    need = pool[~pool["finnkode"].isin(ni_codes)].copy()
    need[["finnkode", "knr", "gnr", "bnr", "place", "fylke"]].to_csv(
        os.path.join(DATA, "need_nibio.csv"), index=False)
    print(f"need_nibio {len(need)} (no NIBIO yet)")

    tot = raw.set_index("finnkode")["tomteareal_dekar"]
    rows = []
    for _, r in need.iterrows():
        fk = str(r["finnkode"])
        p = os.path.join(ADS, f"{fk}.txt")
        t = open(p, encoding="utf-8").read().lower() if os.path.exists(p) else ""
        dy = find_daa(t, ["fulldyrka", "dyrka mark", "dyrket mark", "dyrka jord", "jordbruksareal"])
        sk = find_daa(t, ["produktiv skog", "skogareal", " skog"])
        total = tot.get(fk)
        total = float(total) if pd.notna(total) else None
        rows.append({
            "finnkode": fk, "knr": r["knr"], "gnr": r["gnr"], "bnr": r["bnr"], "place": r["place"],
            "fulldyrka": dy if dy else "", "overflatedyrka": "", "beite": "",
            "skog": sk if sk else "", "annet": "", "bebygd_vann": "", "ikke_klass": "",
            "total_daa": round(total, 1) if total else "", "source": "text",
        })
    pd.DataFrame(rows).to_csv(os.path.join(DATA, "land_est.csv"), index=False)
    print("land_est", len(rows),
          "| dyrka", sum(1 for x in rows if x["fulldyrka"] != ""),
          "| skog", sum(1 for x in rows if x["skog"] != ""))

    # combine — same as build_land_combined.py
    cols = ["finnkode", "knr", "gnr", "bnr", "place", "fulldyrka", "overflatedyrka", "beite",
            "skog", "annet", "bebygd_vann", "ikke_klass", "total_daa", "source"]
    frames = []
    if os.path.exists(ni_p):
        ni = pd.read_csv(ni_p)
        ni["source"] = "nibio"
        for c in cols:
            if c not in ni.columns:
                ni[c] = None
        frames.append(ni[cols])
    es = pd.read_csv(os.path.join(DATA, "land_est.csv"))
    for c in cols:
        if c not in es.columns:
            es[c] = None
    frames.append(es[cols])
    both = pd.concat(frames, ignore_index=True)
    both["finnkode"] = both["finnkode"].astype(str)
    both = both.drop_duplicates("finnkode", keep="first")
    both.to_csv(os.path.join(DATA, "land_all.csv"), index=False)
    print("land_all", len(both),
          "| nibio", (both.source == "nibio").sum(),
          "| text", (both.source == "text").sum())


if __name__ == "__main__":
    main()
