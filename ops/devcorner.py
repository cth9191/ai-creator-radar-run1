"""Claude Dev Corner data: the latest Claude Code releases. Python standard library only.

    python3 ops/devcorner.py      # writes data/devcorner.json, exit 1 on failure

Source 1: GitHub REST releases for anthropics/claude-code (unauthenticated; uses GITHUB_TOKEN
          from the environment when present, never printed).
Source 2 (fallback, e.g. when a sandbox only allows its own repo on api.github.com):
          the public CHANGELOG.md on raw.githubusercontent.com for the notes, plus the npm
          registry for each version's publish time.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "devcorner.json"

RELEASES_API = "https://api.github.com/repos/anthropics/claude-code/releases?per_page=8"
CHANGELOG_URL = "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"
NPM_URL = "https://registry.npmjs.org/@anthropic-ai/claude-code"
TAG_URL = "https://github.com/anthropics/claude-code/releases/tag/{tag}"
USER_AGENT = "ai-creator-radar (+https://github.com/cth9191/ai-creator-radar)"
MAX_RELEASES = 8
MAX_HIGHLIGHTS = 5
MAX_CHARS = 120
TIMEOUT = 25

sys.path.insert(0, str(ROOT))
from ops.refresh import iso, parse_iso, validate, write_json  # noqa: E402


# ---------------------------------------------------------------- markdown -> highlights

def strip_markdown(line: str) -> str:
    s = line.strip()
    s = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", s)            # list marker
    s = re.sub(r"^\[[ xX]\]\s+", "", s)                          # task box
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)              # images
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)               # links
    s = re.sub(r"<[^>]+>", "", s)                                # html tags
    s = re.sub(r"`+([^`]*)`+", r"\1", s)                         # code
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)                    # bold
    s = re.sub(r"(?<![\w*])([*_])(?!\s)(.+?)(?<!\s)\1(?![\w*])", r"\2", s)  # italics
    s = re.sub(r"\s+", " ", s).strip()
    return s


def truncate(text: str, limit: int = MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut[limit // 2:]:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:.-") + "…"


def _rank(text: str) -> int:
    t = text.lower()
    if t.startswith(("added", "new", "introduc", "launch")):
        return 0
    if t.startswith(("improved", "changed", "updated", "faster", "better")):
        return 1
    return 2


def extract_highlights(body: str, limit: int = MAX_HIGHLIGHTS) -> list:
    """3-5 short plain-text lines from a release body. Prefers list items, new features first."""
    bullets, others = [], []
    for raw in (body or "").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ">", "|", "```", "---", "===")):
            continue
        text = strip_markdown(line)
        if len(text) < 4 or text.endswith(":") or re.fullmatch(r"[\W_]+", text):
            continue
        (bullets if re.match(r"^(?:[-*+]|\d+[.)])\s+", line) else others).append(text)
    pool = bullets or others
    ranked = sorted(enumerate(pool), key=lambda p: (_rank(p[1]), p[0]))
    picked = sorted(ranked[:limit], key=lambda p: (_rank(p[1]), p[0]))
    return [truncate(t) for _, t in picked]


# ---------------------------------------------------------------- sources

def http_get(url: str, accept: str = "application/json") -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return res.read()


def from_github(fetch=http_get) -> list:
    items = json.loads(fetch(RELEASES_API, "application/vnd.github+json"))
    if not isinstance(items, list):
        raise ValueError("unexpected releases response")
    out = []
    for r in items:
        if r.get("draft") or not r.get("tag_name") or not r.get("published_at"):
            continue
        url = r.get("html_url") or TAG_URL.format(tag=r["tag_name"])
        out.append({
            "tag": r["tag_name"],
            "name": (r.get("name") or r["tag_name"]).strip(),
            "published_at": iso(parse_iso(r["published_at"])),
            "url": url if url.startswith("https://") else TAG_URL.format(tag=r["tag_name"]),
            "highlights": extract_highlights(r.get("body") or ""),
        })
    return out


def parse_changelog(text: str) -> list:
    """[(version, body)] from a '## 1.2.3' sectioned CHANGELOG, newest first as written."""
    sections = []
    for m in re.finditer(r"^##\s+v?(\d+\.\d+\.\d+[\w.\-]*)\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S):
        sections.append((m.group(1), m.group(2)))
    return sections


def from_changelog(fetch=http_get) -> list:
    sections = parse_changelog(fetch(CHANGELOG_URL, "text/plain").decode("utf-8", "replace"))
    times = json.loads(fetch(NPM_URL)).get("time", {})
    out = []
    for version, body in sections:
        if version not in times:
            continue
        tag = f"v{version}"
        out.append({
            "tag": tag,
            "name": tag,
            "published_at": iso(parse_iso(times[version])),
            "url": TAG_URL.format(tag=tag),
            "highlights": extract_highlights(body),
        })
        if len(out) >= MAX_RELEASES:
            break
    return out


def build(now: datetime, fetch=http_get) -> dict:
    releases, errors = [], []
    for source in (from_github, from_changelog):
        try:
            releases = source(fetch)
        except Exception as e:  # network, HTTP 403, bad JSON...
            errors.append(f"{source.__name__}: {type(e).__name__}: {str(e)[:120]}")
            continue
        if releases:
            break
        errors.append(f"{source.__name__}: no releases")
    if not releases:
        raise RuntimeError("; ".join(errors) or "no releases found")
    for e in errors:
        print(f"note: {e} (used fallback)")
    releases.sort(key=lambda r: r["published_at"], reverse=True)
    return {"sample": False, "generated_at": iso(now), "releases": releases[:MAX_RELEASES], "news": []}


def main() -> int:
    try:
        doc = build(datetime.now(timezone.utc))
    except Exception as e:
        print(f"devcorner: failed: {e}")
        return 1
    problems = validate(ROOT, "devcorner", doc)
    if problems:
        print("devcorner: output does not match schema: " + "; ".join(problems[:3]))
        return 1
    write_json(OUT, doc)
    latest = doc["releases"][0]
    print(f"devcorner: {len(doc['releases'])} releases, latest {latest['tag']} ({latest['published_at']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
