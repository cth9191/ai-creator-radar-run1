// Story Radar (hero panel): every story's trail from X to YouTube, with its gap score.
// Data: data/radar.json (written by radar/gaps.py). Falls back to stories.json / youtube.json
// for top posts and videos when radar.json is an older shape.
import { loadCss, flagState, flagOrder, timeline, scoreBar } from "./shared.js";

const SHOW_FIRST = 5;

export default async function render(body, ctx) {
  await loadCss();
  const { el, chip, empty, timeAgo } = ctx.ui;
  const radar = ctx.data.radar;
  const meta = ctx.data.meta;
  const stories = Array.isArray(radar?.stories) ? [...radar.stories] : [];

  const root = el("div", { class: "rdr" });
  body.append(root);

  if (meta?.x_status === "waiting_for_pc") {
    root.append(el("p", { class: "rdr-note" },
      el("span", { class: "rdr-note-dot", "aria-hidden": "true" }),
      `Stories from the last PC grab, ${meta.x_grabbed_at ? timeAgo(meta.x_grabbed_at) : "time unknown"}. YouTube is still refreshed.`));
  }

  if (!stories.length) {
    root.append(empty("No stories yet. The radar fills after the first X grab."));
    return;
  }

  stories.sort((a, b) => flagOrder(a) - flagOrder(b) || (b.gap?.score ?? 0) - (a.gap?.score ?? 0));
  const counts = { GAP: 0, CLOSING: 0, COVERED: 0 };
  for (const s of stories) if (s.gap?.flag in counts) counts[s.gap.flag] += 1;

  root.append(el("div", { class: "rdr-top" },
    el("div", { class: "rdr-counts" },
      chip(`${counts.GAP} gap${counts.GAP === 1 ? "" : "s"}`, "gap"),
      counts.CLOSING ? chip(`${counts.CLOSING} closing`, "closing") : null,
      counts.COVERED ? chip(`${counts.COVERED} covered`, "covered") : null),
    el("div", { class: "rdr-legend", "aria-hidden": "true" },
      el("span", {}, el("i", { class: "lg-x" }), "X post"),
      el("span", {}, el("i", { class: "lg-yt" }), "YouTube video"),
      el("span", {}, el("i", { class: "lg-gap" }), "No video yet")),
  ));

  const list = el("ol", { class: "rdr-list" });
  root.append(list);
  const now = Date.now();
  stories.forEach((s, i) => {
    const item = storyItem(s, ctx, now);
    if (i >= SHOW_FIRST) item.hidden = true;
    list.append(item);
  });

  if (stories.length > SHOW_FIRST) {
    const more = el("button", { class: "rdr-more", type: "button" }, `Show all ${stories.length} stories`);
    more.addEventListener("click", () => {
      for (const li of list.children) li.hidden = false;
      more.remove();
    });
    root.append(more);
  }
  if (radar?.generated_at) {
    root.append(el("p", { class: "rdr-foot" }, `Scored ${timeAgo(radar.generated_at)} · gap = hot on X × not yet on YouTube`));
  }
}

