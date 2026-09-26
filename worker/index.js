import { fetchTeig } from "./teig.js";

export default {
  async fetch(request) {
    const path = new URL(request.url).pathname;
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
