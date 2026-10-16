"""Unit tests for ops/devcorner.py. No network: http is replaced with canned responses."""
import json
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from ops import devcorner as D
from ops.refresh import validate

REPO = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 16, 11, 7, tzinfo=timezone.utc)

BODY = """## What's changed

### New
- Added **plan mode** for [subagents](https://docs.example.com/a) so they `think` first
- Fixed a crash when resizing
* Improved `/compact` speed by 2x
1. Added a very long feature description that keeps going and going well past the limit we allow for a single highlight line in the panel
-

> quoted note
Plain paragraph line.
"""

CHANGELOG = """# Changelog

## 2.1.301

- Added `FOO` env var
- Fixed bar

## 2.1.300

- Improved baz

## 2.1.299

- Added qux
"""


class HighlightTests(unittest.TestCase):
    def test_strips_markdown_and_skips_headings(self):
        h = D.extract_highlights(BODY)
        self.assertTrue(3 <= len(h) <= 5)
        self.assertEqual(h[0], "Added plan mode for subagents so they think first")
        self.assertNotIn("What's changed", " ".join(h))
        self.assertNotIn("quoted note", " ".join(h))
        self.assertNotIn("Plain paragraph line.", h)  # bullets preferred over paragraphs
        for line in h:
            self.assertLessEqual(len(line), D.MAX_CHARS)
            self.assertNotRegex(line, r"[`*\[\]]")

    def test_new_features_ranked_before_fixes(self):
        h = D.extract_highlights(BODY)
        self.assertTrue(h.index("Improved /compact speed by 2x") < h.index("Fixed a crash when resizing"))
        self.assertTrue(h[1].startswith("Added a very long"))
        self.assertTrue(h[1].endswith("…"))

    def test_paragraphs_when_no_bullets(self):
        self.assertEqual(D.extract_highlights("# Title\n\nJust one line here.\n"), ["Just one line here."])

    def test_empty_body(self):
        self.assertEqual(D.extract_highlights(""), [])
        self.assertEqual(D.extract_highlights(None), [])


def fake_fetch(responses):
    def fetch(url, accept="application/json"):
        for prefix, value in responses.items():
            if url.startswith(prefix):
                if isinstance(value, Exception):
                    raise value
                return value if isinstance(value, bytes) else json.dumps(value).encode()
        raise AssertionError(f"unexpected url {url}")
    return fetch


class SourceTests(unittest.TestCase):
    def test_github_releases(self):
        api = [
            {"tag_name": "v2.1.301", "name": "v2.1.301", "published_at": "2026-10-15T14:34:23Z",
             "html_url": "https://github.com/anthropics/claude-code/releases/tag/v2.1.301", "body": BODY, "draft": False},
            {"tag_name": "v2.1.302", "name": "", "published_at": "2026-10-16T01:00:00Z",
             "html_url": "https://github.com/anthropics/claude-code/releases/tag/v2.1.302", "body": "- Added x", "draft": True},
            {"tag_name": "v2.1.300", "name": None, "published_at": "2026-10-14T14:27:26Z",
             "html_url": "https://github.com/anthropics/claude-code/releases/tag/v2.1.300", "body": "- Added y"},
        ]
        doc = D.build(NOW, fake_fetch({D.RELEASES_API: api}))
        self.assertEqual([r["tag"] for r in doc["releases"]], ["v2.1.301", "v2.1.300"])  # draft skipped
        self.assertEqual(doc["releases"][1]["name"], "v2.1.300")
        self.assertFalse(doc["sample"])
        self.assertEqual(doc["news"], [])
        self.assertEqual(validate(REPO, "devcorner", doc), [])

    def test_falls_back_to_changelog_and_npm(self):
        fetch = fake_fetch({
            D.RELEASES_API: urllib.error.HTTPError(D.RELEASES_API, 403, "Forbidden", {}, None),
            D.CHANGELOG_URL: CHANGELOG.encode(),
            D.NPM_URL: {"time": {"2.1.301": "2026-10-15T14:34:23.330Z", "2.1.300": "2026-10-14T14:27:26.554Z"}},
        })
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            doc = D.build(NOW, fetch)
        tags = [r["tag"] for r in doc["releases"]]
        self.assertEqual(tags, ["v2.1.301", "v2.1.300"])  # 2.1.299 has no npm time, skipped
        self.assertEqual(doc["releases"][0]["published_at"], "2026-10-15T14:34:23Z")
        self.assertEqual(doc["releases"][0]["highlights"], ["Added FOO env var", "Fixed bar"])
        self.assertEqual(doc["releases"][0]["url"], "https://github.com/anthropics/claude-code/releases/tag/v2.1.301")
        self.assertEqual(validate(REPO, "devcorner", doc), [])

    def test_all_sources_down_raises(self):
        err = urllib.error.URLError("offline")
        fetch = fake_fetch({D.RELEASES_API: err, D.CHANGELOG_URL: err, D.NPM_URL: err})
        with self.assertRaises(RuntimeError):
            D.build(NOW, fetch)

    def test_parse_changelog(self):
        secs = D.parse_changelog(CHANGELOG)
        self.assertEqual([v for v, _ in secs], ["2.1.301", "2.1.300", "2.1.299"])


if __name__ == "__main__":
    unittest.main()
