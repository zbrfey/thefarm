import { fetchTeig } from "./teig.js";
import { fetchAr13, fetchBuildings } from "./bygg.js";

function json(body, status = 200) {
  return new Response(body, {
    status,
    headers: {
      "Content-Type": status === 200 && body.startsWith("{") ? "application/geo+json; charset=utf-8" : "application/json; charset=utf-8",
      ...(status === 200 ? { "Cache-Control": "public, max-age=86400" } : {}),
    },
  });
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname;
    if (path === "/ar13map") {
      try {
        const parts = (url.searchParams.get("bbox") || "").split(",").map(Number);
        const buf = await fetchAr13(parts[0], parts[1], parts[2], parts[3]);
        return new Response(buf, {
          headers: { "Content-Type": "image/png", "Cache-Control": "public, max-age=86400" },
        });
      } catch (err) {
        return json(JSON.stringify({ error: String(err && err.message || err) }), 502);
      }
    }
    const bm = path.match(/^\/byggpoly\/(\d+)\/(\d+)\/(\d+)(?:\/(\d+)\/(\d+))?$/);
    if (bm) {
      const [, knr, gnr, bnr, fnr, snr] = bm;
      try {
        return json(JSON.stringify(await fetchBuildings(knr, gnr, bnr, fnr || "0", snr || "0")));
      } catch (err) {
        return json(JSON.stringify({ error: String(err && err.message || err) }), 502);
      }
    }
    const m = path.match(/^\/teigpoly\/(\d+)\/(\d+)\/(\d+)(?:\/(\d+)\/(\d+))?$/);
    if (!m) return new Response("Not found", { status: 404 });
    const [, knr, gnr, bnr, fnr, snr] = m;
    try {
      const body = JSON.stringify(await fetchTeig(knr, gnr, bnr, fnr || "0", snr || "0"));
      return new Response(body, {
        headers: {
          "Content-Type": "application/geo+json; charset=utf-8",
          "Cache-Control": "public, max-age=86400",
        },
      });
    } catch (err) {
      return new Response(JSON.stringify({ error: String(err && err.message || err) }), {
        status: 502,
        headers: { "Content-Type": "application/json; charset=utf-8" },
      });
    }
  },
};
