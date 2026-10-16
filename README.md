# AI Creator Radar

A live dashboard for an AI YouTube creator: what's breaking on X right now, and whether
it has hit YouTube yet. A story that's big on X with little or no YouTube coverage is a
**GAP**, which is a video opportunity.

Built in public for the Chase AI YouTube channel by a team of Claude workers.
All data shown is public.

## How it works

```
Chase's PC (4:30 AM / PM)          Cloud routine (6:07 AM / PM)             GitHub Pages
read-only X search  ── push ──▶  data branch ──▶ group stories, check      ──▶ static page
                                                  YouTube, Dev Corner,          reads data/*.json
                                                  stats, ideas, run log
```

- **X** is read only from Chase's own PC, through the desktop app's browser pane where he's
  logged in. Read-only: no posting, liking or following, and no cookies or tokens are read or saved.
- **YouTube** comes from the YouTube Data API, called from the cloud. The key is attached by the
  network, never stored here. At most 8 searches per refresh.
- If the PC's latest X grab is stale, the page says **waiting for PC**, keeps the last stories and
  still refreshes YouTube, so gaps can close. The page is never blank.

## Who owns what

One folder per worker, so nobody edits the same files. One PR per worker.

| Worker | Folder | Builds |
|---|---|---|
| 1 | `shell/`, root files, `data/` samples | Page shell, look, data contract, CI |
| 2 | `x/` | PC X grab (read-only), X Breaking panel, local scheduled task prompt |
| 3 | `radar/` | Story grouping, gap scoring, Story Radar, Video Ideas |
| 4 | `youtube/` | YouTube coverage, rising small channels, My Stats |
| 5 | `ops/` | Refresh pipeline, waiting-for-PC fallback, Run Log, Claude Dev Corner |

The data contract every worker codes against is in [`shell/DATA.md`](shell/DATA.md).

## Run it locally

```
python3 -m http.server 8000      # then open http://localhost:8000
python3 shell/tools/validate.py  # data matches schema
python3 shell/tools/no_secrets.py
npm install && npx playwright install chromium && npm test
```
