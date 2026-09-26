# -*- coding: utf-8 -*-
"""build_condition.py — locate salgsoppgave + parse TG0–TG3 from each Finn ad.

Norwegian listings often paste a tilstandsrapport excerpt in the ad body:
  TG0: n / TG1: n / TG2: n / TG3: n / TGIU: n
  plus bygningsdeler med TG2/TG3.

We do not download the full broker PDF for every listing (often 10–20 MB).
The Finn excerpt is the same overview as in the prospectus. Direct document
URLs are kept so the dashboard can open the actual salgsoppgave.

If the ad has no excerpt, we try a small attached PDF (finncdn) only.
Writes data/condition.json.
"""
import io, os, re, json, time, html
import requests
import pandas as pd

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36",
    "Accept-Language": "nb-NO",
}

PDF_MAX = 8_000_000
PDF_PAGES = 40

def codes_from_pool():
    for p in ("data/farms_ranked_final.csv", "data/pool69.csv"):
        if os.path.exists(p):
            return [str(c) for c in pd.read_csv(p)["finnkode"]]
    return []

def decode_html(h):
    h = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), h)
    h = html.unescape(h)
    h = re.sub(r"<br\s*/?>", "\n", h, flags=re.I)
    h = re.sub(r"</p>", "\n", h, flags=re.I)
    h = re.sub(r"</li>", "\n", h, flags=re.I)
    h = re.sub(r"</div>", "\n", h, flags=re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    h = h.replace("\xa0", " ").replace("\u2011", "-").replace("\u2013", "-")
    return re.sub(r"[ \t]+", " ", h)

def norm_tg(t):
    t = t.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    t = re.sub(r"TG\s*[-]?\s*I\s*U\b", "TGIU", t, flags=re.I)
    t = re.sub(r"TG\s*[-]?\s*([0123])\b", r"TG\1", t, flags=re.I)
    return t

def parse_tg_counts(t):
    t = norm_tg(t)
    flat = re.sub(r"[\n\r]+", " ", t)
    m = re.search(
        r"TG0\s*[:/]\s*(\d+)\s+TG1\s*[:/]\s*(\d+)\s+TG2\s*[:/]\s*(\d+)\s+TG3\s*[:/]\s*(\d+)",
        flat,
        re.I,
    )
    if not m:
        m = re.search(
            r"TG0\s*[:/]\s*(\d+).*?TG1\s*[:/]\s*(\d+).*?TG2\s*[:/]\s*(\d+).*?TG3\s*[:/]\s*(\d+)",
            t,
            re.I | re.S,
        )
    if not m:
        return None
    iu = 0
    miu = re.search(r"TGIU\s*[:/]\s*(\d+)", flat[m.end() : m.end() + 80] if m.end() < len(flat) else t, re.I)
    if not miu:
        miu = re.search(r"TGIU\s*[:/]\s*(\d+)", t[m.end() : m.end() + 120], re.I)
    if miu:
        iu = int(miu.group(1))
    return {
        "tg0": int(m.group(1)),
        "tg1": int(m.group(2)),
        "tg2": int(m.group(3)),
        "tg3": int(m.group(4)),
        "iu": iu,
    }

def _chunk(t, start_pat, end_pats):
    m = re.search(start_pat, t, re.I)
    if not m:
        return ""
    rest = t[m.end() :]
    ends = [len(rest)]
    for p in end_pats:
        em = re.search(p, rest, re.I)
        if em:
            ends.append(em.start())
    return rest[: min(ends)].strip()

SKIP_PART = re.compile(r"avvik som kan|store eller alvorlige|vesentlige avvik|ingen avvik|mindre eller moderate|^utvendig$|^innvendig$", re.I)

def parse_parts(t, grade):
    t = norm_tg(t)
    g = str(grade)
    chunk = _chunk(
        t,
        rf"Bygningsdeler med\s+TG{g}\s*:?",
        [r"Bygningsdeler med\s+TG", r"Takstmanns", r"Utdrag av tilstandsgrader", r"TGIU\s*:"],
    )
    if not chunk:
        chunk = _chunk(
            t,
            rf"(?:gjevne|gitt|vurdert med|har f.{{0,2}}tt)\s+tilstandsgrad\s*{g}\s*:?",
            [r"tilstandsgrad\s+[123]", r"Bygningsdeler med", r"Takstmanns"],
        )
    if not chunk or len(chunk) < 8:
        chunk = _chunk(
            t,
            rf"Forhold som har f.{{0,3}}tt\s+TG{g}\b",
            [rf"Forhold som har f.{{0,3}}tt\s+TG", r"TGIU", r"TG IU"],
        )
    if not chunk or len(chunk) < 8:
        return []
    chunk = chunk[:5000]
    items, cur = [], None
    for raw in chunk.split("\n"):
        line = raw.strip(" -•\t")
        line = line.lstrip("-–—")
        if not line or len(line) < 3:
            continue
        if re.match(r"^(TG[0-3IU]|TGIU)\b", line, re.I):
            break
        if line.endswith(":") and len(line) < 80 and not line.lower().startswith("symptom"):
            if cur:
                items.append(cur)
            cur = {"part": line[:-1].strip(), "notes": []}
        elif re.search(r"\s>\s", line) and len(line) < 140:
            if cur:
                items.append(cur)
                cur = None
            left, right = line.split(">", 1)
            items.append({"part": f"{left.strip()} · {right.strip()}"[:90], "notes": []})
        elif re.search(r"\s[-–—]\s", line):
            part, note = re.split(r"\s[-–—]\s", line, 1)
            if cur:
                items.append(cur)
                cur = None
            items.append({"part": part.strip()[:90], "notes": [note.strip()[:180]]})
        elif cur is not None:
            cur["notes"].append(line[:180])
        elif len(line) < 110:
            items.append({"part": line[:90], "notes": []})
        if len(items) >= 14:
            break
    if cur and len(items) < 14:
        items.append(cur)
    out = []
    seen = set()
    for it in items:
        note = "; ".join(it["notes"][:3])
        label = re.sub(r"\s+", " ", it["part"]).strip(" :-")
        if SKIP_PART.search(label):
            continue
        if len(label) < 3:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((label + (": " + note if note else ""))[:240])
    return out

def tg_score(c):
    if not c or c.get("tg0") is None:
        return None
    ins = c["tg0"] + c["tg1"] + c["tg2"] + c["tg3"]
    if ins <= 0:
        return None
    raw = (c["tg0"] * 1.0 + c["tg1"] * 0.82 + c["tg2"] * 0.42 + c["tg3"] * 0.08) / ins
    if c["tg3"] >= 6:
        raw = min(raw, 0.28)
    elif c["tg3"] >= 3:
        raw = min(raw, 0.45)
    if c["tg3"] == 0 and c["tg2"] <= 2:
        raw = max(raw, 0.78)
    return round(raw, 2)

BATH = r"(vå?trom|baderom|\bbad\b|dusjrom|bad/)"

def bath_signals(tl):
    notes, score = [], 0.5

    def tg_has_bath(level):
        for m in re.finditer(rf"tilstandsgrad\s*{level}\b", tl):
            seg = tl[m.end() : m.end() + 700].split("tilstandsgrad")[0]
            if re.search(r"(våtrom|baderom|bad/|\bbad\b|dusj|sanitær|membran)", seg):
                return True
        return False

    bathTG3 = tg_has_bath(3)
    bathTG2 = tg_has_bath(2)
    neg = bool(
        re.search(
            rf"{BATH}[^\.]{{0,60}}(må (oppgraderes|renoveres|utbedres|påreg)|utettheter|vannskade|fukt|skade|ikkje? godkjent|ikke godkjent|utett|lekkasje|slitt|eldre standard)",
            tl,
        )
    )
    pos = bool(re.search(rf"(nytt|nyare|nyere|moderne|renovert|oppgradert|rehabilitert|flislagt|påkosta|påkostet|totalrenovert|oppussa)\s+{BATH}", tl)) \
        or bool(re.search(rf"{BATH}[^\.]{{0,25}}(fra|frå|i)\s*20(1[5-9]|2\d)", tl)) \
        or bool(re.search(rf"{BATH}[^\.]{{0,30}}(er renovert|er oppgradert|nyoppussa|nyoppusset|ny membran|nytt fra 20)", tl))
    if bathTG3:
        score = 0.12
        notes.append("våtrom TG3 (alvorleg avvik)")
    elif neg:
        score = 0.2
        notes.append("bad/våtrom med behov/skade")
    elif bathTG2:
        score = 0.4
        notes.append("våtrom TG2 (avvik)")
    if pos and score < 0.6:
        notes.append("men nemner nyare bad")
    elif pos:
        score = 0.9
        notes.append("nyare/moderne bad")
    kitchen_new = bool(re.search(r"(nytt|nyare|nyere|moderne|renovert|oppgradert)\s+kjøkken", tl))
    modern = bool(re.search(r"(totalrenovert|totaloppussa|gjennomgripande oppussing|nyoppussa|nyoppusset|modernisert i 20|oppgradert i 20|påkosta bustad)", tl))
    if kitchen_new:
        notes.append("nyare kjøkken")
    if modern:
        notes.append("modernisert nyleg")
    return score, notes, bool(neg or bathTG3), bool(pos and score >= 0.6), kitchen_new, modern

SKIP_DOC = re.compile(
    r"verdivurdering|salgsgaranti|utm_medium=profil|/selge/|arealplaner\.no|10tips|kommuneplan",
    re.I,
)

def tidy_url(u):
    u = html.unescape(u).replace("&amp;", "&").rstrip("\\/")
    if "meglervisning.no/salgsoppgave/bestill" in u.lower():
        u = re.sub(r"/bestill", "/hent", u, count=1, flags=re.I)
    return u

def kind_of(u):
    ul = u.lower()
    if "tilstand" in ul:
        return "tilstandsrapport"
    if "meglervisning.no/salgsoppgave/hent" in ul or ul.endswith(".pdf") or ".pdf?" in ul:
        return "pdf"
    if "bestill" in ul:
        return "bestill"
    if "hem.no/" in ul or "se_komplett_salgsoppgave" in ul or "openSalesStatement" in u:
        return "salgsoppgave"
    return "salgsoppgave"

def score_url(u):
    ul = u.lower()
    if SKIP_DOC.search(u):
        return -100
    s = 0
    if "meglervisning.no/salgsoppgave/hent" in ul:
        s += 90
    if ul.endswith(".pdf") or ".pdf?" in ul:
        s += 55
    if "images.finncdn.no" in ul and ".pdf" in ul:
        s += 15
    if re.search(r"hem\.no/[0-9a-f-]{20,}", ul):
        s += 48
    if "file-proxy.rfcdn.io" in ul:
        s += 45
    if "digital~salgsoppgave" in ul or "digital-salgsoppgave" in ul or "salgsoppgave.pdf" in ul:
        s += 50
    if "tilstandsrapport" in ul:
        s += 18
    if "openSalesStatement" in u or "openSalesStatement" in ul:
        s += 22
    if "webmegler.no" in ul and "salgsoppgave" in ul:
        s += 18
    if "/hent" in ul:
        s += 20
    if "bestill" in ul:
        s -= 12
    if "registrer" in ul:
        s -= 40
    return s

def extract_docs(raw, extra=None):
    raw = html.unescape(raw)
    found = re.findall(
        r"https?://[^\"'\\\s]+(?:pdf|salgsoppgave|prospekt|tilstand|hem\.no/|file-proxy)[^\"'\\\s]*",
        raw,
        re.I,
    )
    found.extend(re.findall(r'href="(https?://[^"]+)"', raw))
    if extra:
        found.append(extra)
    out, seen = [], set()
    for u in found:
        u = tidy_url(u)
        if "finn.no" in u and "finncdn" not in u:
            continue
        if SKIP_DOC.search(u) or u in seen:
            continue
        if u.endswith(".css") or u.endswith(".js") or "/dist/" in u:
            continue
        if "hem.no" in u.lower() and not re.search(r"hem\.no/[0-9a-f-]{20,}", u, re.I):
            continue
        if "meglervisning.no/salgsoppgave/hent" in u.lower() and "estateid=" not in u.lower():
            continue
        if score_url(u) < 0:
            continue
        if not re.search(
            r"salgsoppgave|prospekt|tilstand|\.pdf|hem\.no/[0-9a-f]|webmegler|meglervisning|aktiv\.no/prospekt|nordvik|/hent|file-proxy|rfcdn",
            u,
            re.I,
        ):
            continue
        seen.add(u)
        out.append({"url": u, "kind": kind_of(u), "score": score_url(u)})
    out.sort(key=lambda d: d["score"], reverse=True)
    return [{"url": d["url"], "kind": d["kind"]} for d in out[:8]]

def pdf_text(url):
    ul = url.lower()
    if "meglervisning.no" in ul or "digital~salgsoppgave" in ul or "digital-salgsoppgave" in ul:
        return ""
    try:
        r = requests.get(url, headers=H, timeout=25, stream=True)
        cl = r.headers.get("Content-Length")
        if cl and int(cl) > PDF_MAX:
            r.close()
            return ""
        buf = b""
        for chunk in r.iter_content(65536):
            buf += chunk
            if len(buf) > PDF_MAX:
                break
        r.close()
        if not buf.startswith(b"%PDF"):
            return ""
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(buf))
        pages = []
        for p in reader.pages[:PDF_PAGES]:
            pages.append(p.extract_text() or "")
        return "\n".join(pages)
    except Exception:
        return ""

