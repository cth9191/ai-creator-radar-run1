// On YouTube (worker 4): how much YouTube coverage each X story has, plus small
// channels whose video on a story is pulling far more views than they have subs.
const CSS_HREF = new URL("./youtube.css", import.meta.url).href;
const MAX_SEARCHES = 8;
const VIDEOS_PER_STORY = 2;

export function ensureCss() {
  if ([...document.querySelectorAll("link[rel=stylesheet]")].some((l) => l.href === CSS_HREF)) return Promise.resolve();
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = CSS_HREF;
  const done = new Promise((resolve) => {
    link.onload = link.onerror = resolve;
    setTimeout(resolve, 1500);
  });
  document.head.append(link);
  return done;
}

const FLAG_CLASS = { GAP: "gap", CLOSING: "closing", COVERED: "covered" };

// Stories in the order the radar ranks them (gap score), else by X engagement.
function orderedStories(data, coverage) {
  const radar = data.radar?.stories ?? [];
  const stories = data.stories?.stories ?? [];
  const byId = new Map();
  [...radar].sort((a, b) => (b.gap?.score ?? 0) - (a.gap?.score ?? 0))
    .forEach((s) => byId.set(s.id, { id: s.id, title: s.title, flag: s.gap?.flag }));
  [...stories].sort((a, b) => (b.engagement ?? 0) - (a.engagement ?? 0))
    .forEach((s) => { if (!byId.has(s.id)) byId.set(s.id, { id: s.id, title: s.title }); });
  for (const [id, c] of Object.entries(coverage)) if (!byId.has(id)) byId.set(id, { id, title: c.query });
  return [...byId.values()].filter((s) => coverage[s.id]);
}

function storyBlock(s, cov, ui) {
  const { el, chip, fmt, timeAgo, link } = ui;
  const count = cov.video_count ?? 0;
  const views = cov.total_views ?? (cov.videos ?? []).reduce((n, v) => n + (v.views ?? 0), 0);
  const zero = count === 0;
  const head = el("div", { class: "yt-story-head" },
    el("div", { class: "yt-story-title", text: s.title || cov.query }),
    s.flag ? chip(s.flag, FLAG_CLASS[s.flag]) : null);
  const counts = el("div", { class: "yt-counts" },
    el("span", { class: zero ? "yt-count zero" : "yt-count" }, el("b", { text: String(count) }), el("span", { text: count === 1 ? "video" : "videos" })),
    el("span", { class: zero ? "yt-count zero" : "yt-count" }, el("b", { text: fmt(views) }), el("span", { text: "views" })),
    zero ? el("span", { class: "yt-open", text: "Nobody on YouTube yet. Open lane." }) : null);
  const vids = [...(cov.videos ?? [])].sort((a, b) => (b.views ?? 0) - (a.views ?? 0)).slice(0, VIDEOS_PER_STORY);
  const list = vids.length ? el("ul", { class: "yt-videos" }, vids.map((v) => el("li", { class: "yt-video" },
    el("div", { class: "yt-video-title" }, link(v.url, v.title || "Untitled")),
    el("div", { class: "yt-video-views", text: `${fmt(v.views)} views` }),
    el("div", { class: "yt-video-meta", text: [v.channel, v.channel_subs != null ? `${fmt(v.channel_subs)} subs` : null, timeAgo(v.published_at)].filter(Boolean).join(" · ") }),
  ))) : null;
  return el("li", { class: s.flag === "GAP" || zero ? "yt-story is-gap" : "yt-story" }, head, counts, list);
}

function risingBlock(rising, ui) {
  const { el, fmt, link } = ui;
  return el("ul", { class: "yt-rising" }, rising.map((r) => {
    const ratio = r.views_per_sub ?? (r.subs ? r.video.views / r.subs : 0);
    return el("li", { class: "yt-rise" },
      el("div", { class: "yt-mult", title: "views per subscriber" },
        el("b", { text: `${ratio >= 10 ? Math.round(ratio) : ratio.toFixed(1)}×` }), el("span", { text: "views/sub" })),
      el("div", { class: "yt-rise-chan" }, link(r.channel_url, r.channel)),
      el("div", { class: "yt-rise-video" }, link(r.video?.url, r.video?.title || "video")),
      el("div", { class: "yt-rise-meta", text: `${fmt(r.video?.views)} views · ${fmt(r.subs)} subs` }),
    );
  }));
}

export default async function render(body, ctx) {
  const ui = ctx.ui;
  const { el, chip, empty, timeAgo } = ui;
  const cssReady = ensureCss();
  const yt = ctx.data.youtube;

  if (!yt || !yt.coverage) {
    body.append(empty("No YouTube check yet. Coverage appears after the next refresh."));
    return cssReady;
  }

  const used = yt.searches_used ?? 0;
  body.append(el("div", { class: "yt-bar-top" },
    el("div", { class: "chips" },
      chip(`${used}/${MAX_SEARCHES} searches`, used <= MAX_SEARCHES ? undefined : false),
      yt.sample ? chip("Sample", "sample") : null),
    el("span", { class: "yt-small", text: `Checked ${timeAgo(yt.generated_at)}` })));

  const stories = orderedStories(ctx.data, yt.coverage);
  if (stories.length) {
    body.append(el("ul", { class: "yt-stories" }, stories.map((s) => storyBlock(s, yt.coverage[s.id], ui))));
  } else {
    body.append(empty("No stories were checked on YouTube this run."));
  }

  body.append(el("div", { class: "yt-section" }, el("p", { class: "label", text: "Small channels popping off" })));
  const rising = (yt.rising ?? []).filter((r) => r && r.video);
  body.append(rising.length
    ? risingBlock(rising, ui)
    : empty("No small channel is out-punching its size on these stories yet."));
  return cssReady;
}
