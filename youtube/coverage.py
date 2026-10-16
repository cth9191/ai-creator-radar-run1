"""YouTube coverage for the top X stories -> data/youtube.json.

Run from the repo root: python3 youtube/coverage.py
Reads data/stories.json, spends at most 8 search.list calls (one per story, top stories
by engagement), then batches videos.list and channels.list for views and subscriber
counts. Exit 0 = file written; anything else = failed, previous file left in place.

RADAR_YT_MAX_SEARCHES can lower the search budget (never above 8).
"""
import argparse
import json
import os
import re
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ytapi  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MAX_SEARCHES = 8
SEARCH_RESULTS = 20          # maxResults per search.list
LOOKBACK = timedelta(days=2)  # publishedAfter = story first_seen minus this
TOP_VIDEOS = 5
RISING_MAX_SUBS = 50_000
RISING_MIN_VIEWS = 1_000
RISING_MIN_RATIO = 1.0
RISING_TOP = 5

# Words too generic to prove a video is about the story on an AI-news search.
STOPWORDS = {
    "a", "an", "and", "the", "of", "for", "to", "in", "on", "with", "by", "at", "is", "it",
    "its", "as", "from", "this", "that", "be", "are", "was", "or", "vs", "via", "into", "about",
    "new", "news", "update", "updates", "launch", "launches", "launched", "release", "released",
    "ai", "now", "just", "today", "out", "how", "what", "why", "who", "you", "your", "my",
    "sample",
}


def search_budget(env=None):
    env = os.environ if env is None else env
    raw = env.get("RADAR_YT_MAX_SEARCHES")
    if raw is None or str(raw).strip() == "":
        return MAX_SEARCHES
    try:
        n = int(str(raw).strip())
    except ValueError:
        return MAX_SEARCHES
    return max(0, min(MAX_SEARCHES, n))


def key_terms(story):
    """Lower-case terms from the story keywords and search query, minus filler words."""
    words = list(story.get("keywords") or []) + re.split(r"\s+", story.get("search_query") or "")
    terms = set()
    for w in words:
        w = re.sub(r"[^\w\-.+]", "", str(w).lower()).strip("-.")
        if not w:
            continue
        parts = [w] + ([p for p in re.split(r"[-.]", w) if p] if re.search(r"[-.]", w) else [])
        for p in parts:
            if len(p) >= 2 and p not in STOPWORDS:
                terms.add(p)
    return terms


def is_relevant(title, terms):
    t = (title or "").lower()
    for term in terms:
        if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", t):
            return True
        if "-" in term and re.search(r"(?<![a-z0-9])" + re.escape(term.replace("-", " ")) + r"(?![a-z0-9])", t):
            return True
    return False


def top_stories(stories, n):
    ranked = sorted(stories, key=lambda s: (-(s.get("engagement") or 0), s.get("id", "")))
    return [s for s in ranked if (s.get("search_query") or "").strip()][:n]


def search_story(client, story):
    try:
        after = ytapi.parse_iso(story["first_seen"]) - LOOKBACK
    except (KeyError, ValueError):
        after = ytapi.now_utc() - LOOKBACK
    res = client.get(
        "search",
        part="snippet",
        type="video",
        order="relevance",
        q=story["search_query"],
        publishedAfter=ytapi.iso(after),
        maxResults=SEARCH_RESULTS,
        relevanceLanguage="en",
    )
    out = []
    for item in res.get("items", []):
        vid = (item.get("id") or {}).get("videoId")
        if vid:
            out.append({"id": vid, "snippet": item.get("snippet") or {}})
    return out


def fetch_videos(client, ids):
    found = {}
    for batch in ytapi.chunks(ids, 50):
        res = client.get("videos", part="statistics,snippet", id=",".join(batch), maxResults=50)
        for item in res.get("items", []):
            found[item["id"]] = item
    return found


def fetch_channels(client, ids):
    found = {}
    for batch in ytapi.chunks(ids, 50):
        res = client.get("channels", part="statistics,snippet", id=",".join(batch), maxResults=50)
        for item in res.get("items", []):
            stats = item.get("statistics") or {}
            subs = None if stats.get("hiddenSubscriberCount") else ytapi.to_int(stats.get("subscriberCount"), None)
            found[item["id"]] = {"subs": subs, "title": (item.get("snippet") or {}).get("title")}
    return found


