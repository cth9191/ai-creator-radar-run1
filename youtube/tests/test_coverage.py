import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from youtube import coverage, ytapi
from youtube.tests import fixtures as fx
from youtube.tests.schema_check import errors, load


def world(n_stories=10):
    """Every story gets 3 relevant videos plus 1 off-topic one."""
    videos, channels, search = {}, {}, {}
    channels["UCbig"] = {"title": "Big AI", "subs": 900_000}
    channels["UCsmall"] = {"title": "Tiny Lab", "subs": 2_000}
    channels["UCmid"] = {"title": "Mid Dev", "subs": 30_000}
    channels["UChidden"] = {"title": "Hidden", "subs": 0, "hidden": True}
    for i in range(n_stories):
        q = f"topic{i} agents"
        ids = [f"v{i}a", f"v{i}b", f"v{i}c", f"v{i}x"]
        videos[ids[0]] = fx.video(f"Topic{i} is here, full breakdown", "UCbig", 50_000 + i)
        videos[ids[1]] = fx.video(f"I tried the new AGENTS thing", "UCsmall", 10_000 + i * 1000)
        videos[ids[2]] = fx.video(f"topic{i}: first look", "UCmid", 20_000)
        videos[ids[3]] = fx.video("My morning routine vlog", "UChidden", 999_999)
        search[q] = ids
    return fx.FakeYouTube(videos=videos, channels=channels, search=search)


class CoverageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.stories = self.dir / "stories.json"
        self.out = self.dir / "youtube.json"
        self.stories.write_text(json.dumps(fx.stories_doc(10)))
        env = {k: v for k, v in os.environ.items() if k != "RADAR_YT_MAX_SEARCHES"}
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_main(self, fake):
        err = io.StringIO()
        with mock.patch("urllib.request.urlopen", fake), redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = coverage.main(["--stories", str(self.stories), "--out", str(self.out)])
        return code, err.getvalue()

    def searches(self, fake):
        return [u for u in fake.urls if "/youtube/v3/search?" in u]

    def test_budget_never_exceeds_eight(self):
        fake = world(10)
        code, _ = self.run_main(fake)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.searches(fake)), 8)
        doc = json.loads(self.out.read_text())
        self.assertEqual(doc["searches_used"], 8)
        self.assertEqual(len(doc["coverage"]), 8)
        # highest-engagement stories win
        self.assertEqual(sorted(doc["coverage"]), [f"s{i}" for i in range(8)])

    def test_env_lowers_but_never_raises_budget(self):
        for raw, want in (("3", 3), ("0", 0), ("50", 8), ("-2", 0), ("junk", 8)):
            with self.subTest(raw=raw):
                os.environ["RADAR_YT_MAX_SEARCHES"] = raw
                fake = world(10)
                code, _ = self.run_main(fake)
                self.assertEqual(code, 0)
                self.assertEqual(len(self.searches(fake)), want)
                self.assertEqual(json.loads(self.out.read_text())["searches_used"], want)

    def test_never_adds_a_key(self):
        os.environ["YOUTUBE_API_KEY"] = "should-never-be-read"
        fake = world(3)
        self.run_main(fake)
        self.assertTrue(fake.urls)
        for url, headers in zip(fake.urls, fake.headers):
            self.assertTrue(url.startswith("https://www.googleapis.com/youtube/v3/"), url)
            self.assertNotRegex(url, r"(?i)[?&](key|api_key|apikey)=")
            self.assertNotIn("should-never-be-read", url)
            self.assertFalse({h.lower() for h in headers} & {"x-goog-api-key", "authorization"})

    def test_client_drops_key_param(self):
        url = ytapi.Client().url("search", {"q": "x", "key": "AIzaFAKE", "KEY": "y"})
        self.assertNotIn("key=", url.lower())

    def test_search_params(self):
        fake = world(1)
        self.run_main(fake)
        q = dict(p.split("=", 1) for p in self.searches(fake)[0].split("?", 1)[1].split("&"))
        self.assertEqual(q["type"], "video")
        self.assertTrue(15 <= int(q["maxResults"]) <= 25)
        # first_seen is 6h before NOW; publishedAfter is 2 days before first_seen
        self.assertEqual(q["publishedAfter"], "2026-10-14T06%3A00%3A00Z")

    def test_irrelevant_results_filtered(self):
        fake = world(2)
        self.run_main(fake)
        doc = json.loads(self.out.read_text())
        cov = doc["coverage"]["s0"]
        self.assertEqual(cov["video_count"], 3)
        titles = [v["title"] for v in cov["videos"]]
        self.assertNotIn("My morning routine vlog", titles)
        self.assertEqual(cov["total_views"], 50_000 + 10_000 + 20_000)
        # top videos sorted by views, with channel subs attached
        self.assertEqual([v["views"] for v in cov["videos"]], [50_000, 20_000, 10_000])
        self.assertEqual(cov["videos"][0]["channel_subs"], 900_000)
        # the filtered video was never looked up
        self.assertFalse(any("v0x" in u for u in fake.urls if "/videos?" in u))

    def test_key_terms_and_relevance(self):
        story = {"keywords": ["open-weights", "coding", "model"], "search_query": "new open-weights coding model"}
        terms = coverage.key_terms(story)
        self.assertNotIn("new", terms)
        self.assertTrue(coverage.is_relevant("Open Weights coding beast", terms))
        self.assertTrue(coverage.is_relevant("Best OPEN-WEIGHTS release", terms))
        self.assertFalse(coverage.is_relevant("Cooking pasta at home", terms))
        self.assertFalse(coverage.is_relevant("Modeling clay", {"model"}))

    def test_rising_ranking(self):
        vids = [
            {"id": "a", "channel": "A", "channel_id": "A", "channel_subs": 1_000, "views": 5_000},     # 5.0
            {"id": "b", "channel": "B", "channel_id": "B", "channel_subs": 2_000, "views": 40_000},    # 20.0
            {"id": "b2", "channel": "B", "channel_id": "B", "channel_subs": 2_000, "views": 4_000},    # same channel, lower
            {"id": "c", "channel": "C", "channel_id": "C", "channel_subs": 60_000, "views": 900_000},  # too big
            {"id": "d", "channel": "D", "channel_id": "D", "channel_subs": 40_000, "views": 20_000},   # ratio < 1
            {"id": "e", "channel": "E", "channel_id": "E", "views": 90_000},                          # subs hidden
            {"id": "f", "channel": "F", "channel_id": "F", "channel_subs": 100, "views": 900},         # under view floor
            {"id": "g", "channel": "G", "channel_id": "G", "channel_subs": 10_000, "views": 30_000},   # 3.0
        ]
        out = coverage.rising_channels(vids)
        self.assertEqual([r["channel"] for r in out], ["B", "A", "G"])
        self.assertEqual(out[0]["views_per_sub"], 20.0)
        self.assertEqual(out[0]["video"]["id"], "b")
        self.assertTrue(out[0]["channel_url"].startswith("https://"))
        many = [{"id": str(i), "channel": str(i), "channel_id": str(i), "channel_subs": 1000, "views": 2000 + i * 100}
                for i in range(9)]
        self.assertEqual(len(coverage.rising_channels(many)), 5)

    def test_output_matches_schema(self):
        fake = world(10)
        self.run_main(fake)
        doc = json.loads(self.out.read_text())
        self.assertEqual(errors(doc, load("youtube")), [])
        self.assertFalse(doc["sample"])
        self.assertTrue(doc["rising"])
        self.assertEqual(doc["rising"][0]["channel"], "Tiny Lab")

    def test_failure_leaves_old_file(self):
        self.out.write_text('{"old": true}\n')
        for endpoint in ("search", "videos", "channels"):
            with self.subTest(endpoint=endpoint):
                fake = world(3)
                fake.fail_on = endpoint
                code, err = self.run_main(fake)
                self.assertNotEqual(code, 0)
                self.assertEqual(self.out.read_text(), '{"old": true}\n')
                self.assertIn("quotaExceeded", err)
                self.assertEqual(len(err.strip().splitlines()), 1)
                self.assertNotIn("?", err)  # no request URL / query in the message
        self.assertEqual([p.name for p in self.dir.iterdir() if p.name.startswith(".")], [])

    def test_missing_stories_fails(self):
        self.stories.unlink()
        self.out.write_text("{}")
        code, err = self.run_main(world(1))
        self.assertNotEqual(code, 0)
        self.assertEqual(self.out.read_text(), "{}")

    def test_sanitize(self):
        s = ytapi.sanitize("GET https://x/y?q=a&key=AIzaSyA1234567890abcdefghijklmnopqrstu&b=1 token=abc")
        self.assertNotIn("AIzaSy", s)
        self.assertNotIn("abc", s.split("token=")[1])


if __name__ == "__main__":
    unittest.main()
