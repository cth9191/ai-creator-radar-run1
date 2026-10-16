import { PANELS, DATA_FILES } from "./panels.js";
import * as ui from "./ui.js";
import { startStars } from "./stars.js";

const { el, chip, metric, timeAgo, fmt } = ui;

async function loadData() {
  const entries = await Promise.all(DATA_FILES.map(async (name) => {
    try {
      const res = await fetch(`data/${name}.json`, { cache: "no-store" });
      if (!res.ok) throw new Error(res.status);
      return [name, await res.json()];
    } catch {
      return [name, null];
    }
  }));
  return Object.fromEntries(entries);
}

function renderStatus(data) {
  const { meta, radar } = data;
  const status = document.getElementById("status");
  const fresh = meta?.x_status === "fresh";
  status.append(
    chip(fresh ? `X fresh · ${timeAgo(meta?.x_grabbed_at)}` : "X waiting for PC", fresh),
    chip(`Refreshed ${timeAgo(meta?.updated_at)}`, Boolean(meta?.updated_at)),
  );
  if (meta?.next_refresh_at) status.append(chip(`Next ${timeAgo(meta.next_refresh_at)}`));
  if (Object.values(data).some((d) => d?.sample)) status.append(chip("Sample data", "sample"));

  const stories = radar?.stories ?? [];
  const gaps = stories.filter((s) => s.gap?.flag === "GAP");
  const top = [...stories].sort((a, b) => (b.gap?.score ?? 0) - (a.gap?.score ?? 0))[0];
  const xPosts = data.x?.posts?.length;
  document.getElementById("metrics").append(
    metric({ label: "Open gaps", value: String(gaps.length), sub: `of ${stories.length} stories`, accent: true }),
    metric({ label: "Top gap", value: top ? String(Math.round(top.gap.score)) : "–", sub: top?.title ?? "no stories yet" }),
    metric({ label: "X posts read", value: fmt(xPosts ?? 0), sub: meta?.x_grabbed_at ? `grabbed ${timeAgo(meta.x_grabbed_at)}` : "no grab yet" }),
    metric({ label: "YouTube searches", value: String(data.youtube?.searches_used ?? 0), sub: "of 8 per refresh" }),
  );
}

function frame(p) {
  const body = el("div", { class: "panel-body" });
  const section = el("section", {
    class: p.hero ? "panel hero" : "panel",
    id: `panel-${p.id}`,
    "data-span": p.span,
    "aria-label": p.title,
  },
    el("header", { class: "panel-head" }, el("h2", { class: "label", text: p.title })),
    body,
    el("footer", { class: "panel-foot" }, el("p", { class: "credit", text: `Built by worker ${p.worker} · ${p.title}` })),
  );
  return { section, body };
}

async function renderPanel(p, ctx) {
  const { section, body } = frame(p);
  document.getElementById("grid").append(section);
  try {
    const mod = await import(p.module);
    await mod.default(body, ctx);
    section.dataset.state = "ready";
  } catch (err) {
    body.replaceChildren(ui.empty(`Worker ${p.worker} is building this panel.`, chip("In progress", "sample")));
    section.dataset.state = "placeholder";
    if (!/Failed to fetch|Importing a module script failed|error loading dynamically/i.test(String(err))) {
      console.warn(`panel ${p.id}:`, err);
    }
  }
}

async function main() {
  startStars(document.getElementById("stars"));
  const data = await loadData();
  renderStatus(data);
  const ctx = { data, ui };
  await Promise.all(PANELS.map((p) => renderPanel(p, ctx)));
  document.body.dataset.ready = "true";
}

main();
