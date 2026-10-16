// Run Log (worker 5): one line per 12-hour refresh, from data/runlog.json.
import { useOpsCss, ctStamp } from "./style.js";

const SHOW = 8;
const STATUS_TEXT = { ok: "OK", partial: "Partial", fail: "Fail" };

export default function render(body, ctx) {
  useOpsCss();
  const { el, chip, empty, timeAgo } = ctx.ui;
  const runs = [...(ctx.data.runlog?.runs ?? [])]
    .filter((r) => r && r.at)
    .sort((a, b) => new Date(b.at) - new Date(a.at));
  const meta = ctx.data.meta;

  if (!runs.length) {
    body.append(empty("No refreshes yet. The first run lands at 6:07 AM or PM Central."));
    return;
  }

  // Summary strip: last run, health of recent runs, next run.
  const recent = runs.slice(0, 30).reverse();
  const okCount = runs.slice(0, 30).filter((r) => r.status === "ok").length;
  body.append(el("div", { class: "rl-summary" },
    el("div", { class: "rl-sum-item" },
      el("p", { class: "label", text: "Last run" }),
      el("p", { class: "rl-sum-val" },
        el("span", { class: `rl-status ${statusClass(runs[0].status)}`, text: STATUS_TEXT[runs[0].status] ?? runs[0].status }),
        el("span", { class: "rl-sum-time", text: timeAgo(runs[0].at) }))),
    el("div", { class: "rl-sum-item rl-health" },
      el("p", { class: "label", text: `Last ${recent.length} run${recent.length === 1 ? "" : "s"} · ${okCount} clean` }),
      el("div", { class: "rl-bars", role: "img", "aria-label": `${okCount} of ${recent.length} recent runs fully ok` },
        recent.map((r) => el("span", { class: `rl-bar ${statusClass(r.status)}`, title: `${ctStamp(r.at)} · ${r.status}` })))),
    meta?.next_refresh_at
      ? el("div", { class: "rl-sum-item" },
          el("p", { class: "label", text: "Next run" }),
          el("p", { class: "rl-sum-val" }, el("span", { class: "rl-sum-time", text: `${ctStamp(meta.next_refresh_at)}` })))
      : null,
  ));

  const term = el("ol", { class: "rl-term", "aria-label": "Refresh runs, newest first" });
  runs.forEach((r, i) => term.append(line(r, i >= SHOW)));
  body.append(term);

  if (runs.length > SHOW) {
    const btn = el("button", { class: "rl-toggle", type: "button", "aria-expanded": "false", text: `Show all ${runs.length} runs` });
    btn.addEventListener("click", () => {
      const open = term.classList.toggle("all");
      btn.setAttribute("aria-expanded", String(open));
      btn.textContent = open ? "Show latest 8" : `Show all ${runs.length} runs`;
    });
    body.append(btn);
  }

  if (ctx.data.runlog?.sample) body.append(el("div", { class: "rl-foot" }, chip("Sample data", "sample")));

  function line(r, extra) {
    const note = r.note || "";
    const noteEl = el("span", { class: "rl-note", title: note, text: note || "—" });
    const li = el("li", { class: extra ? "rl-line rl-extra" : "rl-line", tabindex: note ? "0" : null },
      el("span", { class: "rl-prompt", "aria-hidden": "true", text: "›" }),
      el("time", { class: "rl-time", datetime: r.at, text: ctStamp(r.at) }),
      el("span", { class: `rl-status ${statusClass(r.status)}`, text: STATUS_TEXT[r.status] ?? r.status }),
      el("span", { class: "rl-chips" }, (r.chips ?? []).map((c) => chip(c.label, Boolean(c.ok)))),
      noteEl);
    if (note) {
      const toggle = () => li.classList.toggle("open");
      li.addEventListener("click", toggle);
      li.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
    }
    return li;
  }
}

function statusClass(s) {
  return s === "ok" ? "is-ok" : s === "fail" ? "is-fail" : "is-partial";
}
