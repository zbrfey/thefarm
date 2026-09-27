# -*- coding: utf-8 -*-
"""Tiny static server that always labels HTML as UTF-8.

Proxies Kartverket teig polygons, OpenStreetMap building footprints
clipped to the farm, and an AR13 GetMap image for the 3D ground.
"""
import json, math, re, ssl, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import lru_cache
from pyproj import Transformer

_TO_WGS = Transformer.from_crs(25833, 4326, always_xy=True)
_KV_TEIG = "https://seeiendom.kartverket.no/api/kartutsnitt/teigpolygoner/{knr}/{gnr}/{bnr}/{fnr}/{snr}"
_UA = {"User-Agent": "Gardsjakt/1.0 (local research tool)", "Accept": "application/json"}
_NIBIO_SSL = ssl._create_unverified_context()
_OVERPASS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
_BLABEL = {
    "house": "Våningshus", "residential": "Bustad", "farm": "Gardstun", "barn": "Låve",
    "cabin": "Hytte", "shed": "Skur", "garage": "Garasje", "boathouse": "Naust",
    "farm_auxiliary": "Uthus", "greenhouse": "Veksthus", "yes": "Bygning",
}
_BHEIGHT = {
    "house": 7, "residential": 7, "farm": 9, "barn": 8, "cabin": 4, "shed": 3.2,
    "garage": 3, "boathouse": 3.5, "farm_auxiliary": 5, "greenhouse": 3.5, "yes": 5,
}


def _simp(ring, maxn=500):
    if len(ring) <= maxn:
        return ring
    step = max(1, len(ring) // maxn)
    out = ring[::step]
    if out[-1] != ring[-1]:
        out.append(ring[-1])
    return out


def _ring_lonlat(xy):
    pts = []
    for x, y in xy:
        lon, lat = _TO_WGS.transform(float(x), float(y))
        pts.append([round(lon, 6), round(lat, 6)])
    if pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    return _simp(pts)


def teig_geojson(knr, gnr, bnr, fnr=0, snr=0):
    url = _KV_TEIG.format(knr=knr, gnr=gnr, bnr=bnr, fnr=fnr, snr=snr)
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    rings = []
    teiger = data.get("teiger") or []
    if teiger:
        for t in teiger:
            for ring in t.get("polygoner") or []:
                if ring and len(ring) >= 3:
                    rings.append(_ring_lonlat(ring))
    else:
        for ring in data.get("polygoner") or []:
            if ring and len(ring) >= 3:
                rings.append(_ring_lonlat(ring))
    # GeoJSON polygon = list of rings; we have disjoint teigs → MultiPolygon
    coords = [[ring] for ring in rings]
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"knr": knr, "gnr": gnr, "bnr": bnr, "teigar": len(coords)},
            "geometry": {"type": "MultiPolygon", "coordinates": coords} if coords else None,
        }],
    }


@lru_cache(maxsize=64)
def teig_geojson_cached(knr, gnr, bnr, fnr, snr):
    return json.dumps(teig_geojson(knr, gnr, bnr, fnr, snr), ensure_ascii=False)


def _teig_rings(gj):
    feat = (gj.get("features") or [None])[0] or {}
    geom = feat.get("geometry") or {}
    if geom.get("type") == "Polygon":
        polys = [geom.get("coordinates") or []]
    elif geom.get("type") == "MultiPolygon":
        polys = geom.get("coordinates") or []
    else:
        polys = []
    rings = []
    for poly in polys:
        ring = poly[0] if poly else None
        if ring and len(ring) >= 3:
            rings.append(ring)
    return rings, geom or None


def _pip(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y):
            xint = (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            if x < xint:
                inside = not inside
        j = i
    return inside


def _inside_teig(lon, lat, rings):
    return any(_pip(lon, lat, ring) for ring in rings)


def _height_m(tags):
    raw = str(tags.get("height") or "").replace(",", ".")
    m = re.match(r"([0-9]+(?:\.[0-9]+)?)", raw)
    if m:
        v = float(m.group(1))
        if 1.5 <= v <= 60:
            return round(v, 1)
    try:
        levels = float(str(tags.get("building:levels") or "").replace(",", "."))
    except ValueError:
        levels = 0
    if levels > 0:
        return round(max(2.4, min(40, levels * 3)), 1)
    return _BHEIGHT.get(tags.get("building") or "yes", 5)


def _overpass_buildings(south, west, north, east):
    q = (
        '[out:json][timeout:22];'
        f'way["building"]({south},{west},{north},{east});'
        "out geom;"
    )
    last = None
    for base in _OVERPASS:
        try:
            req = urllib.request.Request(
                base, data=q.encode(), headers={**_UA, "Content-Type": "text/plain"}
            )
            with urllib.request.urlopen(req, timeout=28) as r:
                data = json.load(r)
            return data.get("elements") or []
        except Exception as e:
            last = e
    raise last


def buildings_geojson(knr, gnr, bnr, fnr=0, snr=0):
    gj = teig_geojson(knr, gnr, bnr, fnr, snr)
    rings, geom = _teig_rings(gj)
    if not rings:
        return {
            "type": "FeatureCollection", "bbox": None, "teig": None,
            "features": [], "error": "ingen teig",
        }
    lons = [p[0] for ring in rings for p in ring]
    lats = [p[1] for ring in rings for p in ring]
    minlon, maxlon = min(lons), max(lons)
    minlat, maxlat = min(lats), max(lats)
    pad_lon = max(0.0004, (maxlon - minlon) * 0.04)
    pad_lat = max(0.0003, (maxlat - minlat) * 0.04)
    bbox = [round(minlon - pad_lon, 6), round(minlat - pad_lat, 6),
            round(maxlon + pad_lon, 6), round(maxlat + pad_lat, 6)]
    qpad = 0.0008
    try:
        elements = _overpass_buildings(minlat - qpad, minlon - qpad, maxlat + qpad, maxlon + qpad)
        err = None
    except Exception as e:
        elements = []
        err = "overpass: " + str(e)
    features = []
    for el in elements:
        geom_pts = el.get("geometry") or []
        if len(geom_pts) < 3:
            continue
        ring = [[round(p["lon"], 6), round(p["lat"], 6)] for p in geom_pts]
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)
        hit = _inside_teig(cx, cy, rings) or any(_inside_teig(p[0], p[1], rings) for p in ring[::2])
        if not hit:
            continue
        tags = el.get("tags") or {}
        kind = tags.get("building") or "yes"
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        features.append({
            "type": "Feature",
            "properties": {
                "kind": kind,
                "label": _BLABEL.get(kind, "Bygning"),
                "name": tags.get("name") or "",
                "height_m": _height_m(tags),
                "osm": el.get("id"),
            },
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        })
        if len(features) >= 120:
            break
    out = {
        "type": "FeatureCollection",
        "bbox": bbox,
        "teig": geom,
        "features": features,
    }
    if err:
        out["error"] = err
    return out


