// Claude Dev Corner (worker 5): latest Claude Code releases from data/devcorner.json.
import { useOpsCss, ctDay } from "./style.js";

export default function render(body, ctx) {
  useOpsCss();
  const { el, chip, empty, timeAgo, link } = ctx.ui;
  const dev = ctx.data.devcorner;
  const releases = [...(dev?.releases ?? [])]
    .filter((r) => r && r.tag)
    .sort((a, b) => String(b.published_at).localeCompare(String(a.published_at)));

  if (!releases.length) {
    body.append(empty("No Claude Code releases yet. They arrive with the next refresh."));
    return;
  }

  const [latest, ...earlier] = releases;
  const isNew = !dev?.sample && Date.now() - new Date(latest.published_at).getTime() < 48 * 3600 * 1000;

  const feature = el("article", { class: "dc-feature" },
    el("div", { class: "dc-feature-top" },
      el("p", { class: "label", text: "Latest Claude Code" }),
      isNew ? el("span", { class: "dc-new", text: "New" }) : null),
    el("a", { class: "dc-version", href: safe(latest.url), target: "_blank", rel: "noopener", text: latest.tag }),
    el("p", { class: "dc-when" },
      el("span", { text: `Released ${timeAgo(latest.published_at)}` }),
      el("span", { class: "dc-dot", text: "·" }),
      el("span", { text: ctDay(latest.published_at) })),
    (latest.highlights ?? []).length
      ? el("ul", { class: "dc-highlights" }, latest.highlights.slice(0, 5).map((h) => el("li", { text: h })))
      : null,
    el("a", { class: "dc-more", href: safe(latest.url), target: "_blank", rel: "noopener", text: "Release notes →" }),
  );
  body.append(feature);

  if (earlier.length) {
    body.append(el("p", { class: "label dc-sub", text: "Earlier releases" }));
    body.append(el("ul", { class: "dc-earlier" }, earlier.slice(0, 6).map((r) =>
      el("li", {},
        el("a", { class: "dc-row", href: safe(r.url), target: "_blank", rel: "noopener" },
          el("span", { class: "dc-tag", text: r.tag }),
          el("span", { class: "dc-first", text: r.highlights?.[0] ?? r.name ?? "" }),
          el("span", { class: "dc-age", text: timeAgo(r.published_at) }))))));
  }

  const news = (dev?.news ?? []).filter((n) => n?.title);
  if (news.length) {
    body.append(el("p", { class: "label dc-sub", text: "News" }));
    body.append(ctx.ui.list(news.slice(0, 4), (n) => [
      el("div", { class: "row-title" }, link(n.url, n.title)),
      el("div", { class: "row-meta" },
        n.source ? el("span", { text: n.source }) : null,
        n.published_at ? el("span", { text: timeAgo(n.published_at) }) : null),
    ]));
  }

  if (dev?.sample) body.append(el("div", { class: "dc-foot" }, chip("Sample data", "sample")));
}

function safe(url) {
  return /^https:\/\//.test(url || "") ? url : "https://github.com/anthropics/claude-code/releases";
}
