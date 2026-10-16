// My Stats (worker 4): the Chase AI channel at a glance, and how each recent
// upload is doing against the channel's median views.
import { ensureCss } from "./coverage-panel.js";

function multiplier(x) {
  return `${x >= 10 ? Math.round(x) : x.toFixed(1)}×`;
}

function notConnected(ui, sample) {
  const { el, empty, chip } = ui;
  return empty("",
    el("div", { class: "yt-empty-title", text: "Channel not connected yet" }),
    el("div", { class: "yt-empty-hint" },
      "Subscribers, median views and how each new upload stacks up show here once ",
      el("code", { text: "channel_handle" }), " is set in ", el("code", { text: "youtube/config.json" }), "."),
    el("div", { class: "yt-ghost", "aria-hidden": "true" },
      el("span", { style: "width:72%" }), el("span", { style: "width:45%" }), el("span", { style: "width:88%" })),
    sample ? chip("Sample", "sample") : null);
}

export default async function render(body, ctx) {
  const ui = ctx.ui;
  const { el, metric, fmt, timeAgo, link } = ui;
  const cssReady = ensureCss();
  const st = ctx.data.stats;

  if (!st || st.sample || !st.channel?.id) {
    body.append(notConnected(ui, st?.sample));
    // the shell's .empty puts an empty first <span> in; drop it
    body.querySelector(".empty > span:first-child:empty")?.remove();
    return cssReady;
  }

  const ch = st.channel;
  body.append(el("div", { class: "yt-metrics" },
    metric({ label: "Subscribers", value: fmt(ch.subs), sub: "total", accent: true }),
    metric({ label: "Median", value: fmt(st.median_views), sub: "views per video" }),
    metric({ label: "Videos", value: fmt(ch.video_count ?? 0), sub: "uploaded" })));

  const latest = st.latest ?? [];
  body.append(el("div", { class: "yt-section" }, el("p", { class: "label", text: "Latest uploads vs median" })));
  if (!latest.length) {
    body.append(ui.empty("No uploads found yet."));
    return cssReady;
  }
  // Bar scale: the median sits at 1.0; leave room for the best video (at least 2× wide).
  const scale = Math.max(2, ...latest.map((v) => v.vs_median ?? 0)) * 1.05;
  const pct = (x) => `${Math.min(100, (x / scale) * 100).toFixed(1)}%`;
  body.append(el("ul", { class: "yt-latest" }, latest.map((v) => {
    const x = v.vs_median ?? 0;
    const dir = x >= 1 ? "up" : "down";
    return el("li", { class: "yt-up" },
      el("div", { class: "yt-up-head" },
        el("div", { class: "yt-up-title" }, link(v.url, v.title || "Untitled")),
        el("span", { class: `yt-x ${dir}`, text: multiplier(x) })),
      el("div", { class: "yt-track", role: "img", "aria-label": `${multiplier(x)} the median` },
        el("div", { class: `yt-fill ${dir}`, style: `width:${pct(x)}` }),
        el("div", { class: "yt-median-line", style: `left:${pct(1)}` })),
      el("div", { class: "yt-up-meta" },
        el("span", { text: `${fmt(v.views)} views` }),
        el("span", { text: timeAgo(v.published_at) })));
  })));
  body.append(el("div", { class: "yt-legend" }, el("i"), `median ${fmt(st.median_views)} views, last 15 uploads 48h+ old`));
  return cssReady;
}
