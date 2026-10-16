"""Synthetic YouTube Data API v3 responses (recorded shape, made-up data) and a fake urlopen.

Shapes follow the documented search.list, videos.list, channels.list and
playlistItems.list responses. No network is used.
"""
import io
import json
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakeYouTube:
    """Callable that stands in for urllib.request.urlopen and records every URL."""

    def __init__(self, videos=None, channels=None, search=None, fail_on=None, uploads=None, handle_channel=None):
        self.videos = videos or {}          # id -> {title, channelId, channelTitle, publishedAt, views}
        self.channels = channels or {}      # id -> {title, subs, hidden?, views, videoCount, customUrl}
        self.search = search or {}          # q -> [video ids]
        self.fail_on = fail_on              # endpoint name that returns 403 quotaExceeded
        self.uploads = uploads or []        # video ids, newest first
        self.handle_channel = handle_channel
        self.urls = []
        self.headers = []

    def __call__(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        self.urls.append(url)
        self.headers.append(dict(getattr(req, "header_items", lambda: [])()))
        parsed = urllib.parse.urlparse(url)
        endpoint = parsed.path.rsplit("/", 1)[-1]
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        if self.fail_on == endpoint:
            body = json.dumps({"error": {"code": 403, "message": "The request cannot be completed because you have exceeded your quota.",
                                         "errors": [{"reason": "quotaExceeded"}]}}).encode()
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, io.BytesIO(body))
        handler = getattr(self, "_" + endpoint)
        return FakeResponse(json.dumps(handler(q)).encode())

    def _snippet(self, vid):
        v = self.videos[vid]
        return {"publishedAt": v["publishedAt"], "channelId": v["channelId"], "title": v["title"],
                "description": "", "channelTitle": self.channels.get(v["channelId"], {}).get("title", v["channelTitle"]),
                "thumbnails": {"default": {"url": f"https://i.ytimg.com/vi/{vid}/default.jpg", "width": 120, "height": 90},
                               "medium": {"url": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg", "width": 320, "height": 180}},
                "liveBroadcastContent": "none"}

    def _search(self, q):
        ids = self.search.get(q["q"], [])[: int(q.get("maxResults", 5))]
        return {"kind": "youtube#searchListResponse", "etag": "e", "regionCode": "US",
                "pageInfo": {"totalResults": len(ids), "resultsPerPage": len(ids)},
                "items": [{"kind": "youtube#searchResult", "etag": "e",
                           "id": {"kind": "youtube#video", "videoId": vid},
                           "snippet": self._snippet(vid)} for vid in ids]}

    def _videos(self, q):
        items = []
        for vid in q["id"].split(","):
            if vid not in self.videos:
                continue
            items.append({"kind": "youtube#video", "etag": "e", "id": vid, "snippet": self._snippet(vid),
                          "statistics": {"viewCount": str(self.videos[vid]["views"]), "likeCount": "1",
                                         "favoriteCount": "0", "commentCount": "0"}})
        return {"kind": "youtube#videoListResponse", "etag": "e", "items": items,
                "pageInfo": {"totalResults": len(items), "resultsPerPage": len(items)}}

    def _channel_item(self, cid):
        c = self.channels[cid]
        return {"kind": "youtube#channel", "etag": "e", "id": cid,
                "snippet": {"title": c["title"], "description": "", "customUrl": c.get("customUrl", "@x"),
                            "publishedAt": "2020-01-01T00:00:00Z"},
                "contentDetails": {"relatedPlaylists": {"likes": "", "uploads": "UU" + cid[2:]}},
                "statistics": {"viewCount": str(c.get("views", 0)), "subscriberCount": str(c["subs"]),
                               "hiddenSubscriberCount": c.get("hidden", False), "videoCount": str(c.get("videoCount", 0))}}

    def _channels(self, q):
        if "forHandle" in q:
            ids = [self.handle_channel] if self.handle_channel and q["forHandle"] == "@chaseai" else []
        else:
            ids = [c for c in q["id"].split(",") if c in self.channels]
        items = [self._channel_item(c) for c in ids]
        return {"kind": "youtube#channelListResponse", "etag": "e", "items": items,
                "pageInfo": {"totalResults": len(items), "resultsPerPage": 5}}

    def _playlistItems(self, q):
        ids = self.uploads[: int(q.get("maxResults", 5))]
        return {"kind": "youtube#playlistItemListResponse", "etag": "e",
                "items": [{"kind": "youtube#playlistItem", "etag": "e", "id": "pi" + vid,
                           "contentDetails": {"videoId": vid, "videoPublishedAt": self.videos[vid]["publishedAt"]}}
                          for vid in ids],
                "pageInfo": {"totalResults": len(ids), "resultsPerPage": len(ids)}}


def stories_doc(n=10):
    """n stories with descending engagement; story i searches 'topic{i} agents'."""
    out = []
    for i in range(n):
        out.append({"id": f"s{i}", "title": f"Topic{i} agents ship", "keywords": [f"topic{i}", "agents"],
                    "search_query": f"topic{i} agents", "first_seen": iso(NOW - timedelta(hours=6)),
                    "post_count": 10, "engagement": 10000 - i * 100})
    return {"generated_at": iso(NOW), "stories": out}


def video(title, channel_id, views, hours_ago=10, channel_title=None):
    return {"title": title, "channelId": channel_id, "channelTitle": channel_title or channel_id,
            "publishedAt": iso(NOW - timedelta(hours=hours_ago)), "views": views}
