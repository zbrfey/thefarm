import { cp, mkdir, rm, stat } from "node:fs/promises";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const dist = path.join(root, "dist");
const dash = path.join(root, "dashboard.html");

await stat(dash);
await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });
await cp(dash, path.join(dist, "dashboard.html"));
await cp(dash, path.join(dist, "index.html"));

const media = path.join(root, "data", "media");
await cp(media, path.join(dist, "media"), { recursive: true });
console.log("built dist/ (index.html, dashboard.html, media/)");
