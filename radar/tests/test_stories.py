"""Story grouping: related posts group, unrelated ones separate, ids stay stable."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from radar import stories as st
from radar.tests.schema_check import check_schema

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "x_fixture.json"


def load_fixture():
    return json.loads(FIXTURE.read_text())


def post(pid, text, hours_ago=1.0, likes=500, reposts=50, handle="example_user"):
    h = int(hours_ago * 60)
    return {"id": pid, "url": f"https://x.com/{handle}/status/{pid}", "author": {"handle": handle},
            "text": text, "created_at": f"2026-10-16T{(12 * 60 - h) // 60:02d}:{(12 * 60 - h) % 60:02d}:00Z",
            "likes": likes, "reposts": reposts, "replies": 10, "quotes": 5}


def doc(posts, queries=None):
    return {"grabbed_at": "2026-10-16T12:00:00Z", "source": "pc", "queries": queries or ["AI news"], "posts": posts}


def story_of(stories, post_id):
    for s in stories:
        if post_id in s["post_ids"]:
            return s["id"]
    return None


class TermsTest(unittest.TestCase):
    def test_extracts_versions_tickers_and_names(self):
        terms, _ = st.extract_terms("BREAKING: OpenAI ships GPT-5.5 and Claude Opus 4.7 drops; $NVDA up 5%")
        self.assertIn("gpt-5.5", terms)
        self.assertEqual(terms["gpt-5.5"][1], "GPT-5.5")
        self.assertIn("opus-4.7", terms)
        self.assertEqual(terms["opus-4.7"][1], "Claude Opus 4.7")
        self.assertIn("$nvda", terms)
        self.assertIn("openai", terms)
        self.assertEqual(terms["gpt-5.5"][0], 1)

    def test_lowercase_versions_normalise_to_same_term(self):
        a, _ = st.extract_terms("gpt 5.5 is out")
        b, _ = st.extract_terms("GPT-5.5 is out")
        self.assertIn("gpt-5.5", a)
        self.assertIn("gpt-5.5", b)

    def test_ignores_counting_phrases_and_sentence_starts(self):
        terms, _ = st.extract_terms("Top 10 tips. Trying something new today")
        self.assertNotIn("top-10", terms)
        self.assertNotIn("trying", terms)

    def test_engagement_formula(self):
        self.assertEqual(st.engagement({"likes": 10, "reposts": 3, "replies": 2, "quotes": 1}), 10 + 6 + 2 + 2)
        self.assertEqual(st.engagement({"likes": 10, "reposts": 0}), 10)


class GroupingTest(unittest.TestCase):
    def test_groups_related_and_separates_unrelated(self):
        posts = [
            post("1", "OpenAI just released GPT-5.5 with a 1M context window", 8),
            post("2", "GPT-5.5 benchmarks look strong on SWE-bench", 7),
            post("3", "gpt-5.5 pricing is $3 per million tokens", 6),
            post("4", "OpenAI's Sora 3 makes minute-long videos with dialogue", 5),
            post("5", "Sora 3 hands look right for once", 4),
            post("6", "Sora 3 app hits number one on the App Store", 3),
        ]
        stories, _now = st.build_stories(doc(posts))
        gpt = {story_of(stories, p) for p in ("1", "2", "3")}
        sora = {story_of(stories, p) for p in ("4", "5", "6")}
        self.assertEqual(len(gpt), 1, stories)
        self.assertEqual(len(sora), 1, stories)
        self.assertNotEqual(gpt, sora)
        self.assertEqual(gpt, {"gpt-5-5"})
        self.assertEqual(sora, {"sora-3"})

    def test_fixture_grouping(self):
        stories, _ = st.build_stories(load_fixture())
        ids = [s["id"] for s in stories]
        for expected in ("gpt-5-5", "claude-opus-4-7", "gemini-3-pro", "sora-3", "deepseek-v4",
                         "claude-code", "nvda", "cursor-2-0"):
            self.assertIn(expected, ids)
        by_id = {s["id"]: s for s in stories}
        self.assertEqual(by_id["gpt-5-5"]["post_count"], 8)
        self.assertEqual(by_id["claude-code"]["post_count"], 5)
        # low-engagement chatter is not a story
        self.assertIsNone(story_of(stories, "fx1039"))
        self.assertIsNone(story_of(stories, "fx1042"))
        # every post belongs to at most one story
        all_ids = [pid for s in stories for pid in s["post_ids"]]
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_drops_quiet_singletons_keeps_loud_ones(self):
        posts = [
            post("1", "Midjourney V8 is out", 2, likes=20, reposts=1),
            post("2", "Kling 3 launches with native audio", 2, likes=5000, reposts=900),
        ]
        stories, _ = st.build_stories(doc(posts))
        self.assertIsNone(story_of(stories, "1"))
        self.assertIsNotNone(story_of(stories, "2"))

    def test_ranked_and_capped(self):
        stories, _ = st.build_stories(load_fixture())
        self.assertLessEqual(len(stories), st.MAX_STORIES)
        scores = [s["rank_score"] for s in stories]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_story_fields(self):
        stories, _ = st.build_stories(load_fixture())
        for s in stories:
            self.assertRegex(s["id"], r"^[a-z0-9-]+$")
            self.assertTrue(2 <= len(s["search_query"].split()) <= 5, s["search_query"])
            self.assertLessEqual(len(s["top_posts"]), 3)
            self.assertEqual(s["post_count"], len(s["post_ids"]))
            self.assertGreater(s["velocity"], 0)
            self.assertTrue(s["title"])
            self.assertTrue(s["keywords"])
        by_id = {s["id"]: s for s in stories}
        self.assertEqual(by_id["gpt-5-5"]["first_seen"], "2026-10-15T19:00:00Z")


class StabilityTest(unittest.TestCase):
    def test_same_input_same_output(self):
        a, _ = st.build_stories(load_fixture())
        b, _ = st.build_stories(load_fixture())
        self.assertEqual(a, b)

    def test_ids_stable_when_posts_shuffle_or_grow(self):
        base = load_fixture()
        a, _ = st.build_stories(base)
        shuffled = copy.deepcopy(base)
        shuffled["posts"].reverse()
        b, _ = st.build_stories(shuffled)
        self.assertEqual([s["id"] for s in a], [s["id"] for s in b])
        grown = copy.deepcopy(base)
        grown["posts"].append(post("new1", "GPT-5.5 just helped me ship a feature in an hour", 0.5))
        c, _ = st.build_stories(grown)
        self.assertEqual(sorted(s["id"] for s in a), sorted(s["id"] for s in c))
        self.assertIn("new1", next(s for s in c if s["id"] == "gpt-5-5")["post_ids"])


class ScriptTest(unittest.TestCase):
    def run_script(self, x_path, out_path):
        return subprocess.run([sys.executable, str(ROOT / "radar" / "stories.py"), "--x", str(x_path), "--out", str(out_path)],
                              capture_output=True, text=True)

    def test_writes_valid_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "stories.json"
            r = self.run_script(FIXTURE, out)
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(out.read_text())
            self.assertEqual(data["x_grabbed_at"], "2026-10-16T04:30:00Z")
            check_schema(self, "stories", data)

    def test_failure_leaves_old_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "stories.json"
            out.write_text('{"old": true}')
            bad = Path(d) / "x.json"
            bad.write_text("{not json")
            r = self.run_script(bad, out)
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(out.read_text(), '{"old": true}')
            empty = Path(d) / "x2.json"
            empty.write_text(json.dumps(doc([])))
            self.assertNotEqual(self.run_script(empty, out).returncode, 0)
            self.assertEqual(out.read_text(), '{"old": true}')
            self.assertEqual([p.name for p in Path(d).iterdir() if p.name.endswith(".tmp")], [])


if __name__ == "__main__":
    unittest.main()
