// Loads the page in Chromium at phone and desktop sizes and checks the basics:
// every panel renders with its credit, nothing scrolls sideways, no script errors.
// Screenshots land in shell/tests/out/. Run: node shell/tests/smoke.mjs
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const OUT = join(ROOT, "shell/tests/out");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };

const server = createServer(async (req, res) => {
  const path = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname)).replace(/^(\.\.[/\\])+/, "");
  try {
    const file = join(ROOT, path.endsWith("/") ? path + "index.html" : path);
    const body = await readFile(file);
    res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" }).end(body);
  } catch {
    res.writeHead(404).end("not found");
  }
}).listen(0);
const base = `http://localhost:${server.address().port}/`;

const { PANELS } = await import(new URL("../panels.js", import.meta.url));
// A panel whose module exists must render for real; one not built yet may show its placeholder.
const built = new Set(PANELS.filter((p) => existsSync(join(ROOT, "shell", p.module))).map((p) => `panel-${p.id}`));
const PANEL_MODULE = /\/(radar|x|youtube|ops)\/[\w-]+-panel\.js$/;

const VIEWPORTS = [
  { name: "phone", width: 390, height: 844 },
  { name: "desktop", width: 1440, height: 900 },
];

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
await mkdir(OUT, { recursive: true });
const failures = [];

for (const vp of VIEWPORTS) {
  const page = await browser.newPage({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 2 });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
  page.on("requestfailed", (r) => { if (!/fonts\.(googleapis|gstatic)/.test(r.url()) && !PANEL_MODULE.test(r.url())) errors.push(`request failed ${r.url()}`); });
  page.on("response", (r) => {
    // A missing panel module is fine (shows a placeholder); any other 404 is a bug.
    if (r.status() >= 400 && !PANEL_MODULE.test(r.url())) errors.push(`${r.status()} ${r.url()}`);
  });

  await page.goto(base, { waitUntil: "load" });
  await page.waitForSelector("body[data-ready=true]", { timeout: 15000 });

  const report = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    panels: [...document.querySelectorAll(".panel")].map((p) => ({
      id: p.id,
      state: p.dataset.state,
      credit: p.querySelector(".credit")?.textContent ?? "",
      empty: p.querySelector(".panel-body")?.childElementCount === 0,
    })),
    metrics: document.querySelectorAll("#metrics .metric").length,
  }));

  if (report.overflow > 0) failures.push(`${vp.name}: page scrolls sideways by ${report.overflow}px`);
  if (report.panels.length !== 7) failures.push(`${vp.name}: expected 7 panels, found ${report.panels.length}`);
  for (const p of report.panels) {
    if (!/^Built by worker \d · /i.test(p.credit)) failures.push(`${vp.name}: ${p.id} has no worker credit`);
    if (p.empty) failures.push(`${vp.name}: ${p.id} rendered nothing`);
    if (built.has(p.id) && p.state !== "ready") failures.push(`${vp.name}: ${p.id} module exists but failed to render (see console)`);
  }
  if (report.metrics !== 4) failures.push(`${vp.name}: expected 4 metric cards, found ${report.metrics}`);
  for (const e of errors) failures.push(`${vp.name}: ${e}`);

  await page.screenshot({ path: join(OUT, `${vp.name}.png`), fullPage: true });
  console.log(`${vp.name}: ${report.panels.map((p) => `${p.id}=${p.state}`).join(" ")}`);
  await page.close();
}

await browser.close();
server.close();
if (failures.length) {
  for (const f of failures) console.error("FAIL", f);
  process.exit(1);
}
console.log("smoke test passed");
