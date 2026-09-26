# -*- coding: utf-8 -*-
"""
scrape_farms.py — collect all active Gaardsbruk/Smaabruk (farm/smallholding)
listings from finn.no (property_type=11) and extract the fields that matter
for evaluating a farm: price, areas, plot size, building year, and crucially
the MATRIKKEL (kommunenr/gnr/bnr) which lets us look up NIBIO Gaardskart land
data and Kartverket boundaries/coordinates downstream.

Outputs:
  data/farms_raw.csv        one row per farm (structured fields)
  data/ads/<finnkode>.txt   full cleaned page text (for description / later NLP)

Usage:
  python scrape_farms.py                # scrape everything (all counties)
  python scrape_farms.py --max-pages 3  # limit pages (testing)
  python scrape_farms.py --codes 123,456  # only these finnkodes (testing)
"""
import argparse
import csv
import os
import re
import sys
import time
import random
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup, Comment

BASE = "https://www.finn.no/realestate/homes"
SEARCH = BASE + "/search.html?property_type=11"
AD = BASE + "/ad.html?finnkode={}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "nb-NO,nb;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml",
}

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ADS_DIR = os.path.join(DATA_DIR, "ads")
CSV_PATH = os.path.join(DATA_DIR, "farms_raw.csv")

# Labels whose value sits on the immediately-following text line.
PAIR_LABELS = {
    "Prisantydning": "prisantydning",
    "Totalpris": "totalpris",
    "Omkostninger": "omkostninger",
    "Fellesgjeld": "fellesgjeld",
    "Formuesverdi": "formuesverdi",
    "Boligtype": "boligtype",
    "Eieform": "eieform",
    "Soverom": "soverom",
    "Primærrom": "primaerrom",
    "Internt bruksareal": "internt_bruksareal",
    "Bruksareal": "bruksareal",
    "Bruttoareal": "bruttoareal",
    "Byggeår": "byggeaar",
    "Tomteareal": "tomteareal",
    "Energimerking": "energimerking",
    "Antall rom": "antall_rom",
    "Etasje": "etasje",
}

CSV_FIELDS = [
    "finnkode", "url", "title", "address", "postcode", "place",
    "prisantydning", "totalpris", "omkostninger", "fellesgjeld", "formuesverdi",
    "boligtype", "eieform", "primaerrom", "internt_bruksareal", "bruksareal",
    "bruttoareal", "soverom", "antall_rom", "byggeaar", "etasje",
    "tomteareal", "tomteareal_m2", "tomteareal_dekar", "energimerking",
    "kommunenr", "gnr", "bnr", "n_images", "description", "scraped_at",
]


def safe_get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                r.encoding = "utf-8"
                return r.text
            if r.status_code == 404:
                return None
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa
            last = str(e)
        time.sleep(2 ** i + random.uniform(0, 1))
    print(f"  ! failed {url}: {last}")
    return None


def clean_soup(html):
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)  # strip react comment artifacts
    soup = BeautifulSoup(html, "lxml")
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup


def collect_finnkodes(max_pages=40):
    codes = []
    seen = set()
    page = 1
    empty_streak = 0
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
        print(f"  page {page}: {len(found)} links, {len(new)} new (total {len(codes)})")
        if not new:
            empty_streak += 1
            if empty_streak >= 2:
                break
        else:
            empty_streak = 0
        page += 1
        time.sleep(random.uniform(0.6, 1.4))
    return codes


def _num(s):
    if not s:
        return None
    m = re.findall(r"[\d\s.,]+", s)
    if not m:
        return None
    digits = re.sub(r"[^\d]", "", m[0])
    return int(digits) if digits else None


def parse_ad(code):
    html = safe_get(AD.format(code))
    if not html:
        return None
    soup = clean_soup(html)
    text = soup.get_text("\n", strip=True)
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    rec = {k: "" for k in CSV_FIELDS}
    rec["finnkode"] = code
    rec["url"] = AD.format(code)
    rec["scraped_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # label -> next-line value
    for i, line in enumerate(lines):
        for label, key in PAIR_LABELS.items():
            if line == label and not rec.get(key) and i + 1 < len(lines):
                val = lines[i + 1]
                if val not in PAIR_LABELS:  # guard against label-with-empty-value
                    rec[key] = val
                break

    # title
    h1 = soup.find("h1")
    if h1:
        rec["title"] = h1.get_text(" ", strip=True)

    # address / postcode / place: first line with a Norwegian 4-digit postcode
    for line in lines[:60]:
        m = re.search(r"(.*?),?\s*(\d{4})\s+([A-Za-zÆØÅæøå .\-]+)$", line)
        if m and len(line) < 80:
            rec["address"] = line
            rec["postcode"] = m.group(2)
            rec["place"] = m.group(3).strip()
            break

    # matrikkel
    hm = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    mk = re.search(r"Kommunenr:\s*(\d+)", hm)
    if mk:
        rec["kommunenr"] = mk.group(1)
    mg = re.search(r"Gårdsnr:\s*(\d+)", hm)
    if mg:
        rec["gnr"] = mg.group(1)
    mb = re.search(r"Bruksnr:\s*(\d+)", hm)
    if mb:
        rec["bnr"] = mb.group(1)

    # tomteareal parse -> m2 and dekar
    ta = rec.get("tomteareal", "")
    tam2 = _num(ta)
    if tam2:
        rec["tomteareal_m2"] = tam2
        rec["tomteareal_dekar"] = round(tam2 / 1000.0, 1)

    # image count
    rec["n_images"] = len(soup.select('img[src*="finncdn"], img[src*="images.finncdn"]'))

    # description: text under "Om eiendommen"/"Om boligen"/"Beskrivelse" until a stop heading
    STOPS = {"Fasiliteter", "Beliggenhet", "Prisantydning", "Nabolag",
             "Matrikkelinformasjon", "Om eier", "Vis mer", "Energimerking"}
    desc = []
    capturing = False
    for line in lines:
        if line in ("Om eiendommen", "Om boligen", "Beskrivelse", "Boligen"):
            capturing = True
            continue
        if capturing:
            if line in STOPS or (len(desc) > 4 and line in PAIR_LABELS):
                break
            desc.append(line)
    rec["description"] = " ".join(desc)[:6000]

    # persist full page text for later analysis
    os.makedirs(ADS_DIR, exist_ok=True)
    with open(os.path.join(ADS_DIR, f"{code}.txt"), "w", encoding="utf-8") as f:
        f.write(text)

    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=40)
    ap.add_argument("--codes", type=str, default="")
    args = ap.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)

    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    else:
        print("Collecting finnkodes from search pages...")
        codes = collect_finnkodes(args.max_pages)
    codes = list(dict.fromkeys(codes))  # de-dupe, preserve order
    print(f"Total farms to fetch: {len(codes)}\n")

    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for n, code in enumerate(codes, 1):
            print(f"[{n}/{len(codes)}] {code}")
            try:
                rec = parse_ad(code)
            except Exception as e:  # noqa
                print(f"  ! parse error {code}: {e}")
                rec = None
            if rec:
                w.writerow(rec)
                f.flush()
                print(f"    {rec['title'][:60]!r} | {rec['prisantydning']} | "
                      f"{rec['tomteareal_dekar']} daa | matr {rec['kommunenr']}-{rec['gnr']}/{rec['bnr']}")
            time.sleep(random.uniform(0.5, 1.1))

    print(f"\nDone. Wrote {CSV_PATH}")


if __name__ == "__main__":
    main()
