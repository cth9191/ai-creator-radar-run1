"""Fail if any tracked file looks like it holds a key, token or cookie.

This repo is public. Keys live in the environment (the YouTube key is attached by the
network proxy), never in files. Run: python3 shell/tools/no_secrets.py
"""
import re
import subprocess
import sys

PATTERNS = {
    "Google API key": r"AIza[0-9A-Za-z_\-]{35}",
    "GitHub token": r"\b(ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z]{36}\b|github_pat_[0-9A-Za-z_]{40,}",
    "Anthropic key": r"sk-ant-[0-9A-Za-z_\-]{20,}",
    "OpenAI-style key": r"\bsk-[0-9A-Za-z]{32,}\b",
    "X session cookie": r"\b(auth_token|ct0|twid|kdt)\s*[=:]\s*[\"']?[0-9A-Za-z%]{16,}",
    "Cookie header": r"(?i)^\s*cookie\s*:\s*\S+=\S+",
    "Bearer token": r"(?i)authorization\s*[:=]\s*[\"']?bearer\s+[0-9A-Za-z%._\-]{30,}",
    "API key header": r"(?i)x-goog-api-key\s*[:=]\s*[\"']?[0-9A-Za-z_\-]{20,}",
    "Private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}
SKIP = ("shell/tools/no_secrets.py",)


def main():
    files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], capture_output=True, text=True, check=True).stdout.split()
    hits = []
    for path in files:
        if path in SKIP or path.endswith((".png", ".jpg", ".ico", ".woff2")):
            continue
        try:
            text = open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for name, pat in PATTERNS.items():
            for m in re.finditer(pat, text, re.M):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{path}:{line} looks like a {name}")
    for h in hits:
        print("FAIL", h)
    print(f"{len(files)} files scanned, {len(hits)} possible secrets")
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    main()
