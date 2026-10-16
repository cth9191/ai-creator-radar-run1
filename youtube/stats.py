"""Channel stats for "Chase AI" -> data/stats.json.

Run from the repo root: python3 youtube/stats.py
Uses only cheap calls (channels.list, playlistItems.list, videos.list), never search.list.
The channel comes from youtube/config.json: channel_id if set, else channel_handle.
Exit 0 = file written; anything else = failed, previous file left in place.
"""
import argparse
import json
import statistics
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ytapi  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(__file__).resolve().parent / "config.json"
RECENT = 15                       # uploads considered for the median
LATEST = 5                        # uploads shown on the panel
MIN_AGE = timedelta(hours=48)     # younger videos are still climbing: left out of the median


class ConfigError(Exception):
    pass


def load_config(path):
    try:
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ConfigError("cannot read youtube/config.json") from None
    cid = (cfg.get("channel_id") or "").strip() or None
    handle = (cfg.get("channel_handle") or "").strip() or None
    if not cid and not handle:
        raise ConfigError("set youtube/config.json channel_handle (or channel_id)")
    if handle and not handle.startswith("@"):
        handle = "@" + handle
    return cid, handle


def get_channel(client, cid, handle):
    params = {"part": "snippet,statistics,contentDetails"}
    if cid:
        params["id"] = cid
    else:
        params["forHandle"] = handle
    res = client.get("channels", **params)
    items = res.get("items") or []
    if not items:
        raise ConfigError(f"channel {cid or handle} not found; check youtube/config.json")
    return items[0]


def median_views(videos, now):
    old = [v["views"] for v in videos if now - ytapi.parse_iso(v["published_at"]) >= MIN_AGE]
    return int(round(statistics.median(old))) if old else 0


def build(client, cid, handle, now=None):
    now = now or ytapi.now_utc()
    ch = get_channel(client, cid, handle)
    snip, stats = ch.get("snippet") or {}, ch.get("statistics") or {}
    uploads = ((ch.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
    channel = {
        "title": snip.get("title") or "Chase AI",
        "id": ch["id"],
        "url": f"https://www.youtube.com/{snip['customUrl']}" if (snip.get("customUrl") or "").startswith("@")
               else f"https://www.youtube.com/channel/{ch['id']}",
        "subs": 0 if stats.get("hiddenSubscriberCount") else ytapi.to_int(stats.get("subscriberCount")),
        "views": ytapi.to_int(stats.get("viewCount")),
        "video_count": ytapi.to_int(stats.get("videoCount")),
    }

    ids = []
    if uploads:
        res = client.get("playlistItems", part="contentDetails", playlistId=uploads, maxResults=RECENT)
        ids = [i["contentDetails"]["videoId"] for i in res.get("items", []) if (i.get("contentDetails") or {}).get("videoId")]
    videos = []
    if ids:
        res = client.get("videos", part="statistics,snippet", id=",".join(ids[:50]), maxResults=50)
        for item in res.get("items", []):
            vs = item.get("snippet") or {}
            if not vs.get("publishedAt"):
                continue
            videos.append({
                "id": item["id"],
                "title": vs.get("title") or "",
                "url": f"https://www.youtube.com/watch?v={item['id']}",
                "published_at": ytapi.iso(ytapi.parse_iso(vs["publishedAt"])),
                "views": ytapi.to_int((item.get("statistics") or {}).get("viewCount")),
            })
    videos.sort(key=lambda v: v["published_at"], reverse=True)
    med = median_views(videos, now)
    latest = [dict(v, vs_median=round(v["views"] / med, 2) if med else 0.0) for v in videos[:LATEST]]

    return {
        "sample": False,
        "generated_at": ytapi.iso(now),
        "channel": channel,
        "median_views": med,
        "latest": latest,
    }


def main(argv=None, client=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--out", default=str(ROOT / "data" / "stats.json"))
    args = ap.parse_args(argv)

    client = client or ytapi.Client()
    try:
        cid, handle = load_config(args.config)
        doc = build(client, cid, handle)
    except ConfigError as e:
        return ytapi.fail(f"stats: {e}; stats.json left as is")
    except ytapi.ApiError as e:
        return ytapi.fail(f"stats: YouTube API failed, stats.json left as is: {e}")
    except Exception as e:
        return ytapi.fail(f"stats: unexpected {type(e).__name__}: {e}; stats.json left as is")
    if client.calls.get("search"):
        return ytapi.fail("stats: must not use search.list; stats.json left as is")
    try:
        ytapi.write_json_atomic(args.out, doc)
    except OSError as e:
        return ytapi.fail(f"stats: cannot write output ({type(e).__name__})")
    print(f"stats: {doc['channel']['title']} {doc['channel']['subs']} subs, median {doc['median_views']} views")
    return 0


if __name__ == "__main__":
    sys.exit(main())
