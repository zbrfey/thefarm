# -*- coding: utf-8 -*-
"""
scrape_houses.py — collect Finn enebolig (property_type=1) with tomt ≥ 5 mål
(5000 m²). Skips finnkodes already in farms_raw.csv / houses_raw.csv.
Budget is applied later in score_farms (2.0M, 2.5M in Møre).

Output: data/houses_raw.csv
"""
import argparse
import csv
import os
import re
import time
import random

from scrape_farms import (
    BASE, HEADERS, DATA_DIR, CSV_FIELDS, safe_get, parse_ad,
)

SEARCH = BASE + "/search.html?property_type=1&plot_area_from=5000"
HOUSE_CSV = os.path.join(DATA_DIR, "houses_raw.csv")
FARM_CSV = os.path.join(DATA_DIR, "farms_raw.csv")
HOUSE_FIELDS = CSV_FIELDS + ["listing_kind"]
MIN_M2 = 5000


def existing_codes():
    seen = set()
    for path in (FARM_CSV, HOUSE_CSV):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                c = (row.get("finnkode") or "").strip()
                if c:
                    seen.add(c)
    return seen


def collect_finnkodes(max_pages=20):
    codes, seen = [], set()
    page, empty_streak = 1, 0
    while page <= max_pages:
        url = f"{SEARCH}&page={page}"
        html = safe_get(url)
        if not html:
            break
        found = re.findall(r"finnkode=(\d+)", html)
        new = [c for c in found if c not in seen]
        for c in new:
            seen.add(c)
            codes.append(c)
        treff = re.search(r">(\d+)</span>\s*<!-- -->treff", html)
        print(f"  page {page}: {len(found)} links, {len(new)} new (total {len(codes)})"
              + (f"  treff={treff.group(1)}" if treff else ""))
        if not new:
            empty_streak += 1
            if empty_streak >= 2:
                break
        else:
            empty_streak = 0
        page += 1
        time.sleep(random.uniform(0.6, 1.4))
    return codes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--codes", type=str, default="")
    args = ap.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    have = existing_codes()
    print(f"Already have {len(have)} finnkodes in farms/houses CSVs")

    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    else:
        print("Collecting enebolig finnkodes (tomt >= 5000 m2)...")
        codes = collect_finnkodes(args.max_pages)
    codes = list(dict.fromkeys(codes))
    todo = [c for c in codes if c not in have]
    print(f"Search unique {len(codes)}; to fetch {len(todo)} new\n")

    write_header = not os.path.exists(HOUSE_CSV) or os.path.getsize(HOUSE_CSV) == 0
    n_ok = 0
    with open(HOUSE_CSV, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=HOUSE_FIELDS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for n, code in enumerate(todo, 1):
            print(f"[{n}/{len(todo)}] {code}")
            try:
                rec = parse_ad(code)
            except Exception as e:  # noqa
                print(f"  ! parse error {code}: {e}")
                rec = None
            if rec:
                m2 = rec.get("tomteareal_m2") or 0
                try:
                    m2 = int(m2)
                except Exception:
                    m2 = 0
                if m2 < MIN_M2:
                    print(f"    skip tomt {m2} m2 < {MIN_M2}")
                else:
                    rec["listing_kind"] = "house"
                    w.writerow(rec)
                    f.flush()
                    n_ok += 1
                    print(f"    {rec['title'][:60]!r} | {rec['prisantydning']} | "
                          f"{rec['tomteareal_dekar']} daa | matr {rec['kommunenr']}-{rec['gnr']}/{rec['bnr']}")
            time.sleep(random.uniform(0.5, 1.1))
    print(f"\nDone. Appended {n_ok} houses -> {HOUSE_CSV}")


if __name__ == "__main__":
    main()
