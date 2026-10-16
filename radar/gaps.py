"""Join stories with YouTube coverage: gap scores, trails and video ideas.

Run from the repo root:  python3 radar/gaps.py
Reads data/stories.json and data/youtube.json, writes data/radar.json and data/ideas.json.
Standard library only. Exit 0 means both files were written; anything else means the step
failed and the previous files were left untouched (temp file + rename).

Gap score (0-100) = 100 * heat_factor * (1 - coverage)

  heat (0-1)      how hot the story is on X, on an absolute log scale:
                  0.7 * log10(engagement + 1) / log10(HEAT_ENGAGEMENT_FULL)
                + 0.3 * log10(velocity + 1)   / log10(HEAT_VELOCITY_FULL), each capped at 1
  heat_factor     0.35 + 0.65 * heat, so a lukewarm story with zero coverage still
                  registers, but only a hot one can reach the top of the scale
  coverage (0-1)  how well YouTube has caught up:
                  0.6 * (1 - exp(-relevant_videos / 4))           # 4 videos ~ 63% of this term
                + 0.4 * views_share * min(1, relevant_videos / 2)
                  views_share is 0 at 1K views, 1 at 1M, log scale in between.
                  A video published before the story's first X post is probably about
                  something older, so it counts 0.3 of a video.

Flags (shell/DATA.md): GAP when score >= 60, CLOSING when 25-59, COVERED below 25.

Unknown coverage: a story with no entry in youtube.json (the 8-search budget ran out, or
youtube.json is missing) is shown with video_count 0 and youtube.checked = false, and its
score is capped at UNKNOWN_CAP (75): it can still flag as GAP, but an unchecked story
never claims the top of the scale.
"""
import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stories import iso, parse_time, write_json_atomic  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

GAP_MIN = 60
CLOSING_MIN = 25
UNKNOWN_CAP = 75
HEAT_ENGAGEMENT_FULL = 50_000
HEAT_VELOCITY_FULL = 5_000
VIEWS_FULL = 1_000_000
VIEWS_FLOOR = 1_000
OLD_VIDEO_WEIGHT = 0.3
OLD_VIDEO_SLACK_HOURS = 1.0   # a video up to 1h before the first post still counts (clock skew)
MAX_IDEAS = 12

CODING_WORDS = {"claude code", "codex", "cursor", "copilot", "github copilot", "windsurf", "mcp",
                "agent sdk", "claude agent sdk", "sdk", "cli", "api", "coding", "agent", "agents",
                "plugin", "plugins", "hooks", "subagents", "ide", "devin", "replit", "lovable",
                "gemini cli", "codex cli", "vibe", "terminal"}
OPEN_WORDS = {"open weights", "open-weights", "weights", "open source", "open-source", "local",
              "locally", "ollama", "lm studio", "hugging face", "gguf"}
MONEY_WORDS = {"earnings", "funding", "acquisition", "lawsuit", "pricing", "valuation"}


def flag_for(score):
    if score >= GAP_MIN:
        return "GAP"
    if score >= CLOSING_MIN:
        return "CLOSING"
    return "COVERED"


def _log_share(value, full):
    return max(0.0, min(1.0, math.log10(max(0.0, value) + 1) / math.log10(full + 1)))


def heat(engagement, velocity):
    return 0.7 * _log_share(engagement, HEAT_ENGAGEMENT_FULL) + 0.3 * _log_share(velocity, HEAT_VELOCITY_FULL)


def _video_weight(v, first_seen):
    at = parse_time(v.get("published_at"))
    if first_seen is not None and at is not None and (first_seen - at).total_seconds() > OLD_VIDEO_SLACK_HOURS * 3600:
        return OLD_VIDEO_WEIGHT
    return 1.0


