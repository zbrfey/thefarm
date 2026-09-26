import proj4 from "proj4";

proj4.defs(
  "EPSG:25833",
  "+proj=utm +zone=33 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs +type=crs"
);

const KV = "https://seeiendom.kartverket.no/api/kartutsnitt/teigpolygoner";

export function toLonLat(x, y) {
  const [lon, lat] = proj4("EPSG:25833", "WGS84", [x, y]);
  return [round6(lon), round6(lat)];
}

function round6(n) {
  return Math.round(n * 1e6) / 1e6;
}

function simplify(ring, maxn = 500) {
  if (ring.length <= maxn) return ring;
  const step = Math.max(1, Math.floor(ring.length / maxn));
  const out = ring.filter((_, i) => i % step === 0);
  const last = ring[ring.length - 1];
  const end = out[out.length - 1];
  if (!end || end[0] !== last[0] || end[1] !== last[1]) out.push(last);
  return out;
}

function ringLonLat(xy) {
  const pts = xy.map(([x, y]) => toLonLat(Number(x), Number(y)));
  if (pts.length && (pts[0][0] !== pts[pts.length - 1][0] || pts[0][1] !== pts[pts.length - 1][1])) {
    pts.push(pts[0]);
  }
  return simplify(pts);
}

export function geojsonFromKartverket(data, ids) {
  const rings = [];
  const teiger = data.teiger || [];
  const sources = teiger.length ? teiger : [data];
  for (const t of sources) {
    for (const ring of t.polygoner || []) {
      if (ring && ring.length >= 3) rings.push(ringLonLat(ring));
    }
  }
  return {
    type: "FeatureCollection",
    features: [{
      type: "Feature",
      properties: { ...ids, teigar: rings.length },
      geometry: rings.length ? { type: "MultiPolygon", coordinates: rings.map((ring) => [ring]) } : null,
    }],
  };
}

export async function fetchTeig(knr, gnr, bnr, fnr = "0", snr = "0") {
  const url = `${KV}/${knr}/${gnr}/${bnr}/${fnr}/${snr}`;
  const r = await fetch(url, {
    headers: { "User-Agent": "Gardsjakt/1.0 (local research tool)", Accept: "application/json" },
  });
  if (!r.ok) throw new Error(`Kartverket ${r.status}`);
  const data = await r.json();
  return geojsonFromKartverket(data, { knr, gnr, bnr });
}
