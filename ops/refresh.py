"""One run of the 12-hour refresh. Python standard library only.

    python3 ops/refresh.py                 # normal run (fetches the PC grab from the data branch)
    python3 ops/refresh.py --no-fetch      # use whatever origin/data is already known locally
    python3 ops/refresh.py --now 2026-10-16T11:07:00Z   # pretend it is this time (testing)
    python3 ops/refresh.py --record-fail "validation failed"   # log a failed run, touch nothing else

Order (see shell/DATA.md "Refresh order"):
  1. X        copy x/latest.json from the data branch into data/x.json if it is fresh
  2. Stories  python3 radar/stories.py        (only when X is fresh)
  3. YouTube  python3 youtube/coverage.py     (always, so gaps can close while X is stale)
     Stats    python3 youtube/stats.py
  4. Gaps     python3 radar/gaps.py
  5. Dev      python3 ops/devcorner.py
  6. Append a run to data/runlog.json and write data/meta.json

Every step runs on a snapshot of data/. If the step exits non-zero, times out, or leaves a
file that is not valid JSON or does not match its schema, data/ is put back exactly as it
was before that step. The page is never left blank or half-written.

This script never commits or pushes; the routine (ops/ROUTINE.md) does that.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]

STALE_HOURS = 6                      # a PC grab older than this is "waiting_for_pc"
MAX_RUNS = 60                        # runlog keeps the newest 60 runs
CHICAGO = ZoneInfo("America/Chicago")
REFRESH_TIMES = ((6, 7), (18, 7))    # routine fires at 6:07 AM and 6:07 PM Chicago time
DATA_BRANCH = "data"
GRAB_PATH = "x/latest.json"
GIT_TIMEOUT = 90
TAIL_LINES = 6


@dataclass
class Step:
    label: str          # chip label in the run log
    script: str         # path from repo root
    timeout: int        # seconds
    outputs: tuple      # data/<name>.json files it is expected to write


STEPS = {
    "Stories": Step("Stories", "radar/stories.py", 300, ("stories",)),
    "YouTube": Step("YouTube", "youtube/coverage.py", 600, ("youtube",)),
    "Stats": Step("Stats", "youtube/stats.py", 300, ("stats",)),
    "Gaps": Step("Gaps", "radar/gaps.py", 300, ("radar", "ideas")),
    "Dev": Step("Dev", "ops/devcorner.py", 120, ("devcorner",)),
}
CHIP_ORDER = ("X", "Stories", "YouTube", "Stats", "Gaps", "Dev")


# ---------------------------------------------------------------- time helpers

def parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def next_refresh_at(now: datetime) -> datetime:
    """Next 06:07 or 18:07 America/Chicago strictly after `now`, in UTC (DST-aware)."""
    local = now.astimezone(CHICAGO)
    for day in range(3):
        d = (local + timedelta(days=day)).date()
        for hour, minute in REFRESH_TIMES:
            cand = datetime(d.year, d.month, d.day, hour, minute, tzinfo=CHICAGO)
            if cand > local:
                return cand.astimezone(timezone.utc)
    raise RuntimeError("no refresh time found")  # unreachable


def ago(hours: float) -> str:
    if hours < 1:
        return f"{max(0, round(hours * 60))}m ago"
    if hours < 48:
        return f"{round(hours)}h ago"
    return f"{round(hours / 24)}d ago"


# ---------------------------------------------------------------- files + validation

def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path: Path, doc) -> None:
    """Atomic write: temp file in the same folder, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def validate(root: Path, name: str, doc) -> list:
    """Errors for data/<name>.json content. Uses jsonschema when installed, else a light key check."""
    schema_path = root / "shell" / "schema" / f"{name}.schema.json"
    schema = read_json(schema_path)
    if schema is None:
        return [f"no schema for data/{name}.json"]
    if not isinstance(doc, dict):
        return [f"data/{name}.json is not a JSON object"]
    try:
        from jsonschema import Draft202012Validator, FormatChecker  # type: ignore
    except ImportError:
        errors = [f"data/{name}.json missing '{k}'" for k in schema.get("required", []) if k not in doc]
        for key, spec in schema.get("properties", {}).items():
            if key in doc and spec.get("type") == "array" and not isinstance(doc[key], list):
                errors.append(f"data/{name}.json '{key}' is not a list")
        return errors
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [f"data/{name}.json {'/'.join(map(str, e.path)) or '(root)'}: {e.message}"
            for e in validator.iter_errors(doc)]


