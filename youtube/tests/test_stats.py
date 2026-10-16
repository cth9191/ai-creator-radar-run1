import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from youtube import stats
from youtube.tests import fixtures as fx
from youtube.tests.schema_check import errors, load


def channel_world():
    videos = {
        "n1": fx.video("Fresh upload", "UCchase", 90_000, hours_ago=5),      # < 48h: not in median
        "n2": fx.video("Yesterday", "UCchase", 1_000, hours_ago=30),          # < 48h: not in median
        "o1": fx.video("Three days", "UCchase", 14_000, hours_ago=72),
        "o2": fx.video("Four days", "UCchase", 8_000, hours_ago=96),
        "o3": fx.video("Five days", "UCchase", 10_000, hours_ago=120),
        "o4": fx.video("Six days", "UCchase", 12_000, hours_ago=144),
        "o5": fx.video("Week", "UCchase", 6_000, hours_ago=168),
    }
    channels = {"UCchase": {"title": "Chase AI", "subs": 123_456, "views": 9_876_543, "videoCount": 210,
                            "customUrl": "@chaseai"}}
    return fx.FakeYouTube(videos=videos, channels=channels, uploads=["n1", "n2", "o1", "o2", "o3", "o4", "o5"],
                          handle_channel="UCchase")


class StatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = self.dir / "config.json"
        self.out = self.dir / "stats.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, fake, cfg):
        self.cfg.write_text(json.dumps(cfg))
        err = io.StringIO()
        with mock.patch("urllib.request.urlopen", fake), mock.patch.object(stats.ytapi, "now_utc", lambda: fx.NOW), \
                redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = stats.main(["--config", str(self.cfg), "--out", str(self.out)])
        return code, err.getvalue()

    def test_handle_flow_and_median_excludes_young_videos(self):
        fake = channel_world()
        code, err = self.run_main(fake, {"channel_handle": "chaseai", "channel_id": None})
        self.assertEqual(code, 0, err)
        doc = json.loads(self.out.read_text())
        # median of 14k, 8k, 10k, 12k, 6k = 10k (the 90k and 1k fresh uploads are ignored)
        self.assertEqual(doc["median_views"], 10_000)
        self.assertEqual([v["id"] for v in doc["latest"]], ["n1", "n2", "o1", "o2", "o3"])
        self.assertEqual(doc["latest"][0]["vs_median"], 9.0)
        self.assertEqual(doc["latest"][2]["vs_median"], 1.4)
        self.assertEqual(doc["channel"]["subs"], 123_456)
        self.assertEqual(doc["channel"]["video_count"], 210)
        self.assertEqual(doc["channel"]["url"], "https://www.youtube.com/@chaseai")
        self.assertEqual(errors(doc, load("stats")), [])
        self.assertTrue(any("forHandle=%40chaseai" in u for u in fake.urls))

    def test_no_search_and_no_key(self):
        fake = channel_world()
        self.run_main(fake, {"channel_handle": None, "channel_id": "UCchase"})
        self.assertTrue(fake.urls)
        for u in fake.urls:
            self.assertNotIn("/search?", u)
            self.assertNotRegex(u, r"(?i)[?&](key|api_key|apikey)=")
        self.assertTrue(any("id=UCchase" in u for u in fake.urls if "/channels?" in u))
        self.assertTrue(any("/playlistItems?" in u for u in fake.urls))

    def test_unset_config_fails_with_message(self):
        self.out.write_text("old")
        fake = channel_world()
        code, err = self.run_main(fake, {"channel_handle": None, "channel_id": None})
        self.assertNotEqual(code, 0)
        self.assertIn("set youtube/config.json channel_handle", err)
        self.assertEqual(fake.urls, [])
        self.assertEqual(self.out.read_text(), "old")

    def test_unknown_handle_fails(self):
        self.out.write_text("old")
        code, err = self.run_main(channel_world(), {"channel_handle": "@nobody"})
        self.assertNotEqual(code, 0)
        self.assertIn("not found", err)
        self.assertEqual(self.out.read_text(), "old")

    def test_quota_error_leaves_old_file(self):
        self.out.write_text("old")
        fake = channel_world()
        fake.fail_on = "videos"
        code, err = self.run_main(fake, {"channel_id": "UCchase"})
        self.assertNotEqual(code, 0)
        self.assertEqual(self.out.read_text(), "old")
        self.assertIn("quotaExceeded", err)
        self.assertNotIn("?", err)

    def test_median_helper(self):
        vids = [{"views": 100, "published_at": fx.iso(fx.NOW)}]
        self.assertEqual(stats.median_views(vids, fx.NOW), 0)

    def test_shipped_config_has_no_guess(self):
        cfg = json.loads(stats.CONFIG.read_text())
        self.assertIn("channel_handle", cfg)
        self.assertIn("channel_id", cfg)


if __name__ == "__main__":
    unittest.main()