def video_record(vid, search_snip, video, channels):
    snip = (video or {}).get("snippet") or search_snip
    stats = (video or {}).get("statistics") or {}
    ch_id = snip.get("channelId") or search_snip.get("channelId") or ""
    rec = {
        "id": vid,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "title": snip.get("title") or search_snip.get("title") or "",
        "channel": snip.get("channelTitle") or search_snip.get("channelTitle") or "",
        "channel_id": ch_id,
        "published_at": ytapi.iso(ytapi.parse_iso(snip.get("publishedAt") or search_snip.get("publishedAt"))),
        "views": ytapi.to_int(stats.get("viewCount")),
    }
    subs = (channels.get(ch_id) or {}).get("subs")
    if subs is not None:
        rec["channel_subs"] = subs
    thumbs = snip.get("thumbnails") or {}
    thumb = ytapi.https(((thumbs.get("medium") or thumbs.get("default") or {}).get("url")))
    if thumb:
        rec["thumb"] = thumb
    return rec


def rising_channels(videos):
    """Small channels (< 50K subs) whose video is out-pulling their subscriber count."""
    best = {}
    for v in videos:
        subs = v.get("channel_subs")
        if not subs or subs >= RISING_MAX_SUBS or v["views"] < RISING_MIN_VIEWS:
            continue
        ratio = v["views"] / subs
        if ratio < RISING_MIN_RATIO:
            continue
        cur = best.get(v["channel_id"])
        if cur is None or ratio > cur["views_per_sub"]:
            best[v["channel_id"]] = {
                "channel": v["channel"],
                "channel_id": v["channel_id"],
                "channel_url": f"https://www.youtube.com/channel/{v['channel_id']}",
                "subs": subs,
                "video": v,
                "views_per_sub": round(ratio, 1),
            }
    ranked = sorted(best.values(), key=lambda r: (-r["views_per_sub"], -r["video"]["views"]))
    return ranked[:RISING_TOP]


def build(stories_doc, client, budget):
    stories = top_stories(stories_doc.get("stories") or [], budget)
    hits = {}  # story id -> [(video id, search snippet)]
    for story in stories:
        if client.calls.get("search", 0) >= budget:
            break
        terms = key_terms(story)
        results = search_story(client, story)
        hits[story["id"]] = [r for r in results if is_relevant(r["snippet"].get("title"), terms)]

    ids = list(dict.fromkeys(r["id"] for rs in hits.values() for r in rs))
    videos = fetch_videos(client, ids) if ids else {}
    ch_ids = list(dict.fromkeys(
        ((videos.get(i) or {}).get("snippet") or {}).get("channelId") for i in ids))
    channels = fetch_channels(client, [c for c in ch_ids if c]) if ch_ids else {}

    coverage, all_videos = {}, {}
    for story in stories:
        if story["id"] not in hits:
            continue
        recs = []
        for r in hits[story["id"]]:
            if r["id"] not in videos:
                continue  # removed or private since the search
            rec = video_record(r["id"], r["snippet"], videos[r["id"]], channels)
            recs.append(rec)
            all_videos[rec["id"]] = rec
        recs.sort(key=lambda v: -v["views"])
        coverage[story["id"]] = {
            "query": story["search_query"],
            "video_count": len(recs),
            "total_views": sum(v["views"] for v in recs),
            "videos": recs[:TOP_VIDEOS],
        }

    return {
        "sample": False,
        "generated_at": ytapi.iso(ytapi.now_utc()),
        "searches_used": client.calls.get("search", 0),
        "coverage": coverage,
        "rising": rising_channels(all_videos.values()),
    }


def main(argv=None, client=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stories", default=str(ROOT / "data" / "stories.json"))
    ap.add_argument("--out", default=str(ROOT / "data" / "youtube.json"))
    args = ap.parse_args(argv)

    try:
        stories_doc = json.loads(Path(args.stories).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return ytapi.fail(f"coverage: cannot read stories ({type(e).__name__}); youtube.json left as is")
    budget = search_budget()
    client = client or ytapi.Client()
    try:
        doc = build(stories_doc, client, budget)
    except ytapi.ApiError as e:
        return ytapi.fail(f"coverage: YouTube API failed, youtube.json left as is: {e}")
    except Exception as e:  # never leave a half-written file, never dump a traceback with URLs
        return ytapi.fail(f"coverage: unexpected {type(e).__name__}: {e}; youtube.json left as is")
    if doc["searches_used"] > MAX_SEARCHES:
        return ytapi.fail("coverage: search budget exceeded; youtube.json left as is")
    try:
        ytapi.write_json_atomic(args.out, doc)
    except OSError as e:
        return ytapi.fail(f"coverage: cannot write output ({type(e).__name__})")
    print(f"coverage: {len(doc['coverage'])} stories, {doc['searches_used']}/{MAX_SEARCHES} searches, "
          f"{len(doc['rising'])} rising channels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