def relevant_coverage(cov, first_seen):
    """(video count, total views), discounting videos published well before the story began on X.

    The listed videos may be a sample of video_count, so their old/new mix is applied to the totals.
    """
    count = int(cov.get("video_count") or 0)
    videos = [v for v in (cov.get("videos") or []) if isinstance(v, dict)]
    listed_views = sum(int(v.get("views") or 0) for v in videos)
    views = int(cov.get("total_views") or listed_views)
    if not videos:
        return float(count), float(views)
    count_share = sum(_video_weight(v, first_seen) for v in videos) / len(videos)
    views_share = (sum(int(v.get("views") or 0) * _video_weight(v, first_seen) for v in videos) / listed_views
                   if listed_views else count_share)
    return count * count_share, views * views_share


def coverage(cov, first_seen):
    if not cov:
        return 0.0
    n, views = relevant_coverage(cov, first_seen)
    if n <= 0:
        return 0.0
    # views only count in proportion to how many relevant videos there are (full from 2 videos up)
    return 0.6 * (1 - math.exp(-n / 4.0)) + 0.4 * _views_share(views) * min(1.0, n / 2.0)


def _views_share(views):
    """0 at VIEWS_FLOOR or fewer, 1 at VIEWS_FULL, log scale in between."""
    if views <= VIEWS_FLOOR:
        return 0.0
    return min(1.0, math.log10(views / VIEWS_FLOOR) / math.log10(VIEWS_FULL / VIEWS_FLOOR))


def gap_score(story, cov):
    """Return (score 0-100 rounded to int, heat, coverage, checked)."""
    first_seen = parse_time(story.get("first_seen"))
    h = heat(story.get("engagement") or 0, story.get("velocity") or 0)
    checked = cov is not None
    c = coverage(cov, first_seen) if checked else 0.0
    score = 100.0 * (0.35 + 0.65 * h) * (1.0 - c)
    if not checked:
        score = min(score, UNKNOWN_CAP)
    return int(round(max(0.0, min(100.0, score)))), round(h, 3), round(c, 3), checked


def _short(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}".rstrip("0").rstrip(".") + "M"
    if n >= 10_000:
        return f"{round(n / 1000)}K"
    if n >= 1000:
        return f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "K"
    return str(n)


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def build_trail(story, cov):
    trail = []
    first = story.get("first_post") or {}
    first_at = parse_time(first.get("created_at")) or parse_time(story.get("first_seen"))
    top = [p for p in story.get("top_posts") or [] if isinstance(p, dict)]
    if first_at:
        item = {"at": iso(first_at), "platform": "x",
                "label": f"First X post · @{first['handle']}" if first.get("handle") else "First X post"}
        url = first.get("url") or next((p["url"] for p in top if p.get("created_at") == story.get("first_seen")), None)
        if isinstance(url, str) and url.startswith("https://"):
            item["url"] = url
        trail.append(item)
    first_id = first.get("id")
    for i, p in enumerate(top[:2]):  # the peak post(s): highest engagement
        at = parse_time(p.get("created_at"))
        if at is None or p.get("id") == first_id or (not first_id and first_at and at == first_at):
            continue
        eng = (p.get("likes") or 0) + 2 * (p.get("reposts") or 0) + (p.get("replies") or 0) + 2 * (p.get("quotes") or 0)
        handle = (p.get("author") or {}).get("handle", "")
        item = {"at": iso(at), "platform": "x",
                "label": f"{'Peak' if i == 0 else 'Big'} X post · @{handle} · {_short(eng)} engagement"}
        if str(p.get("url", "")).startswith("https://"):
            item["url"] = p["url"]
        trail.append(item)
    for v in (cov or {}).get("videos") or []:
        at = parse_time(v.get("published_at")) if isinstance(v, dict) else None
        if at is None:
            continue
        item = {"at": iso(at), "platform": "youtube",
                "label": f"{v.get('channel', 'YouTube')} · {_short(v.get('views'))} views"}
        if str(v.get("url", "")).startswith("https://"):
            item["url"] = v["url"]
        trail.append(item)
    trail.sort(key=lambda t: (t["at"], 0 if t["platform"] == "x" else 1, t["label"]))
    return trail