def snapshot(data_dir: Path) -> dict:
    return {p.name: p.read_bytes() for p in sorted(data_dir.glob("*.json"))}


def changed_files(data_dir: Path, before: dict) -> list:
    now = snapshot(data_dir)
    return sorted(n for n, b in now.items() if before.get(n) != b) + sorted(n for n in before if n not in now)


def restore(data_dir: Path, before: dict) -> None:
    for p in data_dir.glob("*.json"):
        if p.name not in before:
            p.unlink()
    for name, blob in before.items():
        p = data_dir / name
        if not p.exists() or p.read_bytes() != blob:
            tmp = p.with_name(f".{name}.restore")
            tmp.write_bytes(blob)
            os.replace(tmp, p)
    for p in data_dir.glob(".*.tmp"):  # half-written temp files from a killed step
        try:
            p.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- output hygiene

_SECRET_ENV = re.compile(r"KEY|TOKEN|SECRET|COOKIE|PASSWORD|PASS|AUTH|CREDENTIAL", re.I)


def redact(text: str) -> str:
    """Hide any secret-looking environment value that a script may have printed."""
    for k, v in os.environ.items():
        if v and len(v) >= 8 and _SECRET_ENV.search(k):
            text = text.replace(v, "[redacted]")
    return text


def tail(text: str, n: int = TAIL_LINES) -> str:
    lines = [l for l in (text or "").strip().splitlines() if l.strip()]
    return "\n".join("    " + l[:200] for l in lines[-n:])


# ---------------------------------------------------------------- runners (patched in tests)