_BYGG_CACHE = {}


def buildings_geojson_cached(knr, gnr, bnr, fnr, snr):
    key = (knr, gnr, bnr, fnr, snr)
    hit = _BYGG_CACHE.get(key)
    if hit is not None:
        return hit
    body = buildings_geojson(knr, gnr, bnr, fnr, snr)
    text = json.dumps(body, ensure_ascii=False)
    if not str(body.get("error") or "").startswith("overpass"):
        if len(_BYGG_CACHE) > 64:
            _BYGG_CACHE.pop(next(iter(_BYGG_CACHE)))
        _BYGG_CACHE[key] = text
    return text


def _merc(lon, lat):
    x = lon * 20037508.34 / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
    return x, y * 20037508.34 / 180.0


def ar13_png(minlon, minlat, maxlon, maxlat):
    if not all(math.isfinite(v) for v in (minlon, minlat, maxlon, maxlat)):
        raise ValueError("bbox")
    if maxlon <= minlon or maxlat <= minlat:
        raise ValueError("bbox")
    if (maxlon - minlon) > 1.2 or (maxlat - minlat) > 1.2:
        raise ValueError("bbox for stor")
    x0, y0 = _merc(minlon, minlat)
    x1, y1 = _merc(maxlon, maxlat)
    long = 1024
    if abs(x1 - x0) >= abs(y1 - y0):
        w, h = long, max(64, int(round(long * abs(y1 - y0) / abs(x1 - x0))))
    else:
        h, w = long, max(64, int(round(long * abs(x1 - x0) / abs(y1 - y0))))
    url = (
        "https://wms.nibio.no/cgi-bin/ar5?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap"
        "&LAYERS=Bonitet&STYLES=&CRS=EPSG:3857"
        f"&BBOX={x0},{y0},{x1},{y1}&WIDTH={w}&HEIGHT={h}"
        "&FORMAT=image/png&TRANSPARENT=TRUE&BGCOLOR=0xE7F0E4"
    )
    req = urllib.request.Request(url, headers={"User-Agent": _UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=30, context=_NIBIO_SSL) as r:
        data = r.read()
    if not data.startswith(b"\x89PNG"):
        raise RuntimeError("NIBIO svarte ikkje med PNG")
    return data


class H(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".css": "text/css; charset=utf-8",
    }

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def _send(self, code, body, content_type, cache=True):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        if cache and code == 200:
            self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/ar13map":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            raw = (qs.get("bbox") or [""])[0]
            try:
                minlon, minlat, maxlon, maxlat = [float(x) for x in raw.split(",")]
                body = ar13_png(minlon, minlat, maxlon, maxlat)
                self._send(200, body, "image/png")
            except Exception as e:
                msg = json.dumps({"error": str(e)}).encode("utf-8")
                self._send(502, msg, "application/json; charset=utf-8", cache=False)
            return
        bm = re.match(r"^/byggpoly/(\d+)/(\d+)/(\d+)(?:/(\d+)/(\d+))?$", path)
        if bm:
            knr, gnr, bnr = bm.group(1), bm.group(2), bm.group(3)
            fnr, snr = bm.group(4) or "0", bm.group(5) or "0"
            try:
                body = buildings_geojson_cached(knr, gnr, bnr, fnr, snr).encode("utf-8")
                self._send(200, body, "application/geo+json; charset=utf-8")
            except Exception as e:
                msg = json.dumps({"error": str(e)}).encode("utf-8")
                self._send(502, msg, "application/json; charset=utf-8", cache=False)
            return
        m = re.match(r"^/teigpoly/(\d+)/(\d+)/(\d+)(?:/(\d+)/(\d+))?$", path)
        if m:
            knr, gnr, bnr = m.group(1), m.group(2), m.group(3)
            fnr, snr = m.group(4) or "0", m.group(5) or "0"
            try:
                body = teig_geojson_cached(knr, gnr, bnr, fnr, snr).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/geo+json; charset=utf-8")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                msg = json.dumps({"error": str(e)}).encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
            return
        return super().do_GET()


if __name__ == "__main__":
    print("Gårdsjakt http://127.0.0.1:8766/dashboard.html  (teigpoly, byggpoly, ar13map)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8766), H).serve_forever()
