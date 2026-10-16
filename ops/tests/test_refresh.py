"""Unit tests for ops/refresh.py. No network, no real git, no real step scripts."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from ops import refresh as R

REPO = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 16, 11, 7, tzinfo=timezone.utc)


def grab(grabbed_at, n=3):
    return {
        "grabbed_at": R.iso(grabbed_at),
        "source": "pc",
        "posts": [{"id": f"p{i}", "url": f"https://x.com/a/status/{i}", "author": {"handle": "a"},
                   "text": "hello", "created_at": R.iso(grabbed_at), "likes": 1, "reposts": 0} for i in range(n)],
    }


class FakeGit:
    """Stands in for run_git. `files` maps 'origin/data:x/latest.json' -> text, or None = missing branch."""

    def __init__(self, text=None):
        self.text = text
        self.calls = []

    def __call__(self, root, args, timeout=R.GIT_TIMEOUT):
        self.calls.append(args)
        if args[0] == "fetch":
            return (0, "", "") if self.text is not None else (128, "", "fatal: couldn't find remote ref data")
        if args[0] == "show":
            if self.text is None:
                return 128, "", "fatal: invalid object name 'origin/data'"
            return 0, self.text, ""
        return 1, "", "unexpected"


class FakeRunner:
    """Stands in for run_script. `actions` maps script -> callable(root) returning (code, output)."""

    def __init__(self, actions=None):
        self.actions = actions or {}
        self.ran = []

    def __call__(self, root, script, timeout):
        self.ran.append(script)
        act = self.actions.get(script)
        return act(root) if act else (0, "ok")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(REPO / "shell" / "schema", self.tmp / "shell" / "schema")
        shutil.copytree(REPO / "data", self.tmp / "data")
        for s in ("radar/stories.py", "youtube/coverage.py", "youtube/stats.py", "radar/gaps.py", "ops/devcorner.py"):
            (self.tmp / s).parent.mkdir(parents=True, exist_ok=True)
            (self.tmp / s).write_text("# stub\n")
        # Known starting point regardless of what is in the working copy's data/.
        (self.tmp / "data" / "runlog.json").write_text(json.dumps({"sample": True, "runs": [
            {"at": "2026-10-16T11:07:00Z", "status": "partial", "note": "Sample data", "chips": [{"label": "X", "ok": False}]}]}))
        (self.tmp / "data" / "meta.json").write_text(json.dumps({
            "sample": True, "updated_at": "2026-10-16T11:07:00Z", "x_status": "waiting_for_pc",
            "x_grabbed_at": "2026-10-16T04:31:00Z", "next_refresh_at": "2026-10-16T23:07:00Z"}))
        (self.tmp / "data" / "x.json").write_text(json.dumps({**grab(NOW - timedelta(hours=7)), "sample": True}))
        self.sleep = mock.patch.object(R.time, "sleep", lambda s: None)
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def data(self, name):
        return json.loads((self.tmp / "data" / f"{name}.json").read_text())

    def run_refresh(self, git, runner, now=NOW):
        with contextlib.redirect_stdout(io.StringIO()):
            return R.refresh(self.tmp, now, fetch=True, runner=runner, git=git)


class FreshnessTests(Base):
    def test_exactly_at_threshold_is_fresh(self):
        self.assertTrue(R.is_fresh(NOW - timedelta(hours=R.STALE_HOURS), NOW))
        self.assertFalse(R.is_fresh(NOW - timedelta(hours=R.STALE_HOURS, seconds=1), NOW))

    def test_fresh_grab_copies_x_and_runs_stories(self):
        doc = grab(NOW - timedelta(hours=2), n=5)
        runner = FakeRunner()
        run = self.run_refresh(FakeGit(json.dumps(doc)), runner)
        self.assertEqual(self.data("x")["grabbed_at"], doc["grabbed_at"])
        self.assertEqual(len(self.data("x")["posts"]), 5)
        self.assertIn("radar/stories.py", runner.ran)
        meta = self.data("meta")
        self.assertEqual(meta["x_status"], "fresh")
        self.assertEqual(meta["x_grabbed_at"], doc["grabbed_at"])
        self.assertFalse(meta["sample"])
        self.assertEqual(run["status"], "ok")
        self.assertIn("X fresh", run["note"])

    def test_grab_at_threshold_is_fresh_end_to_end(self):
        doc = grab(NOW - timedelta(hours=R.STALE_HOURS))
        run = self.run_refresh(FakeGit(json.dumps(doc)), FakeRunner())
        self.assertEqual(self.data("meta")["x_status"], "fresh")
        self.assertTrue(run["chips"][0]["ok"])

    def test_stale_grab_keeps_x_and_stories(self):
        old_x = (self.tmp / "data" / "x.json").read_bytes()
        old_stories = (self.tmp / "data" / "stories.json").read_bytes()
        doc = grab(NOW - timedelta(hours=14))
        runner = FakeRunner()
        run = self.run_refresh(FakeGit(json.dumps(doc)), runner)
        self.assertEqual((self.tmp / "data" / "x.json").read_bytes(), old_x)
        self.assertEqual((self.tmp / "data" / "stories.json").read_bytes(), old_stories)
        self.assertNotIn("radar/stories.py", runner.ran)
        # YouTube, stats, gaps and dev still run so gaps can close.
        self.assertEqual(runner.ran, ["youtube/coverage.py", "youtube/stats.py", "radar/gaps.py", "ops/devcorner.py"])
        meta = self.data("meta")
        self.assertEqual(meta["x_status"], "waiting_for_pc")
        self.assertEqual(meta["x_grabbed_at"], doc["grabbed_at"])
        self.assertEqual(run["status"], "partial")
        self.assertIn("X waiting for PC (last grab 14h ago)", run["note"])

    def test_missing_data_branch_waits_and_skips_stories(self):
        runner = FakeRunner()
        run = self.run_refresh(FakeGit(None), runner)
        self.assertNotIn("radar/stories.py", runner.ran)
        self.assertIn("youtube/coverage.py", runner.ran)
        self.assertEqual(self.data("meta")["x_status"], "waiting_for_pc")
        self.assertEqual(run["status"], "partial")
        self.assertEqual({c["label"]: c["ok"] for c in run["chips"]}["X"], False)

    def test_broken_grab_waits(self):
        run = self.run_refresh(FakeGit("{not json"), FakeRunner())
        self.assertEqual(self.data("meta")["x_status"], "waiting_for_pc")
        self.assertIn("unreadable", run["note"])

    def test_sample_x_gives_null_grabbed_at_when_branch_missing(self):
        self.run_refresh(FakeGit(None), FakeRunner())
        self.assertIsNone(self.data("meta")["x_grabbed_at"])


class StepTests(Base):
    def test_failed_step_restores_previous_file(self):
        before = (self.tmp / "data" / "youtube.json").read_bytes()

        def half_write(root):
            (root / "data" / "youtube.json").write_text('{"generated_at": "2026-')  # truncated
            return 1, "boom"

        runner = FakeRunner({"youtube/coverage.py": half_write})
        run = self.run_refresh(FakeGit(json.dumps(grab(NOW))), runner)
        self.assertEqual((self.tmp / "data" / "youtube.json").read_bytes(), before)
        self.assertEqual(run["status"], "partial")
        self.assertIn("YouTube", run["note"])

    def test_exit_zero_with_invalid_output_is_restored(self):
        before = (self.tmp / "data" / "stats.json").read_bytes()

        def bad(root):
            (root / "data" / "stats.json").write_text('{"generated_at": "2026-10-16T11:07:00Z"}')  # missing keys
            return 0, "done"

        with contextlib.redirect_stdout(io.StringIO()):
            ok = R.run_step(self.tmp, R.STEPS["Stats"], FakeRunner({"youtube/stats.py": bad}))
        self.assertFalse(ok)
        self.assertEqual((self.tmp / "data" / "stats.json").read_bytes(), before)

    def test_stray_new_file_is_removed_on_failure(self):
        def junk(root):
            (root / "data" / "junk.json").write_text("{}")
            return 2, ""

        with contextlib.redirect_stdout(io.StringIO()):
            ok = R.run_step(self.tmp, R.STEPS["Gaps"], FakeRunner({"radar/gaps.py": junk}))
        self.assertFalse(ok)
        self.assertFalse((self.tmp / "data" / "junk.json").exists())

    def test_missing_script_is_a_failed_step(self):
        (self.tmp / "radar" / "gaps.py").unlink()
        runner = FakeRunner()
        with contextlib.redirect_stdout(io.StringIO()):
            ok = R.run_step(self.tmp, R.STEPS["Gaps"], runner)
        self.assertFalse(ok)
        self.assertEqual(runner.ran, [])

    def test_runner_exception_does_not_crash(self):
        def explode(root):
            raise RuntimeError("bad")

        run = self.run_refresh(FakeGit(None), FakeRunner({"ops/devcorner.py": explode}))
        self.assertIn("Dev", run["note"])

    def test_secret_env_values_are_redacted(self):
        with mock.patch.dict(R.os.environ, {"YOUTUBE_API_KEY": "abc123secretvalue"}):
            self.assertNotIn("abc123secretvalue", R.redact("key=abc123secretvalue"))


class StatusAndLogTests(Base):
    def test_status_logic(self):
        self.assertEqual(R.run_status({"X": True, "Dev": True}), "ok")
        self.assertEqual(R.run_status({"X": False, "Dev": True}), "partial")
        self.assertEqual(R.run_status({"X": False, "Dev": False}), "fail")

    def test_everything_failed_is_fail(self):
        fail = lambda root: (1, "")
        runner = FakeRunner({s: fail for s in ("youtube/coverage.py", "youtube/stats.py", "radar/gaps.py", "ops/devcorner.py")})
        run = self.run_refresh(FakeGit(None), runner)
        self.assertEqual(run["status"], "fail")
        with mock.patch.object(R, "refresh", return_value=run), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(R.main([]), 1)

    def test_chips_order(self):
        run = self.run_refresh(FakeGit(None), FakeRunner())
        self.assertEqual([c["label"] for c in run["chips"]], ["X", "Stories", "YouTube", "Stats", "Gaps", "Dev"])

    def test_runlog_drops_sample_and_caps_at_60_newest_first(self):
        self.assertTrue(self.data("runlog")["sample"])
        for i in range(65):
            self.run_refresh(FakeGit(None), FakeRunner(), now=NOW + timedelta(hours=12 * i))
        log = self.data("runlog")
        self.assertFalse(log["sample"])
        self.assertEqual(len(log["runs"]), 60)
        ats = [r["at"] for r in log["runs"]]
        self.assertEqual(ats, sorted(ats, reverse=True))
        self.assertEqual(ats[0], R.iso(NOW + timedelta(hours=12 * 64)))
        self.assertNotIn("2026-10-16T11:07:00Z", [r["at"] for r in log["runs"] if "Sample" in r.get("note", "")])

    def test_outputs_match_schema(self):
        self.run_refresh(FakeGit(json.dumps(grab(NOW))), FakeRunner())
        for name in ("runlog", "meta", "x"):
            self.assertEqual(R.validate(self.tmp, name, self.data(name)), [], name)

    def test_gap_counts_in_note(self):
        def gaps(root):
            radar = {"generated_at": "2026-10-16T11:07:00Z",
                     "stories": [{"gap": {"flag": "GAP"}}, {"gap": {"flag": "GAP"}}, {"gap": {"flag": "CLOSING"}}]}
            (root / "data" / "radar.json").write_text(json.dumps(radar))
            return 0, ""

        with mock.patch.object(R, "validate", return_value=[]):
            run = self.run_refresh(FakeGit(None), FakeRunner({"radar/gaps.py": gaps}))
        self.assertIn("2 gaps open, 1 closing", run["note"])

    def test_record_fail_keeps_last_updated_at(self):
        with contextlib.redirect_stdout(io.StringIO()):
            R.record_fail(self.tmp, NOW, "Validation failed; restored previous data")
        self.assertEqual(self.data("runlog")["runs"][0]["status"], "fail")
        self.assertEqual(self.data("meta")["updated_at"], "2026-10-16T11:07:00Z")


class NextRefreshTests(unittest.TestCase):
    def nxt(self, s):
        return R.iso(R.next_refresh_at(R.parse_iso(s)))

    def test_morning_and_evening(self):
        # CDT is UTC-5: 6:07 AM = 11:07Z, 6:07 PM = 23:07Z
        self.assertEqual(self.nxt("2026-10-16T10:00:00Z"), "2026-10-16T11:07:00Z")
        self.assertEqual(self.nxt("2026-10-16T11:07:00Z"), "2026-10-16T23:07:00Z")  # strictly after
        self.assertEqual(self.nxt("2026-10-16T23:30:00Z"), "2026-10-17T11:07:00Z")

    def test_dst_end_nov_1_2026(self):
        # Sat Oct 31 6:07 PM CDT = 23:07Z; Sun Nov 1 is CST (UTC-6): 6:07 AM = 12:07Z, 6:07 PM = 00:07Z next day
        self.assertEqual(self.nxt("2026-10-31T23:30:00Z"), "2026-11-01T12:07:00Z")
        self.assertEqual(self.nxt("2026-11-01T12:30:00Z"), "2026-11-02T00:07:00Z")

    def test_dst_start_mar_8_2026(self):
        self.assertEqual(self.nxt("2026-03-08T01:00:00Z"), "2026-03-08T11:07:00Z")  # 6:07 AM CDT


if __name__ == "__main__":
    unittest.main()