BROKER_HOSTS = (
    "aktiv.no", "eiendomsmegler1.no", "dnbeiendom.no", "nordvikbolig.no",
    "webmegler.no", "hem.no", "garanti.no", "partners.no",
)

def follow_broker(url):
    if not url:
        return "", []
    ul = url.lower()
    if ".pdf" in ul or "meglervisning.no/salgsoppgave/hent" in ul or "bestill" in ul:
        return "", []
    if not any(h in ul for h in BROKER_HOSTS):
        return "", []
    if "hem.no" in ul:
        return "", []
    try:
        r = requests.get(url, headers=H, timeout=20)
        extra = extract_docs(r.text)
        return decode_html(r.text), extra
    except Exception:
        return "", []

def condition(code, meta_sog=None):
    raw = requests.get(
        f"https://www.finn.no/realestate/homes/ad.html?finnkode={code}",
        headers=H,
        timeout=25,
    ).text
    t = decode_html(raw)
    tl = t.lower()
    bath_score, notes, bath_neg, bath_pos, kitchen_new, modern = bath_signals(tl)
    tg = parse_tg_counts(t)
    source = "ad-excerpt" if tg else None
    blob = t
    docs = extract_docs(raw, extra=meta_sog)
    # Follow the HTML prospectus to get the real PDF + TG2/TG3 lists.
    for d in list(docs)[:3]:
        html_t, extra = follow_broker(d["url"])
        if extra:
            seen = {x["url"] for x in docs}
            for e in extra:
                if e["url"] not in seen:
                    docs.append(e)
                    seen.add(e["url"])
            docs.sort(key=lambda x: score_url(x["url"]), reverse=True)
            docs = [{"url": x["url"], "kind": x.get("kind") or kind_of(x["url"])} for x in docs[:8]]
        if html_t:
            blob = blob + "\n" + html_t
            if not tg:
                tg = parse_tg_counts(html_t)
                if tg:
                    source = "salgsoppgave"
            time.sleep(0.15)
            break
    tg2 = parse_parts(blob, 2)
    tg3 = parse_parts(blob, 3)
    tgiu = parse_parts(blob, "IU")
    if not tg and not tg2 and not tg3:
        for d in docs:
            if d["kind"] != "pdf" and ".pdf" not in d["url"].lower():
                continue
            pt = pdf_text(d["url"])
            if not pt:
                continue
            tg = parse_tg_counts(pt)
            if tg or parse_parts(pt, 3):
                blob = blob + "\n" + pt
                if tg:
                    source = "pdf"
                tg2 = parse_parts(blob, 2)
                tg3 = parse_parts(blob, 3)
                tgiu = parse_parts(blob, "IU")
                break
    if tg is None and (tg2 or tg3):
        tg = {
            "tg0": None, "tg1": None,
            "tg2": len(tg2), "tg3": len(tg3),
            "iu": len(tgiu), "partial": True,
        }
        source = source or "ad-text"
    if tg3 and not bath_neg:
        blob_l = " ".join(tg3).lower()
        if re.search(r"våtrom|baderom|\bbad\b|membran", blob_l):
            bath_neg = True
            if bath_score > 0.2:
                bath_score = 0.2
                notes.insert(0, "våtrom nemnt under TG3")
    tsc = tg_score(tg) if tg and tg.get("tg0") is not None else None
    if tsc is not None:
        cond_score = tsc
    else:
        cond_score = min(1.0, bath_score + 0.08 * kitchen_new + 0.08 * modern)
    sog = docs[0]["url"] if docs else None
    has_report = ("tilstandsrapport" in tl) or ("tilstandsgrad" in tl) or bool(tg)
    if source is None:
        source = "ad-text" if has_report else "none"
    return {
        "bath_score": round(bath_score, 2),
        "bath_neg": bath_neg,
        "bath_pos": bath_pos,
        "kitchen_new": kitchen_new,
        "modern": modern,
        "has_report": has_report,
        "notes": notes,
        "tg": tg,
        "tg_score": tsc,
        "cond_score": round(cond_score, 2),
        "tg2": tg2,
        "tg3": tg3,
        "tgiu": tgiu,
        "salgsoppgave": sog,
        "docs": docs,
        "source": source,
    }

