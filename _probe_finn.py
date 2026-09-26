# -*- coding: utf-8 -*-
import ssl, urllib.request, re, json, os
ctx = ssl._create_unverified_context()
H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36",
    "Accept-Language": "nb-NO",
}

def fetch(url):
    req = urllib.request.Request(url, headers=H)
    return urllib.request.urlopen(req, timeout=30, context=ctx).read()

for code in ["475527762", "474654074", "385752750", "349756784"]:
    u = f"https://www.finn.no/realestate/homes/ad.html?finnkode={code}"
    try:
        raw = fetch(u)
        h = raw.decode("utf-8", "replace")
    except Exception as e:
        print(code, "ERR", e)
        continue
    print("====", code, "len", len(h))
    tl = h.lower()
    print(" tilstandsgrad", tl.count("tilstandsgrad"), "tg2", h.count("TG2"), "tg3", h.count("TG3"))
    docs = re.findall(r"https?://[^\"'\\\s]+(?:pdf|salgsoppgave|prospekt|tilstand)[^\"'\\\s]*", h, re.I)
    print(" doc urls", len(set(docs)))
    for d in sorted(set(docs))[:15]:
        print("  ", d[:160])
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
    print(" NEXT_DATA", bool(m), "len", len(m.group(1)) if m else 0)
    if m:
        try:
            data = json.loads(m.group(1))
            s = json.dumps(data, ensure_ascii=False)
            for kw in ["tilstands", "condition", "tg3", "salgsoppgave", "documents", "attachments"]:
                print("   json kw", kw, s.lower().count(kw.lower()))
            Path = "tmp"
            os.makedirs("data/_probe", exist_ok=True)
            open(f"data/_probe/{code}_next.json", "w", encoding="utf-8").write(s[:200000])
        except Exception as e:
            print(" json fail", e)
    i = tl.find("tilstandsgrad")
    if i >= 0:
        print(" snippet", re.sub(r"\s+", " ", h[max(0, i - 60) : i + 350])[:350])
    print()