function storyItem(s, ctx, now) {
  const { el, chip, fmt } = ctx.ui;
  const flag = s.gap?.flag ?? "COVERED";
  const score = Math.round(s.gap?.score ?? 0);
  const yt = s.youtube ?? {};
  const x = s.x ?? {};
  const checked = yt.checked !== false;

  const li = el("li", { class: `rdr-story is-${flagState(flag)}` });
  const head = el("div", { class: "rdr-head", role: "button", tabindex: "0", "aria-expanded": "false" });

  const titleBox = el("div", { class: "rdr-titlebox" },
    el("div", { class: "rdr-flagrow" },
      chip(flag, flagState(flag)),
      el("span", { class: "rdr-score num", "aria-label": `Gap score ${score}` }, String(score)),
      el("span", { class: "rdr-caret", "aria-hidden": "true" })),
    el("h3", { class: "rdr-title", text: s.title ?? s.id }),
    s.summary ? el("p", { class: "rdr-summary", text: s.summary }) : null);

  const stats = el("div", { class: "rdr-stats" },
    stat("X", `${fmt(x.post_count ?? 0)} post${x.post_count === 1 ? "" : "s"}`, `${fmt(x.engagement ?? 0)} eng`, "x", el),
    stat("YouTube", checked ? `${fmt(yt.video_count ?? 0)} video${yt.video_count === 1 ? "" : "s"}` : "not checked",
      checked ? `${fmt(yt.total_views ?? 0)} views` : "budget ran out", "yt", el),
    scoreBar(score, flag, el));

  head.append(titleBox, timeline(s, now, ctx.ui), stats);
  li.append(head);

  let detail = null;
  const toggle = () => {
    const open = head.getAttribute("aria-expanded") !== "true";
    head.setAttribute("aria-expanded", String(open));
    li.classList.toggle("open", open);
    if (open && !detail) {
      detail = details(s, ctx);
      li.append(detail);
    }
    if (detail) detail.hidden = !open;
  };
  head.addEventListener("click", toggle);
  head.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
  });
  return li;
}

function stat(label, big, small, kind, el) {
  return el("div", { class: `rdr-stat ${kind}` },
    el("p", { class: "label", text: label }),
    el("div", { class: "rdr-stat-line" },
      el("span", { class: "rdr-stat-big num", text: big }),
      el("span", { class: "rdr-stat-small", text: small })));
}

function details(s, ctx) {
  const { el, timeAgo, fmt, link, empty } = ctx.ui;
  const posts = s.x?.top_posts?.length ? s.x.top_posts
    : (ctx.data.stories?.stories ?? []).find((t) => t.id === s.id)?.top_posts ?? [];
  const cov = ctx.data.youtube?.coverage?.[s.id];
  const videos = s.youtube?.videos?.length ? s.youtube.videos : (cov?.videos ?? []);

  const postList = posts.length
    ? el("ul", { class: "rdr-items" }, posts.slice(0, 3).map((p) => {
        const eng = (p.likes ?? 0) + 2 * (p.reposts ?? 0) + (p.replies ?? 0) + 2 * (p.quotes ?? 0);
        return el("li", { class: "rdr-item" },
          el("div", { class: "rdr-item-meta" },
            el("span", { class: "dot x", "aria-hidden": "true" }),
            el("span", { text: `@${p.author?.handle ?? "unknown"}` }),
            el("span", { text: timeAgo(p.created_at) }),
            el("span", { text: `${fmt(eng)} eng` })),
          el("p", { class: "rdr-item-text", text: p.text ?? "" }),
          link(p.url, "Open on X ↗"));
      }))
    : empty("No posts saved for this story.");

  let videoList;
  if (videos.length) {
    videoList = el("ul", { class: "rdr-items" }, videos.slice(0, 5).map((v) =>
      el("li", { class: "rdr-item" },
        el("div", { class: "rdr-item-meta" },
          el("span", { class: "dot yt", "aria-hidden": "true" }),
          el("span", { text: v.channel ?? "YouTube" }),
          el("span", { text: timeAgo(v.published_at) }),
          el("span", { text: `${fmt(v.views ?? 0)} views` })),
        el("p", { class: "rdr-item-text", text: v.title ?? "" }),
        link(v.url, "Watch on YouTube ↗"))));
  } else if (s.youtube?.checked === false) {
    videoList = empty("Not searched on YouTube yet (search budget ran out). Treat this gap as likely, not confirmed.");
  } else {
    videoList = empty("No YouTube videos yet. This is the gap.");
  }

  const q = s.search_query
    ? el("p", { class: "rdr-query" }, "Searched YouTube for ", el("span", { class: "num", text: `“${s.search_query}”` }))
    : null;

  return el("div", { class: "rdr-detail" },
    el("section", { class: "rdr-col" }, el("p", { class: "label", text: "Top posts on X" }), postList),
    el("section", { class: "rdr-col" }, el("p", { class: "label", text: "On YouTube" }), videoList, q));
}