def _slim_post(p):
    out = {k: p[k] for k in ("id", "url", "text", "created_at", "likes", "reposts", "replies", "quotes")
           if k in p}
    a = p.get("author") or {}
    out["author"] = {k: a[k] for k in ("handle", "name", "followers", "verified") if k in a} or {"handle": ""}
    return out


def _slim_video(v):
    return {k: v[k] for k in ("id", "url", "title", "channel", "channel_subs", "published_at", "views", "thumb")
            if k in v}


def radar_story(story, cov):
    score, h, c, checked = gap_score(story, cov)
    flag = flag_for(score)
    videos = sorted((v for v in (cov or {}).get("videos") or [] if isinstance(v, dict)),
                    key=lambda v: (v.get("published_at") or "", v.get("id") or ""))
    top_posts = [p for p in story.get("top_posts") or [] if isinstance(p, dict)]
    x = {"post_count": int(story.get("post_count") or 0),
         "engagement": int(story.get("engagement") or 0),
         "first_seen": story["first_seen"],
         "velocity": float(story.get("velocity") or 0),
         "top_posts": [_slim_post(p) for p in top_posts[:3]]}
    if top_posts and str(top_posts[0].get("url", "")).startswith("https://"):
        x["top_url"] = top_posts[0]["url"]
    yt = {"video_count": int((cov or {}).get("video_count") or 0),
          "total_views": int((cov or {}).get("total_views") or sum(int(v.get("views") or 0) for v in videos)),
          "first_video_at": iso(parse_time(videos[0]["published_at"])) if videos and parse_time(videos[0].get("published_at")) else None,
          "checked": checked,
          "videos": [_slim_video(v) for v in sorted(videos, key=lambda v: -(v.get("views") or 0))[:5]]}
    if cov and cov.get("query"):
        yt["query"] = cov["query"]
    if videos:
        best = max(videos, key=lambda v: (v.get("views") or 0))
        if str(best.get("url", "")).startswith("https://"):
            yt["top_url"] = best["url"]
    out = {"id": story["id"], "title": story.get("title") or story["id"],
           "summary": story.get("summary") or "",
           "keywords": list(story.get("keywords") or []),
           "search_query": story.get("search_query") or "",
           "x": x, "youtube": yt,
           "gap": {"score": score, "flag": flag, "heat": h, "coverage": c, "capped": not checked and score >= UNKNOWN_CAP},
           "trail": build_trail(story, cov)}
    return out


# ---------------------------------------------------------------- ideas

