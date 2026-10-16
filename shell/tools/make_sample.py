"""Write placeholder data/*.json so the page is never blank before the first refresh.

Every file is marked "sample": true. Run: python3 shell/tools/make_sample.py
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
NOW = datetime(2026, 10, 16, 11, 7, tzinfo=timezone.utc)


def ts(hours_ago=0.0):
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


STORIES = [
    ("sample-model-launch", "Sample: new frontier model launch", 9.5, 41, 18400, 0, 92),
    ("sample-agent-sdk", "Sample: agent SDK update", 7.0, 22, 9100, 2, 61),
    ("sample-open-weights", "Sample: open-weights coding model", 11.0, 30, 12800, 6, 34),
    ("sample-voice-mode", "Sample: real-time voice API", 5.5, 12, 4300, 14, 9),
]


def post(i, story_id, hours):
    return {
        "id": f"{story_id}-{i}",
        "url": f"https://x.com/example/status/{1000 + i}",
        "author": {"handle": "example", "name": "Sample Author", "followers": 12000, "verified": False},
        "text": "Sample post. Real posts arrive with the first PC grab.",
        "created_at": ts(hours),
        "likes": 900 - i * 100, "reposts": 120 - i * 10, "replies": 40, "quotes": 12, "views": 50000,
        "query": "sample",
    }


def video(story_id, i, hours, views):
    return {
        "id": f"{story_id}-v{i}", "url": f"https://www.youtube.com/watch?v=sample{i}",
        "title": "Sample video", "channel": "Sample Channel", "channel_id": "UCsample",
        "channel_subs": 8000, "published_at": ts(hours), "views": views,
    }


def main():
    DATA.mkdir(exist_ok=True)
    posts, stories, coverage, radar, ideas = [], [], {}, [], []
    for sid, title, age, count, eng, vids, gap in STORIES:
        top = [post(i, sid, age - i) for i in range(2)]
        posts += top
        stories.append({
            "id": sid, "title": title, "summary": "Placeholder story until the first real refresh.",
            "keywords": title.lower().split()[1:4], "search_query": title.split(": ")[1],
            "first_seen": ts(age), "post_ids": [p["id"] for p in top], "post_count": count,
            "engagement": eng, "velocity": round(eng / age, 1), "top_posts": top,
        })
        vs = [video(sid, i, age - 3 - i, 4000 * (i + 1)) for i in range(min(vids, 3))]
        coverage[sid] = {"query": title.split(": ")[1], "video_count": vids,
                         "total_views": sum(v["views"] for v in vs), "videos": vs}
        flag = "GAP" if gap >= 60 else "CLOSING" if gap >= 25 else "COVERED"
        trail = [{"at": ts(age), "platform": "x", "label": "First X post", "url": top[0]["url"]}]
        trail += [{"at": v["published_at"], "platform": "youtube", "label": "YouTube video", "url": v["url"]} for v in vs]
        radar.append({
            "id": sid, "title": title, "summary": "Placeholder story until the first real refresh.",
            "x": {"post_count": count, "engagement": eng, "first_seen": ts(age), "top_url": top[0]["url"]},
            "youtube": {"video_count": vids, "total_views": coverage[sid]["total_views"],
                        "first_video_at": vs[0]["published_at"] if vs else None},
            "gap": {"score": gap, "flag": flag}, "trail": trail,
        })
    for rank, r in enumerate(sorted(radar, key=lambda r: -r["gap"]["score"]), 1):
        ideas.append({"rank": rank, "story_id": r["id"], "title": r["title"],
                      "angle": "Sample angle: what it means for builders", "why": "Placeholder reasoning.",
                      "gap_score": r["gap"]["score"], "flag": r["gap"]["flag"]})
    files = {
        "x": {"grabbed_at": ts(6.6), "source": "sample", "queries": ["sample"], "posts": posts},
        "stories": {"generated_at": ts(), "x_grabbed_at": ts(6.6), "stories": stories},
        "youtube": {"generated_at": ts(), "searches_used": 4, "coverage": coverage, "rising": [{
            "channel": "Sample Small Channel", "channel_id": "UCsmall", "channel_url": "https://www.youtube.com/@example",
            "subs": 2100, "video": video("sample", 9, 20, 48000), "views_per_sub": 22.9}]},
        "radar": {"generated_at": ts(), "stories": radar},
        "ideas": {"generated_at": ts(), "ideas": ideas},
        "stats": {"generated_at": ts(), "channel": {"title": "Chase AI", "subs": 0, "views": 0, "video_count": 0}, "median_views": 10000, "latest": [
            {"title": "Sample video A", "published_at": ts(30), "views": 14000, "vs_median": 1.4},
            {"title": "Sample video B", "published_at": ts(80), "views": 8000, "vs_median": 0.8},
            {"title": "Sample video C", "published_at": ts(130), "views": 10000, "vs_median": 1.0}]},
        "devcorner": {"generated_at": ts(), "releases": [{"tag": "v0.0.0-sample", "name": "Sample release",
                      "published_at": ts(20), "url": "https://github.com/anthropics/claude-code/releases",
                      "highlights": ["Real releases arrive with the first refresh."]}], "news": []},
        "runlog": {"runs": [{"at": ts(), "status": "partial", "note": "Sample data, waiting for the first refresh.",
                   "chips": [{"label": "X", "ok": False}, {"label": "YouTube", "ok": True}, {"label": "Dev", "ok": True},
                             {"label": "Stats", "ok": True}]}]},
        "meta": {"updated_at": ts(), "x_status": "waiting_for_pc", "x_grabbed_at": ts(6.6), "next_refresh_at": ts(-12)},
    }
    for name, body in files.items():
        (DATA / f"{name}.json").write_text(json.dumps({"sample": True, **body}, indent=2) + "\n")
    print("wrote", ", ".join(sorted(files)))


if __name__ == "__main__":
    main()
