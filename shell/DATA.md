# Data contract

The page is static. It reads JSON files from `data/` and never calls an API
from the browser. Every file has a schema in `shell/schema/` and CI validates
`data/*.json` against it on every PR.

| File | Written by | What it holds |
|---|---|---|
| `x.json` | PC grab (W2), copied in by the refresh (W5) | Raw X posts from the latest grab |
| `stories.json` | W3 | X posts grouped into stories |
| `youtube.json` | W4 | YouTube coverage per story, plus rising small channels |
| `radar.json` | W3 | Stories joined with coverage, gap score and trail |
| `ideas.json` | W3 | Video angles ranked by gap |
| `stats.json` | W4 | "Chase AI" channel stats |
| `devcorner.json` | W5 | Claude Code releases and news |
| `runlog.json` | W5 | One line per refresh |
| `meta.json` | W5 | When the page was refreshed and whether X is fresh |

All times are ISO 8601 UTC strings (`2026-10-16T11:07:00Z`).
All files carry `"sample": true` while they hold placeholder data, so the page can
show a SAMPLE chip until the first real refresh replaces them.

## Refresh order (one run of the 12-hour routine)

1. Pull the latest PC grab from the `data` branch into `data/x.json`. If it is
   more than 6 hours old, keep the previous `stories.json` and set
   `meta.x_status` to `"waiting_for_pc"`.
2. `stories.json` from `x.json` (skipped when waiting for PC).
3. `youtube.json` for the stories (at most 8 searches) and `stats.json`.
4. `radar.json` and `ideas.json` from stories + youtube.
5. `devcorner.json`.
6. Append to `runlog.json`, write `meta.json`.

A step that fails leaves its previous file in place, so the page is never blank.

## Gap flag

`radar.json` stories carry `gap.flag`:

- `GAP`: big on X, little or no YouTube coverage. The video opportunity.
- `CLOSING`: YouTube is starting to cover it.
- `COVERED`: well covered on YouTube.

## Panel modules

Each panel is an ES module whose default export renders into a container the
shell gives it. The shell draws the frame, title and the
"BUILT BY WORKER n · PANEL" credit, so a panel only fills the body.

```js
// e.g. radar/radar-panel.js
export default function render(body, ctx) {
  const radar = ctx.data.radar;      // parsed data/radar.json (or null)
  body.append(ctx.ui.metric({ label: "Gaps", value: 3 }));
}
```

`ctx.data` holds every data file by name (missing or broken files are `null`).
`ctx.ui` has the shared building blocks from `shell/ui.js`:
`el`, `metric`, `chip`, `list`, `empty`, `timeAgo`, `fmt`.

The panel registry lives in `shell/panels.js`. A panel whose module is missing
or throws shows a placeholder instead of breaking the page.

## Pipeline scripts

The refresh (W5, `ops/refresh.py`) runs each step as its own script from the repo
root. Exit code 0 means the step wrote its file; anything else means it failed and
the previous file stays. Scripts use the Python standard library only.

| Step | Command | Reads | Writes |
|---|---|---|---|
| Stories | `python3 radar/stories.py` | `data/x.json` | `data/stories.json` |
| YouTube coverage | `python3 youtube/coverage.py` | `data/stories.json` | `data/youtube.json` |
| My Stats | `python3 youtube/stats.py` | – | `data/stats.json` |
| Gaps + ideas | `python3 radar/gaps.py` | `data/stories.json`, `data/youtube.json` | `data/radar.json`, `data/ideas.json` |
| Dev Corner | `python3 ops/devcorner.py` | GitHub releases | `data/devcorner.json` |

The PC grab (W2) commits `x/latest.json` (same shape as `data/x.json`) to the `data`
branch. The refresh reads it with `git fetch origin data` and copies it into `data/x.json`.

## Tests

Put unit tests in `<your folder>/tests/test_*.py` (stdlib `unittest`). CI runs them
for every PR, alongside schema validation, the secret scan and the page smoke test.
