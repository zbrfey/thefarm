# -*- coding: utf-8 -*-
import ssl, urllib.request, re, html, json, os
ctx = ssl._create_unverified_context()
H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36",
    "Accept-Language": "nb-NO",
}

def fetch(url):
    req = urllib.request.Request(url, headers=H)
    return urllib.request.urlopen(req, timeout=30, context=ctx).read().decode("utf-8", "replace")

code = "475527762"
h = fetch(f"https://www.finn.no/realestate/homes/ad.html?finnkode={code}")
# unescape unicode
h2 = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), h)
h2 = html.unescape(h2)
os.makedirs("data/_probe", exist_ok=True)
open("data/_probe/sandstad.html", "w", encoding="utf-8").write(h2)
i = h2.lower().find("utdrag av tilstandsgrader")
print("idx", i)
print(h2[i:i+2500] if i>=0 else "no utdrag")
print("---- links ----")
for m in re.finditer(r'href="(https?://[^"]+)"', h2):
    u=m.group(1)
    if re.search(r'salgsoppgave|prospekt|tilstand|pdf|dokument|hem\.no|webmegler|meglervisning', u, re.I):
        print(u[:180])
print("---- json blobs ----")
for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', h2, re.S):
    print("ld+json", m.group(1)[:400])
print("apollo/state", "apollo" in h2.lower(), "__DATA" in h2, "finnAd" in h2)
# document filenames in page
for m in re.finditer(r'.{0,40}tilstandsrapport.{0,80}', h2, re.I):
    s=re.sub(r"\s+"," ", m.group(0))
    if "pdf" in s.lower() or "http" in s.lower() or "dokument" in s.lower():
        print("tr ctx", s[:160])