EMPTY = {
    "bath_score": 0.5, "bath_neg": False, "bath_pos": False,
    "kitchen_new": False, "modern": False, "has_report": False,
    "notes": [], "tg": None, "tg_score": None, "cond_score": 0.5,
    "tg2": [], "tg3": [], "tgiu": [], "salgsoppgave": None, "docs": [],
    "source": "error",
}

def main():
    codes = codes_from_pool()
    meta = {}
    if os.path.exists("data/meta.json"):
        meta = json.load(open("data/meta.json", encoding="utf-8"))
    out = {}
    print(f"condition refresh {len(codes)} listings")
    for i, c in enumerate(codes, 1):
        try:
            extra = (meta.get(c) or {}).get("salgsoppgave")
            out[c] = condition(c, extra)
            tg = out[c]["tg"]
            tg_s = f"TG3={tg['tg3']}" if tg else "no-tg"
            print(f"{i:3}/{len(codes)} {c} {out[c]['source']} {tg_s} sog={bool(out[c]['salgsoppgave'])} {out[c]['notes'][:1]}")
        except Exception as e:
            print(c, "ERR", e)
            out[c] = dict(EMPTY)
        time.sleep(0.28)
    json.dump(out, open("data/condition.json", "w", encoding="utf-8"), ensure_ascii=False)
    n_tg = sum(1 for v in out.values() if v.get("tg"))
    n_sog = sum(1 for v in out.values() if v.get("salgsoppgave"))
    n_parts = sum(1 for v in out.values() if v.get("tg3") or v.get("tg2"))
    print(f"wrote condition.json  tg {n_tg}/{len(out)}  docs {n_sog}/{len(out)}  parts {n_parts}/{len(out)}")

if __name__ == "__main__":
    main()
