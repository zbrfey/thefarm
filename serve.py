# -*- coding: utf-8 -*-
"""Tiny static server that always labels HTML as UTF-8.

Also proxies Kartverket teig polygons as WGS84 GeoJSON so the dashboard
can clip AR5 to the farm being viewed.
"""
import json, re, urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import lru_cache
from pyproj import Transformer

_TO_WGS = Transformer.from_crs(25833, 4326, always_xy=True)
_KV_TEIG = "https://seeiendom.kartverket.no/api/kartutsnitt/teigpolygoner/{knr}/{gnr}/{bnr}/{fnr}/{snr}"
_UA = {"User-Agent": "Gardsjakt/1.0 (local research tool)", "Accept": "application/json"}


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

    def do_GET(self):
        m = re.match(r"^/teigpoly/(\d+)/(\d+)/(\d+)(?:/(\d+)/(\d+))?$", self.path.split("?", 1)[0])
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
    print("Gårdsjakt http://127.0.0.1:8766/dashboard.html  (teigpoly proxy on)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8766), H).serve_forever()
