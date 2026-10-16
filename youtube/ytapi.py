"""Tiny YouTube Data API v3 client (stdlib only), shared by coverage.py and stats.py.

The API key is attached to requests by the routine's network proxy. This module never
adds a key parameter or header, never reads one from the environment or files, and
scrubs anything that looks like `key=...` out of every message it produces.
"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://www.googleapis.com/youtube/v3/"
TIMEOUT = 25
_KEY_RE = re.compile(r"(?i)\b(key|api_key|apikey|access_token|token)=[^&\s\"'<>]*")
_GOOGLE_KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")


class ApiError(Exception):
    """A YouTube API call failed. str(err) is safe to print (no URL query, no key)."""


def sanitize(text):
    """Remove anything key-like from text before it is logged."""
    text = _KEY_RE.sub(lambda m: m.group(1) + "=REDACTED", str(text))
    return _GOOGLE_KEY_RE.sub("REDACTED", text)


class Client:
    """Counts calls per endpoint so callers can enforce and report their budget."""

    def __init__(self, base=API, timeout=TIMEOUT):
        self.base = base
        self.timeout = timeout
        self.calls = {}

    def url(self, endpoint, params):
        clean = {k: v for k, v in params.items() if v is not None and k.lower() not in ("key", "api_key", "apikey")}
        return self.base + endpoint + "?" + urllib.parse.urlencode(clean)

    def get(self, endpoint, **params):
        self.calls[endpoint] = self.calls.get(endpoint, 0) + 1
        req = urllib.request.Request(self.url(endpoint, params), headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise ApiError(sanitize(f"{endpoint}: HTTP {e.code} {_reason(e)}")) from None
        except urllib.error.URLError as e:
            raise ApiError(sanitize(f"{endpoint}: network error {getattr(e, 'reason', e)}")) from None
        except (ValueError, OSError) as e:
            raise ApiError(sanitize(f"{endpoint}: bad response ({type(e).__name__})")) from None


def _reason(err):
    """Short reason from a Google error body, e.g. 'quotaExceeded: The request cannot...'."""
    try:
        body = json.loads(err.read().decode("utf-8"))
        e = body.get("error", {})
        reasons = [x.get("reason") for x in e.get("errors", []) if x.get("reason")]
        msg = (e.get("message") or "").strip()
        out = ", ".join(reasons)
        if msg:
            out = f"{out}: {msg}" if out else msg
        return out[:200] or (err.reason or "")
    except Exception:
        return str(getattr(err, "reason", "") or "")


def chunks(items, n=50):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)


def to_int(v, default=0):
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return default


def https(url):
    return url if isinstance(url, str) and url.startswith("https://") else None


def write_json_atomic(path, doc):
    """Write doc to path via temp file + rename, so a crash never leaves a half file."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def fail(msg, code=1):
    print(sanitize(msg).splitlines()[0] if msg else "failed", file=sys.stderr)
    return code