def _has(text, words):
    return any(re.search(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", text) for w in words)


def _kind(story):
    """Pick the template family from what the story is about (first match wins):
    two versioned names -> versus; open weights -> run locally; a coding tool as the main
    subject -> Claude Code angle; ticker or money words -> explainer; a versioned model ->
    hands-on test; anything else -> explainer."""
    kws = [k for k in story.get("keywords") or []]
    title = (story.get("title") or "").lower()
    lead = (kws[0] if kws else title).lower()
    low = " ".join([title] + [k.lower() for k in kws])
    versioned = [k for k in kws if any(ch.isdigit() for ch in k) and not k.startswith("$")]
    if len(versioned) >= 2 and not _redundant_names(versioned[0], versioned[1]):
        return "versus", versioned[:2]
    if _has(low, OPEN_WORDS):
        return "open", versioned[:1]
    if _has(lead, CODING_WORDS):
        return "coding", versioned[:1]
    if any(k.startswith("$") for k in kws) or _has(low, MONEY_WORDS):
        return "money", []
    if versioned:
        return "model", versioned[:1]
    if _has(low, CODING_WORDS):
        return "coding", []
    return "explain", []


def _redundant_names(a, b):
    a, b = a.lower(), b.lower()
    return a in b or b in a


def angle_for(story):
    """One concrete video angle, chosen deterministically from the story's keywords."""
    kind, names = _kind(story)
    kws = story.get("keywords") or []
    subject = names[0] if names else (kws[0] if kws else story.get("title", "This"))
    title = story.get("title") or subject
    if kind == "versus":
        return f"{names[0]} vs {names[1]}: which one should you actually use?"
    if kind == "open":
        return f"Run {subject} locally: full setup and honest first test"
    if kind == "coding":
        if subject.lower().startswith("claude code"):
            return f"{title}: what changed and how I'm using it"
        return f"What {subject} means for Claude Code users"
    if kind == "money":
        return f"{title} explained in 8 minutes (and why creators should care)"
    if kind == "model":
        return f"I tested {subject} so you don't have to"
    return f"{title} explained in 8 minutes"


def why_for(story, r):
    x, yt = r["x"], r["youtube"]
    parts = [_plural(x["post_count"], "X post"), f"{_short(x['engagement'])} engagement"]
    if not yt.get("checked"):
        parts.append("YouTube not checked yet")
    else:
        vids = _plural(yt["video_count"], "YouTube video")
        if yt["video_count"]:
            vids += f" ({_short(yt.get('total_views'))} views)"
        parts.append(vids)
    return ", ".join(parts)


def build(stories_doc, youtube_doc):
    stories = [s for s in (stories_doc or {}).get("stories") or []
               if isinstance(s, dict) and s.get("id") and s.get("first_seen")]
    coverage_map = (youtube_doc or {}).get("coverage") or {}
    radar = [radar_story(s, coverage_map.get(s["id"]) if isinstance(coverage_map.get(s["id"]), dict) else None)
             for s in stories]
    radar.sort(key=lambda r: (-r["gap"]["score"], -r["x"]["engagement"], r["id"]))
    by_id = {s["id"]: s for s in stories}
    ideas = []
    for r in radar[:MAX_IDEAS]:
        s = by_id[r["id"]]
        ideas.append({"rank": len(ideas) + 1, "story_id": r["id"], "title": r["title"],
                      "angle": angle_for(s), "why": why_for(s, r),
                      "gap_score": r["gap"]["score"], "flag": r["gap"]["flag"]})
    return radar, ideas


def _load(path, required):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        if required:
            raise ValueError(f"cannot read {path}: {e}")
        print(f"gaps: {path} unreadable ({e}); treating YouTube coverage as unknown", file=sys.stderr)
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stories", default=str(DATA / "stories.json"))
    ap.add_argument("--youtube", default=str(DATA / "youtube.json"))
    ap.add_argument("--radar", default=str(DATA / "radar.json"))
    ap.add_argument("--ideas", default=str(DATA / "ideas.json"))
    args = ap.parse_args(argv)
    try:
        stories_doc = _load(args.stories, required=True)
        if not isinstance(stories_doc, dict) or not isinstance(stories_doc.get("stories"), list):
            raise ValueError("stories.json has no stories list")
        youtube_doc = _load(args.youtube, required=False)
        radar, ideas = build(stories_doc, youtube_doc)
        now = iso(datetime.now(timezone.utc))
        sample = bool(stories_doc.get("sample") or (youtube_doc or {}).get("sample"))
        head = {"sample": True} if sample else {}
        radar_doc = {**head, "generated_at": now, "stories": radar}
        ideas_doc = {**head, "generated_at": now, "ideas": ideas}
        write_json_atomic(args.radar, radar_doc)
        write_json_atomic(args.ideas, ideas_doc)
    except Exception as e:
        print(f"gaps: FAILED: {e}", file=sys.stderr)
        return 1
    flags = [r["gap"]["flag"] for r in radar]
    print(f"gaps: {len(radar)} stories ({flags.count('GAP')} GAP, {flags.count('CLOSING')} CLOSING, "
          f"{flags.count('COVERED')} COVERED), {len(ideas)} ideas -> {args.radar}, {args.ideas}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
