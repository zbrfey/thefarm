import { fetchTeig } from "./teig.js";

const OVERPASS = [
  "https://overpass-api.de/api/interpreter",
  "https://overpass.kumi.systems/api/interpreter",
];
const UA = "Gardsjakt/1.0 (local research tool)";
const LABEL = {
  house: "Våningshus", residential: "Bustad", farm: "Gardstun", barn: "Låve",
  cabin: "Hytte", shed: "Skur", garage: "Garasje", boathouse: "Naust",
  farm_auxiliary: "Uthus", greenhouse: "Veksthus", yes: "Bygning",
};
const HEIGHT = {
  house: 7, residential: 7, farm: 9, barn: 8, cabin: 4, shed: 3.2,
  garage: 3, boathouse: 3.5, farm_auxiliary: 5, greenhouse: 3.5, yes: 5,
};

function teigRings(gj) {
  const feat = (gj.features || [])[0] || {};
  const geom = feat.geometry || null;
  const polys = !geom ? [] : geom.type === "Polygon" ? [geom.coordinates] : geom.type === "MultiPolygon" ? geom.coordinates : [];
  const rings = [];
  for (const poly of polys) {
    const ring = poly && poly[0];
    if (ring && ring.length >= 3) rings.push(ring);
  }
  return { rings, geom };
}

function pip(x, y, ring) {
  let inside = false;
  let j = ring.length - 1;
  for (let i = 0; i < ring.length; i++) {
    const xi = ring[i][0], yi = ring[i][1];
    const xj = ring[j][0], yj = ring[j][1];
    if ((yi > y) !== (yj > y)) {
      const xint = (xj - xi) * (y - yi) / ((yj - yi) || 1e-12) + xi;
      if (x < xint) inside = !inside;
    }
    j = i;
  }
  return inside;
}

function insideTeig(lon, lat, rings) {
  return rings.some((ring) => pip(lon, lat, ring));
}

function heightM(tags) {
  const raw = String(tags.height || "").replace(",", ".");
  const m = raw.match(/([0-9]+(?:\.[0-9]+)?)/);
  if (m) {
    const v = Number(m[1]);
    if (v >= 1.5 && v <= 60) return Math.round(v * 10) / 10;
  }
  const levels = Number(String(tags["building:levels"] || "").replace(",", "."));
  if (levels > 0) return Math.round(Math.max(2.4, Math.min(40, levels * 3)) * 10) / 10;
  return HEIGHT[tags.building || "yes"] || 5;
}

async function overpassBuildings(south, west, north, east) {
  const q = `[out:json][timeout:22];way["building"](${south},${west},${north},${east});out geom;`;
  let last = "overpass";
  for (const base of OVERPASS) {
    try {
      const r = await fetch(base, {
        method: "POST",
        headers: { "User-Agent": UA, "Content-Type": "text/plain" },
        body: q,
      });
      if (!r.ok) { last = `overpass ${r.status}`; continue; }
      const data = await r.json();
      return data.elements || [];
    } catch (err) {
      last = String(err && err.message || err);
    }
  }
  throw new Error(last);
}

export async function fetchBuildings(knr, gnr, bnr, fnr = "0", snr = "0") {
  const gj = await fetchTeig(knr, gnr, bnr, fnr, snr);
  const { rings, geom } = teigRings(gj);
  if (!rings.length) {
    return { type: "FeatureCollection", bbox: null, teig: null, features: [], error: "ingen teig" };
  }
  const lons = rings.flat().map((p) => p[0]);
  const lats = rings.flat().map((p) => p[1]);
  const minlon = Math.min(...lons), maxlon = Math.max(...lons);
  const minlat = Math.min(...lats), maxlat = Math.max(...lats);
  const padLon = Math.max(0.0004, (maxlon - minlon) * 0.04);
  const padLat = Math.max(0.0003, (maxlat - minlat) * 0.04);
  const bbox = [
    round6(minlon - padLon), round6(minlat - padLat),
    round6(maxlon + padLon), round6(maxlat + padLat),
  ];
  const qpad = 0.0008;
  let elements = [];
  let error = null;
  try {
    elements = await overpassBuildings(minlat - qpad, minlon - qpad, maxlat + qpad, maxlon + qpad);
  } catch (err) {
    error = "overpass: " + String(err && err.message || err);
  }
  const features = [];
  for (const el of elements) {
    const pts = el.geometry || [];
    if (pts.length < 3) continue;
    const ring = pts.map((p) => [round6(p.lon), round6(p.lat)]);
    const cx = ring.reduce((s, p) => s + p[0], 0) / ring.length;
    const cy = ring.reduce((s, p) => s + p[1], 0) / ring.length;
    const hit = insideTeig(cx, cy, rings) || ring.some((p, i) => i % 2 === 0 && insideTeig(p[0], p[1], rings));
    if (!hit) continue;
    const tags = el.tags || {};
    const kind = tags.building || "yes";
    if (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) ring.push(ring[0]);
    features.push({
      type: "Feature",
      properties: {
        kind,
        label: LABEL[kind] || "Bygning",
        name: tags.name || "",
        height_m: heightM(tags),
        osm: el.id,
      },
      geometry: { type: "Polygon", coordinates: [ring] },
    });
    if (features.length >= 120) break;
  }
  const out = { type: "FeatureCollection", bbox, teig: geom, features };
  if (error) out.error = error;
  return out;
}

function round6(n) {
  return Math.round(n * 1e6) / 1e6;
}

function merc(lon, lat) {
  const x = lon * 20037508.34 / 180;
  const y = Math.log(Math.tan((90 + lat) * Math.PI / 360)) / (Math.PI / 180);
  return [x, y * 20037508.34 / 180];
}

export async function fetchAr13(minlon, minlat, maxlon, maxlat) {
  const vals = [minlon, minlat, maxlon, maxlat];
  if (vals.some((v) => !Number.isFinite(v)) || maxlon <= minlon || maxlat <= minlat) {
    throw new Error("bbox");
  }
  if (maxlon - minlon > 1.2 || maxlat - minlat > 1.2) throw new Error("bbox for stor");
  const [x0, y0] = merc(minlon, minlat);
  const [x1, y1] = merc(maxlon, maxlat);
  const long = 1024;
  let w, h;
  if (Math.abs(x1 - x0) >= Math.abs(y1 - y0)) {
    w = long;
    h = Math.max(64, Math.round(long * Math.abs(y1 - y0) / Math.abs(x1 - x0)));
  } else {
    h = long;
    w = Math.max(64, Math.round(long * Math.abs(x1 - x0) / Math.abs(y1 - y0)));
  }
  const url = "https://wms.nibio.no/cgi-bin/ar5?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap"
    + "&LAYERS=Bonitet&STYLES=&CRS=EPSG:3857"
    + `&BBOX=${x0},${y0},${x1},${y1}&WIDTH=${w}&HEIGHT=${h}`
    + "&FORMAT=image/png&TRANSPARENT=TRUE&BGCOLOR=0xE7F0E4";
  const r = await fetch(url, { headers: { "User-Agent": UA } });
  if (!r.ok) throw new Error(`NIBIO ${r.status}`);
  const buf = await r.arrayBuffer();
  const head = new Uint8Array(buf, 0, 4);
  if (head[0] !== 0x89 || head[1] !== 0x50) throw new Error("NIBIO svarte ikkje med PNG");
  return buf;
}
