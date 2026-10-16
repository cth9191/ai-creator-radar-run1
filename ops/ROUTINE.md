# The 12-hour refresh routine

A Claude Code cloud session with this repo runs the prompt below every 12 hours, at about
6:07 AM and 6:07 PM America/Chicago (the PC grabs X at about 4:30, so the grab is ~1.5h old).
Everything it does is in scripts; the prompt only runs them, checks them and commits.

## Prompt (paste exactly)

```text
You are the refresh routine for the public AI Creator Radar dashboard (repo cth9191/ai-creator-radar).
Work only in that repo, on the main branch. Do not edit any script, page or workflow file; only
data/*.json may change, and only through the commands below. This repo is public: never print
environment variables, never write or commit keys, tokens or cookies, and never add an API key
or Authorization header to any request (the YouTube key is attached by the network). Do not run
any YouTube search yourself; youtube/coverage.py does at most 8 per run.

1. Sync:
   git checkout main && git pull --ff-only origin main

2. Refresh (runs every step, keeps the previous file for any step that fails, writes the run log and meta):
   python3 ops/refresh.py
   Keep the LAST line it prints. It looks like
   "Refresh 2026-10-16T11:07:00Z: partial · X waiting for PC (last grab 14h ago); YouTube refreshed; ..."
   Exit code 1 only means every step failed; still continue to step 3.

3. Check:
   python3 -c "import jsonschema" 2>/dev/null || pip install -q "jsonschema[format]==4.23.0"
   python3 shell/tools/validate.py
   python3 shell/tools/no_secrets.py

4a. If BOTH checks pass, commit only data files:
   git add data/*.json
   git commit -m "<the last line from step 2>"
   (skip the commit if git says there is nothing to commit)

4b. If EITHER check fails, throw away this run's data and log the failure instead:
   git checkout HEAD -- data/
   git clean -fdq -- data/
   python3 ops/refresh.py --record-fail "Checks failed: <first FAIL line, max 120 chars, no secrets>; previous data kept"
   python3 shell/tools/validate.py && python3 shell/tools/no_secrets.py
   git add data/runlog.json data/meta.json
   git commit -m "Refresh <UTC time, e.g. 2026-10-16T11:07:00Z>: fail · checks failed, previous data kept"
   If the checks still fail here, commit nothing and report.

5. Push:
   git push origin main
   On a network error retry after 2s, 4s, 8s, 16s. If the push is rejected because main moved,
   run "git pull --rebase origin main" and push again (same retries). Never force-push.

6. Reply with one line: the summary from step 2 (or the failure line), plus "pushed" or "not pushed".
```

## Notes

- **Order and fallbacks** are in `ops/refresh.py` and match `shell/DATA.md`. X counts as fresh
  when `x/latest.json` on the `data` branch was grabbed at most `STALE_HOURS = 6` hours ago.
  Otherwise the page shows "waiting for PC", keeps the last `x.json` and `stories.json`, and still
  refreshes YouTube, stats, gaps and the Dev Corner so gaps can close.
- **A failed step never blanks the page.** Each step runs on a snapshot of `data/`; on a non-zero
  exit, a timeout or an output that does not match its schema, `data/` is restored to the snapshot.
- **Run log** keeps the newest 60 runs. `status` is `ok` when every chip is green, `fail` when none
  is, `partial` otherwise (a run waiting for the PC is at best `partial`).
- **Dev Corner network.** `ops/devcorner.py` tries `api.github.com/repos/anthropics/claude-code/releases`
  first. Cloud sessions are usually scoped to their own repo on api.github.com, so it falls back to
  the public `CHANGELOG.md` on `raw.githubusercontent.com` plus publish times from
  `registry.npmjs.org`. Both hosts must be reachable from the routine's network.
- **Schedule and daylight saving.** `meta.next_refresh_at` assumes 6:07 AM/PM Chicago. A trigger
  set in UTC (`7 11,23 * * *`) matches that during CDT; during CST (from Nov 1 2026) it fires at
  5:07 AM/PM Chicago, so either move the trigger to `7 0,12 * * *` UTC for the winter or change
  `REFRESH_TIMES` in `ops/refresh.py`. The page only uses it for the "Next" chip.
- **Local test:** `python3 ops/refresh.py --no-fetch` (does not touch git). Afterwards
  `git checkout -- data/` to throw the result away.
- **Unit tests:** `python3 -m unittest discover -s ops/tests -t .`
- Story titles and angles are left to `radar/` scripts; the routine does not rewrite them, so a run
  is the same whether a person or the routine starts it.