def run_script(root: Path, script: str, timeout: int):
    """Run a step script from the repo root. Returns (returncode, combined output)."""
    try:
        p = subprocess.run([sys.executable, script], cwd=root, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        return 124, out + f"\ntimed out after {timeout}s"
    except OSError as e:
        return 127, str(e)


def run_git(root: Path, args: list, timeout: int = GIT_TIMEOUT):
    """Run git. Returns (returncode, stdout, stderr)."""
    try:
        p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"git {' '.join(args)} timed out"
    except OSError as e:
        return 127, "", str(e)


# ---------------------------------------------------------------- the run

@dataclass
class Outcome:
    chips: dict = field(default_factory=dict)       # label -> bool
    failed: list = field(default_factory=list)      # labels that failed (not skipped)
    x_status: str = "waiting_for_pc"
    x_grabbed_at: str | None = None
    x_note: str = ""


def check_grab(doc) -> str | None:
    """Basic shape check of a PC grab. Returns an error string or None."""
    if not isinstance(doc, dict):
        return "grab is not a JSON object"
    if not isinstance(doc.get("posts"), list):
        return "grab has no posts list"
    try:
        parse_iso(doc.get("grabbed_at"))
    except (TypeError, ValueError):
        return "grab has no valid grabbed_at"
    return None


def is_fresh(grabbed_at: datetime, now: datetime, stale_hours: float = STALE_HOURS) -> bool:
    return now - grabbed_at <= timedelta(hours=stale_hours)


def step_x(root: Path, now: datetime, fetch: bool, git=run_git) -> Outcome:
    out = Outcome()
    data_dir = root / "data"
    prev = read_json(data_dir / "x.json")
    if isinstance(prev, dict) and not prev.get("sample") and prev.get("grabbed_at"):
        out.x_grabbed_at = prev["grabbed_at"]

    if fetch:
        code, _, err = 1, "", ""
        for wait in (0, 2, 4):
            time.sleep(wait)
            code, _, err = git(root, ["fetch", "--quiet", "origin", DATA_BRANCH])
            if code == 0:
                break
        if code != 0:
            print(f"  x: git fetch origin {DATA_BRANCH} failed: {redact(err.strip())[:200]}")
    code, text, err = git(root, ["show", f"origin/{DATA_BRANCH}:{GRAB_PATH}"])
    if code != 0:
        out.x_note = "X waiting for PC (no grab on the data branch yet)"
        print(f"  x: no {GRAB_PATH} on origin/{DATA_BRANCH}")
        return out
    try:
        doc = json.loads(text)
    except ValueError:
        doc = None
    problem = check_grab(doc)
    if problem is None:
        problem = next(iter(validate(root, "x", doc)), None)
    if problem:
        out.x_note = "X waiting for PC (latest grab unreadable)"
        print(f"  x: {problem[:200]}")
        return out

    grabbed = parse_iso(doc["grabbed_at"])
    if out.x_grabbed_at is None or grabbed >= parse_iso(out.x_grabbed_at):
        out.x_grabbed_at = iso(grabbed)
    age_h = (now - grabbed).total_seconds() / 3600
    if not is_fresh(grabbed, now):
        out.x_note = f"X waiting for PC (last grab {ago(age_h)})"
        print(f"  x: grab is {age_h:.1f}h old (limit {STALE_HOURS}h), keeping previous X and stories")
        return out

    write_json(data_dir / "x.json", doc)
    out.x_status = "fresh"
    out.x_grabbed_at = iso(grabbed)
    out.x_note = f"X fresh ({len(doc['posts'])} posts, grabbed {ago(age_h)})"
    print(f"  x: fresh grab, {len(doc['posts'])} posts, {age_h:.1f}h old")
    return out


def run_step(root: Path, step: Step, runner=run_script) -> bool:
    """Run one step on a snapshot of data/. Restores data/ unless it succeeded with valid files."""
    data_dir = root / "data"
    before = snapshot(data_dir)
    if not (root / step.script).is_file():
        print(f"  {step.label.lower()}: {step.script} not found, keeping previous file")
        return False
    t0 = time.monotonic()
    try:
        code, output = runner(root, step.script, step.timeout)
    except Exception as e:  # a runner bug must not kill the whole refresh
        code, output = 1, f"{type(e).__name__}: {e}"
    secs = time.monotonic() - t0
    problems = []
    if code == 0:
        for name in changed_files(data_dir, before):
            stem = name.removesuffix(".json")
            doc = read_json(data_dir / name)
            if doc is None:
                problems.append(f"data/{name} missing or not valid JSON")
            else:
                problems.extend(validate(root, stem, doc)[:3])
    ok = code == 0 and not problems
    print(f"  {step.label.lower()}: {'ok' if ok else 'FAILED'} (exit {code}, {secs:.1f}s)")
    if output.strip():
        print(tail(redact(output)))
    for p in problems[:3]:
        print(f"    invalid: {p[:200]}")
    if not ok:
        restore(data_dir, before)
        print(f"    restored previous data/ files")
    return ok


def gap_counts(root: Path):
    radar = read_json(root / "data" / "radar.json")
    stories = radar.get("stories", []) if isinstance(radar, dict) else []
    flags = [((s or {}).get("gap") or {}).get("flag") for s in stories if isinstance(s, dict)]
    return flags.count("GAP"), flags.count("CLOSING")


def run_status(chips: dict) -> str:
    oks = list(chips.values())
    if oks and all(oks):
        return "ok"
    if not any(oks):
        return "fail"
    return "partial"


def build_note(root: Path, out: Outcome) -> str:
    parts = [out.x_note] if out.x_note else []
    c = out.chips
    if c.get("Stories"):
        stories = read_json(root / "data" / "stories.json") or {}
        parts.append(f"{len(stories.get('stories', []))} stories")
    if c.get("YouTube"):
        parts.append("YouTube refreshed")
    if c.get("Gaps"):
        gaps, closing = gap_counts(root)
        parts.append(f"{gaps} gap{'s' if gaps != 1 else ''} open, {closing} closing")
    if out.failed:
        parts.append("failed: " + ", ".join(out.failed) + " (kept previous)")
    return "; ".join(parts) or "Nothing ran"


def append_run(root: Path, run: dict) -> None:
    path = root / "data" / "runlog.json"
    log = read_json(path)
    runs = log.get("runs", []) if isinstance(log, dict) and not log.get("sample") else []
    runs = [r for r in runs if isinstance(r, dict) and r.get("at")]
    runs.insert(0, run)
    runs.sort(key=lambda r: parse_iso(r["at"]), reverse=True)
    write_json(path, {"sample": False, "runs": runs[:MAX_RUNS]})


def write_meta(root: Path, now: datetime, x_status: str, x_grabbed_at, updated_at=None) -> dict:
    meta = {
        "sample": False,
        "updated_at": updated_at or iso(now),
        "x_status": x_status,
        "x_grabbed_at": x_grabbed_at,
        "next_refresh_at": iso(next_refresh_at(now)),
    }
    write_json(root / "data" / "meta.json", meta)
    return meta


def refresh(root: Path = ROOT, now: datetime | None = None, fetch: bool = True,
            runner=run_script, git=run_git) -> dict:
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    print(f"Refresh {iso(now)}")
    data_dir = root / "data"

    before_x = snapshot(data_dir)
    try:
        out = step_x(root, now, fetch, git)
    except Exception as e:  # never crash on the X step
        restore(data_dir, before_x)
        out = Outcome(x_note=f"X waiting for PC (error: {type(e).__name__})")
        print(f"  x: error {type(e).__name__}: {e}")
    fresh = out.x_status == "fresh"
    out.chips["X"] = fresh

    for label in ("Stories", "YouTube", "Stats", "Gaps", "Dev"):
        if label == "Stories" and not fresh:
            out.chips[label] = False      # skipped: previous stories stay on the page
            print("  stories: skipped (X waiting for PC), keeping previous stories")
            continue
        ok = run_step(root, STEPS[label], runner)
        out.chips[label] = ok
        if not ok:
            out.failed.append(label)

    status = run_status(out.chips)
    run = {
        "at": iso(now),
        "status": status,
        "chips": [{"label": k, "ok": out.chips[k]} for k in CHIP_ORDER],
        "note": build_note(root, out),
    }
    append_run(root, run)
    write_meta(root, now, out.x_status, out.x_grabbed_at)
    print(f"Refresh {iso(now)}: {status} · {run['note']}")
    return run


def record_fail(root: Path, now: datetime, note: str) -> dict:
    """Log a failed run (e.g. the routine's validation failed and it restored data/ from HEAD)."""
    now = now.replace(microsecond=0)
    prev = read_json(root / "data" / "meta.json") or {}
    run = {"at": iso(now), "status": "fail",
           "chips": [{"label": k, "ok": False} for k in CHIP_ORDER],
           "note": (note or "Refresh failed; previous data kept")[:300]}
    append_run(root, run)
    # Keep the last good updated_at so the header does not claim a fresh refresh.
    write_meta(root, now, prev.get("x_status", "waiting_for_pc"), prev.get("x_grabbed_at"),
               updated_at=prev.get("updated_at") or iso(now))
    print(f"Refresh {iso(now)}: fail · {run['note']}")
    return run


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="One run of the AI Creator Radar refresh.")
    ap.add_argument("--no-fetch", action="store_true", help="skip git fetch of the data branch")
    ap.add_argument("--now", help="ISO time to use instead of the clock (testing)")
    ap.add_argument("--record-fail", metavar="NOTE", help="only append a failed run with this note")
    args = ap.parse_args(argv)
    now = parse_iso(args.now) if args.now else datetime.now(timezone.utc)
    if args.record_fail is not None:
        record_fail(ROOT, now, args.record_fail)
        return 0
    run = refresh(ROOT, now, fetch=not args.no_fetch)
    return 1 if run["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
