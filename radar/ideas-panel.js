// Video Ideas: one concrete angle per story, ranked by gap size.
// Data: data/ideas.json (written by radar/gaps.py).
import { loadCss, flagState } from "./shared.js";

export default async function render(body, ctx) {
  await loadCss();
  const { el, chip, empty, timeAgo } = ctx.ui;
  const ideas = Array.isArray(ctx.data.ideas?.ideas) ? [...ctx.data.ideas.ideas] : [];
  ideas.sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));

  if (!ideas.length) {
    body.append(empty("No video ideas yet. They appear once the radar has stories."));
    return;
  }

  const list = el("ol", { class: "ideas" });
  for (const idea of ideas.slice(0, 6)) {
    const state = flagState(idea.flag);
    const score = Math.round(idea.gap_score ?? 0);
    list.append(el("li", { class: `idea is-${state}` },
      el("span", { class: "idea-rank num", "aria-label": `Rank ${idea.rank}` }, String(idea.rank ?? "").padStart(2, "0")),
      el("div", { class: "idea-main" },
        el("h3", { class: "idea-angle", text: idea.angle }),
        el("div", { class: "idea-meta" },
          el("span", { class: "idea-score num", title: "Gap score" }, String(score)),
          idea.flag ? chip(idea.flag, state) : null,
          el("span", { class: "idea-story", text: idea.title })),
        idea.why ? el("p", { class: "idea-why", text: idea.why }) : null)));
  }
  body.append(list);
  if (ctx.data.ideas?.generated_at) {
    body.append(el("p", { class: "rdr-foot", text: `Ranked by gap score · ${timeAgo(ctx.data.ideas.generated_at)}` }));
  }
}
