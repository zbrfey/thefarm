# -*- coding: utf-8 -*-
"""
build_climate.py — 6-year climatology per listing from Open-Meteo archive.

For each property with lat/lon (stage2b.csv):
  daylight_gt10h   days/year with photoperiod ≥ 10 h
  sunshine_gt10h   days/year with actual sunshine ≥ 10 h
  snow_days        days/year with snowfall > 0.1 cm
  snow_cover_days  days/year with snow on ground ≥ 1 cm (if API provides snow_depth)
  frost_days       days/year with Tmin < 0 °C
  mean_sunshine_h  mean sunshine hours per day

Averages over complete calendar years 2020–2025. Incremental: skips codes
already in data/climate.json unless --refresh.
"""
import argparse
import json
import os
import time

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "climate.json")
START, END = "2020-01-01", "2025-12-31"
YEARS = list(range(2020, 2026))
DAILY = "daylight_duration,sunshine_duration,snowfall_sum,temperature_2m_min"
URL = "https://archive-api.open-meteo.com/v1/archive"


def fetch(lat, lon, daily=DAILY):
    params = {
        "latitude": round(float(lat), 4),
        "longitude": round(float(lon), 4),
        "start_date": START,
        "end_date": END,
        "daily": daily,
        "timezone": "Europe/Oslo",
    }
    wait = 4
    for _ in range(10):
        r = requests.get(URL, params=params, timeout=90)
        if r.status_code == 429:
            print(f"  429, wait {wait}s", flush=True)
            time.sleep(wait)
            wait = min(90, wait * 2)
            continue
        if r.status_code == 400 and "snow_depth" in daily:
            return fetch(lat, lon, daily.replace(",snow_depth", ""))
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Open-Meteo 429 persisted")


def summarise(j):
    d = j["daily"]
    times = d["time"]
    dl = d.get("daylight_duration") or []
    su = d.get("sunshine_duration") or []
    sn = d.get("snowfall_sum") or []
    tn = d.get("temperature_2m_min") or []
    sd = d.get("snow_depth") or [None] * len(times)

    by_year = {y: {"dl": 0, "su": 0, "sn": 0, "sd": 0, "fr": 0, "sun_s": 0, "n": 0, "n_sd": 0}
               for y in YEARS}
    for i, t in enumerate(times):
        y = int(t[:4])
        if y not in by_year:
            continue
        b = by_year[y]
        b["n"] += 1
        if dl and dl[i] is not None and dl[i] >= 36000:
            b["dl"] += 1
        if su and su[i] is not None:
            b["sun_s"] += su[i]
            if su[i] >= 36000:
                b["su"] += 1
        if sn and sn[i] is not None and sn[i] > 0.1:
            b["sn"] += 1
        if tn and tn[i] is not None and tn[i] < 0:
            b["fr"] += 1
        if sd and sd[i] is not None:
            b["n_sd"] += 1
            if sd[i] >= 0.01:  # metres
                b["sd"] += 1

    complete = [y for y in YEARS if by_year[y]["n"] >= 360]
    if not complete:
        complete = [y for y in YEARS if by_year[y]["n"] > 300]
    n = max(1, len(complete))
    has_cover = any(by_year[y]["n_sd"] >= 300 for y in complete)

    def mean(key):
        return round(sum(by_year[y][key] for y in complete) / n, 1)

    rec = {
        "years": complete,
        "n_years": n,
        "daylight_gt10h": mean("dl"),
        "sunshine_gt10h": mean("su"),
        "snow_days": mean("sn"),
        "frost_days": mean("fr"),
        "mean_sunshine_h": round(
            sum(by_year[y]["sun_s"] for y in complete) / sum(by_year[y]["n"] for y in complete) / 3600, 2
        ) if complete else None,
        "source": "open-meteo-archive",
        "period": f"{complete[0]}–{complete[-1]}" if complete else None,
    }
    if has_cover:
        rec["snow_cover_days"] = mean("sd")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    gb = pd.read_csv(os.path.join(HERE, "data", "stage2b.csv"))
    gb["finnkode"] = gb["finnkode"].astype(str)
    climate = {}
    if os.path.exists(OUT) and not args.refresh:
        climate = json.load(open(OUT, encoding="utf-8"))

    todo = []
    for _, r in gb.iterrows():
        fk = str(r["finnkode"])
        if pd.isna(r.get("lat")):
            continue
        if fk in climate and not args.refresh:
            continue
        todo.append((fk, float(r["lat"]), float(r["lon"])))
    print(f"climate: {len(climate)} cached, {len(todo)} to fetch", flush=True)

    for i, (fk, lat, lon) in enumerate(todo, 1):
        try:
            j = fetch(lat, lon)
            rec = summarise(j)
            rec["lat"] = round(lat, 5)
            rec["lon"] = round(lon, 5)
            climate[fk] = rec
            print(f"[{i}/{len(todo)}] {fk} dl>{rec['daylight_gt10h']} sun>{rec['sunshine_gt10h']} "
                  f"snow={rec['snow_days']} frost={rec['frost_days']}"
                  + (f" cover={rec.get('snow_cover_days')}" if rec.get("snow_cover_days") is not None else ""),
                  flush=True)
        except Exception as e:
            print(f"[{i}/{len(todo)}] {fk} ERR {e}", flush=True)
        if i % 5 == 0 or i == len(todo):
            json.dump(climate, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        time.sleep(1.2)
    json.dump(climate, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote {OUT} ({len(climate)} listings)")


if __name__ == "__main__":
    main()
