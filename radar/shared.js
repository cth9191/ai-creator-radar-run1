// Helpers shared by the Story Radar and Video Ideas panels.

let cssPromise = null;

// Inject radar/radar.css once, and wait for it (max 1.5s) so the panel never flashes unstyled.
export function loadCss() {
  if (cssPromise) return cssPromise;
  const href = new URL("./radar.css", import.meta.url).href;
  let link = [...document.querySelectorAll('link[rel="stylesheet"]')].find((l) => l.href === href);
  if (link) return (cssPromise = Promise.resolve());
  link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  link.dataset.radarCss = "";
  cssPromise = new Promise((resolve) => {
    link.addEventListener("load", resolve, { once: true });
    link.addEventListener("error", resolve, { once: true });
    setTimeout(resolve, 1500);
  });
  document.head.append(link);
  return cssPromise;
}

export function flagState(flag) {
  return flag === "GAP" ? "gap" : flag === "CLOSING" ? "closing" : "covered";
}

export function flagOrder(story) {
  return { GAP: 0, CLOSING: 1, COVERED: 2 }[story?.gap?.flag] ?? 3;
}

const HOUR = 3600e3;

export function duration(ms) {
  const m = Math.max(0, ms) / 60000;
  if (m < 60) return `${Math.max(1, Math.round(m))}m`;
  const h = m / 60;
  if (h < 48) return `${Math.round(h)}h`;
  return `${Math.round(h / 24)}d`;
}

// Horizontal X -> YouTube timeline: first seen on the left, now on the right.
export function timeline(story, now, ui) {
  const { el, timeAgo } = ui;
  const trail = (story.trail ?? [])
    .map((t) => ({ ...t, ms: Date.parse(t.at) }))
    .filter((t) => Number.isFinite(t.ms));
  const firstSeen = Date.parse(story.x?.first_seen);
  const first = Number.isFinite(firstSeen) ? firstSeen : (trail[0]?.ms ?? now);
  const times = trail.map((t) => t.ms);
  const start = Math.min(first, ...times);
  const end = Math.max(now, ...times, start + HOUR);
  const pos = (ms) => Math.min(100, Math.max(0, ((ms - start) / (end - start)) * 100));

  const firstVideo = trail.find((t) => t.platform === "youtube" && t.ms >= first - HOUR);
  const gapEnd = firstVideo ? firstVideo.ms : end;

  const lane = el("div", { class: "tl-lane" },
    el("div", { class: "tl-track" }),
    el("div", {
      class: firstVideo ? "tl-gap closed" : "tl-gap",
      style: `left:${pos(first)}%;width:${Math.max(0, pos(gapEnd) - pos(first))}%`,
    }));

  const counts = { x: 0, youtube: 0 };
  for (const t of trail) {
    const isPeak = t.platform === "x" && /^Peak/.test(t.label);
    const isFirst = t.platform === "x" && /^First/.test(t.label);
    counts[t.platform] = (counts[t.platform] ?? 0) + 1;
    lane.append(el("span", {
      class: `tl-dot ${t.platform === "youtube" ? "yt" : "x"}${isPeak ? " peak" : ""}${isFirst ? " first" : ""}`,
      style: `left:${pos(t.ms)}%`,
      title: `${t.label} · ${timeAgo(t.at, now)}`,
    }));
  }
  if (!counts.x) {
    lane.append(el("span", { class: "tl-dot x first", style: `left:${pos(first)}%`, title: "First seen on X" }));
  }
  lane.append(el("span", { class: "tl-now", style: "left:100%", "aria-hidden": "true" }));

  const olderVideos = counts.youtube > 0;
  const gapText = firstVideo
    ? `first video ${duration(firstVideo.ms - first)} later`
    : `${duration(end - first)} · no ${olderVideos ? "new " : ""}video yet`;

  return el("div", {
    class: "tl",
    role: "img",
    "aria-label": `First seen on X ${timeAgo(new Date(first).toISOString(), now)}; ${gapText}`,
  },
    lane,
    el("div", { class: "tl-axis" },
      el("span", { text: `first seen ${timeAgo(new Date(first).toISOString(), now)}` }),
      el("span", { class: firstVideo ? "tl-axis-gap closed" : "tl-axis-gap", text: gapText }),
      el("span", { text: "now" })));
}

export function scoreBar(score, flag, el) {
  const s = Math.max(0, Math.min(100, Math.round(score)));
  return el("div", { class: `rdr-bar is-${flagState(flag)}` },
    el("div", { class: "rdr-bar-head" },
      el("p", { class: "label", text: "Gap score" }),
      el("span", { class: "num", text: `${s}/100` })),
    el("div", { class: "rdr-bar-track", role: "meter", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(s) },
      el("div", { class: "rdr-bar-fill", style: `width:${s}%` }),
      el("i", { class: "rdr-bar-tick", style: "left:25%" }),
      el("i", { class: "rdr-bar-tick", style: "left:60%" })));
}
