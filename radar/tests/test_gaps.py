"""Gap scoring, flags, unknown coverage, trails and ideas."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from radar import gaps
from radar import stories as st
from radar.tests.schema_check import check_schema

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures"


def story(sid="s1", engagement=18000, velocity=1500, first_seen="2026-10-16T02:00:00Z", **kw):
    s = {"id": sid, "title": kw.pop("title", "OpenAI GPT-5.5 launch"), "summary": "x",
         "keywords": kw.pop("keywords", ["GPT-5.5", "OpenAI"]), "search_query": "OpenAI GPT-5.5 launch",
         "first_seen": first_seen, "post_ids": ["a"], "post_count": 12, "engagement": engagement,
         "velocity": velocity,
         "top_posts": [{"id": "a", "url": "https://x.com/example_a/status/1", "author": {"handle": "example_a"},
                        "text": "t", "created_at": "2026-10-16T03:00:00Z", "likes": 900, "reposts": 100}],
         "first_post": {"id": "f", "url": "https://x.com/example_f/status/2", "handle": "example_f",
                        "created_at": first_seen}}
    s.update(kw)
    return s


def videos(n, views_each=10000, at="2026-10-16T06:00:00Z"):
    vids = [{"id": f"v{i}", "url": f"https://www.youtube.com/watch?v=v{i}", "title": "t", "channel": f"Example {i}",
             "published_at": at, "views": views_each} for i in range(n)]
    return {"query": "q", "video_count": n, "total_views": n * views_each, "videos": vids}


class ScoreTest(unittest.TestCase):
    def test_flags_follow_thresholds(self):
        self.assertEqual(gaps.flag_for(100), "GAP")
        self.assertEqual(gaps.flag_for(60), "GAP")
        self.assertEqual(gaps.flag_for(59), "CLOSING")
        self.assertEqual(gaps.flag_for(25), "CLOSING")
        self.assertEqual(gaps.flag_for(24), "COVERED")
        self.assertEqual(gaps.flag_for(0), "COVERED")

    def test_more_videos_lower_score(self):
        scores = [gaps.gap_score(story(), videos(n))[0] for n in (0, 1, 2, 4, 8, 16)]
        self.assertEqual(scores, sorted(scores, reverse=True), scores)
        self.assertGreater(scores[0], scores[-1])

    def test_more_views_lower_score(self):
        scores = [gaps.gap_score(story(), videos(3, v))[0] for v in (100, 5000, 50000, 500000, 5000000)]
        self.assertEqual(scores, sorted(scores, reverse=True), scores)
        self.assertGreater(scores[0], scores[-1])

    def test_hotter_story_higher_score(self):
        cov = videos(1)
        scores = [gaps.gap_score(story(engagement=e, velocity=e / 10), cov)[0] for e in (100, 1000, 10000, 100000)]
        self.assertEqual(scores, sorted(scores), scores)

    def test_old_videos_count_less(self):
        fresh = gaps.gap_score(story(), videos(3, at="2026-10-16T06:00:00Z"))[0]
        old = gaps.gap_score(story(), videos(3, at="2026-10-10T06:00:00Z"))[0]
        self.assertGreater(old, fresh)

    def test_hot_uncovered_story_is_gap_and_covered_story_is_not(self):
        self.assertEqual(gaps.flag_for(gaps.gap_score(story(), videos(0))[0]), "GAP")
        self.assertEqual(gaps.flag_for(gaps.gap_score(story(), videos(20, 200000))[0]), "COVERED")

    def test_score_in_range(self):
        for e in (0, 10, 10 ** 7):
            for cov in (None, videos(0), videos(50, 10 ** 7)):
                s = gaps.gap_score(story(engagement=e, velocity=e), cov)[0]
                self.assertTrue(0 <= s <= 100)


class UnknownCoverageTest(unittest.TestCase):
    def test_missing_entry_capped_and_marked(self):
        radar, ideas = gaps.build({"stories": [story(engagement=10 ** 6, velocity=10 ** 5)]}, {"coverage": {}})
        r = radar[0]
        self.assertEqual(r["youtube"]["video_count"], 0)
        self.assertFalse(r["youtube"]["checked"])
        self.assertLessEqual(r["gap"]["score"], gaps.UNKNOWN_CAP)
        self.assertTrue(r["gap"]["capped"])
        self.assertIn("not checked", ideas[0]["why"])

    def test_missing_youtube_file(self):
        radar, _ = gaps.build({"stories": [story()]}, None)
        self.assertEqual(len(radar), 1)
        self.assertFalse(radar[0]["youtube"]["checked"])

    def test_checked_zero_beats_unknown(self):
        known = gaps.gap_score(story(engagement=10 ** 6, velocity=10 ** 5), videos(0))[0]
        unknown = gaps.gap_score(story(engagement=10 ** 6, velocity=10 ** 5), None)[0]
        self.assertGreater(known, unknown)


class TrailAndIdeasTest(unittest.TestCase):
    def test_trail_time_ordered_with_both_platforms(self):
        r = gaps.radar_story(story(), videos(2))
        ats = [t["at"] for t in r["trail"]]
        self.assertEqual(ats, sorted(ats))
        self.assertEqual(r["trail"][0]["platform"], "x")
        self.assertEqual(r["trail"][0]["url"], "https://x.com/example_f/status/2")
        self.assertEqual(sum(t["platform"] == "youtube" for t in r["trail"]), 2)
        self.assertTrue(any(t["label"].startswith("Peak") for t in r["trail"]))

    def test_ideas_ranked_by_gap_with_numbers(self):
        stories = {"stories": [story("a", title="Cursor 2.0", keywords=["Cursor 2.0"]),
                               story("b", engagement=900, velocity=40, title="Sora 3", keywords=["Sora 3"])]}
        cov = {"coverage": {"a": videos(0), "b": videos(12, 90000)}}
        radar, ideas = gaps.build(stories, cov)
        self.assertEqual([i["story_id"] for i in ideas], ["a", "b"])
        self.assertEqual([i["rank"] for i in ideas], [1, 2])
        self.assertIn("12 X posts", ideas[0]["why"])
        self.assertIn("0 YouTube videos", ideas[0]["why"])
        self.assertIn("Claude Code", ideas[0]["angle"])
        self.assertIn("Sora 3", ideas[1]["angle"])

    def test_angle_templates_are_deterministic(self):
        self.assertEqual(gaps.angle_for(story(keywords=["GPT-5.5", "Claude Opus 4.7"])),
                         "GPT-5.5 vs Claude Opus 4.7: which one should you actually use?")
        self.assertEqual(gaps.angle_for(story(keywords=["GPT-5.5", "OpenAI"])), "I tested GPT-5.5 so you don't have to")
        self.assertIn("locally", gaps.angle_for(story(title="DeepSeek V4 open weights", keywords=["DeepSeek V4"])))
        self.assertIn("explained", gaps.angle_for(story(title="$NVDA earnings", keywords=["$NVDA"])))


class EndToEndTest(unittest.TestCase):
    def test_fixture_pipeline_validates(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            run = lambda *a: subprocess.run([sys.executable, *map(str, a)], capture_output=True, text=True)
            r = run(ROOT / "radar" / "stories.py", "--x", FIX / "x_fixture.json", "--out", d / "stories.json")
            self.assertEqual(r.returncode, 0, r.stderr)
            r = run(ROOT / "radar" / "gaps.py", "--stories", d / "stories.json", "--youtube", FIX / "youtube_fixture.json",
                    "--radar", d / "radar.json", "--ideas", d / "ideas.json")
            self.assertEqual(r.returncode, 0, r.stderr)
            radar = json.loads((d / "radar.json").read_text())
            ideas = json.loads((d / "ideas.json").read_text())
            check_schema(self, "radar", radar)
            check_schema(self, "ideas", ideas)
            by_id = {s["id"]: s for s in radar["stories"]}
            self.assertEqual(by_id["claude-opus-4-7"]["gap"]["flag"], "GAP")
            self.assertEqual(by_id["sora-3"]["gap"]["flag"], "COVERED")
            self.assertFalse(by_id["nvda"]["youtube"]["checked"])
            scores = [s["gap"]["score"] for s in radar["stories"]]
            self.assertEqual(scores, sorted(scores, reverse=True))

    def test_missing_stories_fails_without_writing(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "radar.json").write_text("old")
            r = subprocess.run([sys.executable, str(ROOT / "radar" / "gaps.py"), "--stories", str(d / "nope.json"),
                                "--radar", str(d / "radar.json"), "--ideas", str(d / "ideas.json")],
                               capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual((d / "radar.json").read_text(), "old")
            self.assertFalse((d / "ideas.json").exists())


if __name__ == "__main__":
    unittest.main()
