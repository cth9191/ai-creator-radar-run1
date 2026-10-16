"""Group raw X posts (data/x.json) into stories (data/stories.json).

Run from the repo root:  python3 radar/stories.py
Optional:                python3 radar/stories.py --x path/to/x.json --out path/to/stories.json

Standard library only. Exit 0 means data/stories.json was written; anything else means
the step failed and the previous file was left untouched (we write to a temp file and
rename it into place).

How grouping works (deterministic, no randomness, no network):

1. Clean each post (drop URLs, @mentions, emoji) and pull out *terms*:
     tier 1  versioned models/products ("GPT-5.5", "Claude Opus 4.7", "o3") and $tickers
     tier 2  known products ("Claude Code", "NotebookLM"), capitalized phrases
             ("Deep Research"), hashtags
     tier 3  known companies/people ("OpenAI", "Sam Altman"), single capitalized words
             and acronyms ("MCP")
   plus lowercase content words, which only help similarity, never anchor a story.
   Terms that are just the grab's own search queries drop to the last tier, so a
   query like "Claude" does not swallow every post.
2. Anchor pass: walk the terms by tier, then by how many posts use them. A term
   shared by 2+ unassigned posts claims those posts as a cluster.
3. Leftover posts join the most similar cluster (cosine over idf-weighted terms) or
   stay alone.
4. Near-duplicate clusters (cosine >= MERGE_COS) are merged, best pair first.
5. Singletons with little engagement are dropped. The rest are ranked and capped.

Engagement of a post = likes + 2*reposts + replies + 2*quotes
(a repost or quote spreads the story further than a like, so it counts double).
Velocity of a story = engagement / hours between its first post and the grab (min 1h).
Rank = log(1 + recent engagement) + 0.5*log(1 + velocity) + 0.2*log(1 + posts),
where recent engagement weights posts in the last 12 hours fully and halves the
weight of older posts for every further 12 hours.
"""
import argparse
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_X = ROOT / "data" / "x.json"
DEFAULT_OUT = ROOT / "data" / "stories.json"

MAX_STORIES = 12
MIN_SINGLETON_ENGAGEMENT = 1500   # a story made of one post needs at least this much
RECENT_HOURS = 12.0
MERGE_COS = 0.45                  # merge clusters this similar
ATTACH_COS = 0.22                 # a leftover post joins a cluster this similar
GENERIC_SHARE = 0.5               # a term in more than half the posts can't anchor (when 10+ posts)

TIER_WEIGHT = {1: 3.0, 2: 2.0, 3: 1.2, 4: 0.6, 5: 0.25}

# Known names. kind: product (tier 2) or org/person (tier 3). Longest match wins.
LEXICON = {
    "product": [
        "Claude Code", "Claude Agent SDK", "Agent SDK", "Claude Desktop", "Claude Cowork", "Cowork",
        "ChatGPT", "ChatGPT Atlas", "Codex", "Codex CLI", "Gemini CLI", "NotebookLM", "AI Studio",
        "Deep Research", "Operator", "Sora", "Veo", "Nano Banana", "Genie", "Jules", "Antigravity",
        "Midjourney", "Runway", "Kling", "Suno", "Flux", "Stable Diffusion", "Copilot",
        "GitHub Copilot", "Cursor", "Windsurf", "Replit", "Lovable", "Bolt", "v0", "Devin",
        "Perplexity Comet", "Comet", "MCP", "Model Context Protocol", "Ollama", "LM Studio",
        "n8n", "Zapier", "Manus", "Grok", "Llama", "Gemma", "Qwen", "Kimi", "GLM", "Phi",
        "Claude", "Gemini", "Opus", "Sonnet", "Haiku", "Stargate", "Optimus", "Vision Pro",
        "Apple Intelligence", "Siri", "Alexa",
    ],
    "org": [
        "OpenAI", "Anthropic", "Google", "Google DeepMind", "DeepMind", "Meta", "xAI",
        "Microsoft", "Apple", "Nvidia", "Amazon", "AWS", "Mistral", "DeepSeek", "Alibaba",
        "Hugging Face", "Perplexity", "Vercel", "GitHub", "Figma", "Notion", "Stripe", "Groq",
        "Cerebras", "TSMC", "SoftBank", "Tesla", "Neuralink", "Cognition",
        "Thinking Machines", "Safe Superintelligence", "Character.AI", "Black Forest Labs",
        "Stability AI", "Moonshot", "Zhipu", "MiniMax", "ElevenLabs", "Scale AI", "Oracle",
        "AMD", "Intel", "Samsung", "ByteDance", "Baidu", "Tencent", "Salesforce", "IBM",
        "Sam Altman", "Dario Amodei", "Demis Hassabis", "Elon Musk", "Jensen Huang",
        "Mark Zuckerberg", "Satya Nadella", "Sundar Pichai", "Andrej Karpathy", "Boris Cherny",
    ],
}

# Model families: "gpt 5", "claude-4.7", "qwen3", "o3" are versioned terms even in lowercase.
FAMILIES = ("gpt", "claude", "gemini", "gemma", "llama", "grok", "qwen", "deepseek", "mistral",
            "sora", "veo", "kling", "midjourney", "phi", "opus", "sonnet", "haiku", "kimi", "glm",
            "flux", "codex", "r", "v", "o", "iphone", "ios", "m", "h", "b", "gb")
SUFFIXES = ("pro", "mini", "flash", "ultra", "turbo", "max", "nano", "lite", "coder", "instruct",
            "thinking", "high", "preview", "plus", "omni", "codex", "fast", "opus", "sonnet", "haiku")

STOP_CAPS = set("""
a an the this that these those just new breaking today tonight yesterday tomorrow we i it its it's
what how why when where who which here there huge big wow omg so and but or if you your my our their
is are was were be been not no yes holy insane crazy finally introducing announcing announced thread
update updates check look can will did does do has have had let lets let's in on at for with from to
of by every everyone people some all most literally honestly imagine wait also still now then they he
she real sample hot take thoughts thanks thank please one two three first last next day week month year
monday tuesday wednesday thursday friday saturday sunday january february march april may june july
august september october november december ai llm llms api apis agi gpu gpus ceo cto rt imo lol tldr
tl dr fyi pc agent agents model models video videos youtube x twitter tweet post posts news great good
bad best better worst major quick quickly very really much more less many few big small after before
again only even about over under into out up down off then than too own same other another such each
both any via per vs versus top note btw yeah nope ok okay hey hi hello welcome meet open source
""".split())

STOP_WORDS = STOP_CAPS | set("""
like just dont don't doesnt isnt cant won't wont gonna wanna going thing things stuff people way ways
make makes made making use used using get gets got getting know think thinks see seen saw say says said
want wants need needs time times right left still well actually basically pretty kind sort lot lots
being been having does done doing come comes came give gives gave take takes took look looks looked
work works worked working something anything nothing everything someone anyone everybody
would could should might must shall will just also there their they them then than that this with
from your have what when where which while about into over under after before because since until
""".split())

# Action words that make a title readable ("GPT-5.5 launch"). First match by priority wins.
ACTIONS = [
    ("leak", ("leak", "leaked", "leaks")),
    ("outage", ("outage", "outages", "downtime")),
    ("acquisition", ("acquires", "acquired", "acquisition", "buys", "bought")),
    ("funding", ("raises", "raised", "funding", "valuation")),
    ("lawsuit", ("lawsuit", "sued", "sues", "court")),
    ("open weights", ("open-weights", "open-weight", "weights", "open-sourced", "opensource")),
    ("earnings", ("earnings", "revenue", "guidance", "quarter", "beats")),
    ("launch", ("launch", "launches", "launched", "ships", "shipped", "released", "release",
                "releases", "available", "rolling", "rollout", "drops", "dropped", "live", "out")),
    ("pricing", ("pricing", "price", "prices", "cheaper")),
    ("benchmarks", ("benchmark", "benchmarks", "swe-bench", "arc-agi", "evals", "leaderboard")),
    ("update", ("update", "updated", "upgrade", "changelog", "version")),
    ("demo", ("demo", "demos", "preview", "beta")),
    ("paper", ("paper", "research", "arxiv")),
]

URL_RE = re.compile(r"https?://\S+|www\.\S+")
MENTION_RE = re.compile(r"(?<!\w)@\w+")
NON_TEXT_RE = re.compile(r"[^\w\s$#.,:;!?'’\-/&+%]", re.UNICODE)
TICKER_RE = re.compile(r"(?<![\w$])\$([A-Za-z]{1,5})\b")
HASHTAG_RE = re.compile(r"(?<!\w)#([A-Za-z][A-Za-z0-9_]{2,})")
_fam = "|".join(sorted(FAMILIES, key=len, reverse=True))
_suf = "|".join(SUFFIXES)
_num = r"([vr]?\d{1,2}(?:\.\d{1,2})?[a-z]?)"
PARENTS = ("Claude", "Gemini", "Meta Llama", "Google Gemini")  # "Claude Opus 4.7": key opus-4.7, shown in full
_par = "|".join(PARENTS)
# "Claude Code 2.1", "Gemini CLI 1.0": multiword products with a version
_multi = "|".join(re.escape(n) for n in sorted((n for n in LEXICON["product"] if " " in n), key=len, reverse=True))
PRODUCT_VERSION_RE = re.compile(rf"(?<![\w.])({_multi})[ -]v?(\d{{1,2}}(?:\.\d{{1,2}}){{0,2}})(?![\w.]*\d)", re.I)
FAMILY_VERSION_RE = re.compile(
    rf"(?<![\w.])(?:({_par})[ -])?({_fam})[- ]?{_num}(?:[- ]({_suf}))?(?![\w.]*\d)", re.I)
CAP_VERSION_RE = re.compile(
    rf"(?<![\w.])()([A-Z][A-Za-z]{{1,15}})[- ]{_num}(?:[- ]({_suf}))?\b(?![.,]?\d)")
VERSION_WORD_STOP = STOP_CAPS | {"top", "step", "part", "chapter", "episode", "level", "season", "page",
                                 "hour", "hours", "minute", "minutes", "ep", "no", "number", "version",
                                 "under", "over", "only", "about", "around", "with", "and", "for", "in",
                                 "of", "at", "the", "to", "by", "series", "gen", "round", "phase", "tier"}
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'’.\-]*[A-Za-z0-9]|[A-Za-z]")


def _lex_patterns():
    items = []
    for kind, names in LEXICON.items():
        for name in names:
            items.append((name, kind))
    items.sort(key=lambda t: (-len(t[0]), t[0]))
    pats = []
    for name, kind in items:
        pats.append((re.compile(r"(?<![\w.])" + re.escape(name) + r"(?![\w])", re.I), name, kind))
    return pats


LEX_PATTERNS = _lex_patterns()


# ---------------------------------------------------------------- helpers

def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def engagement(post):
    """likes + 2*reposts + replies + 2*quotes."""
    def n(k):
        v = post.get(k) or 0
        return v if isinstance(v, int) and v > 0 else 0
    return n("likes") + 2 * n("reposts") + n("replies") + 2 * n("quotes")


def clean_text(text):
    text = URL_RE.sub(" ", text or "")
    text = MENTION_RE.sub(" ", text)
    text = text.replace("’", "'")
    text = NON_TEXT_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "story"


def version_key(family, num, suffix):
    key = f"{family.lower()}-{num.lower()}"
    if family.lower() in ("o",):
        key = f"o{num.lower()}"
    return key + (f"-{suffix.lower()}" if suffix else "")


def version_display(family, num, suffix):
    fam = family
    low = family.lower()
    if low == "gpt":
        fam = "GPT"
    elif low == "o":
        disp = f"o{num}"
        return disp + (f"-{suffix.lower()}" if suffix else "")
    elif low in ("glm", "ios", "gb"):
        fam = low.upper() if low != "ios" else "iOS"
    elif fam.islower() or fam.isupper():
        fam = fam[:1].upper() + fam[1:].lower()
    if low == "deepseek":
        fam = "DeepSeek"
    sep = "-" if low in ("gpt",) else " "
    if low in ("r", "v", "m", "h", "b", "qwen", "kimi") or (len(low) == 1):
        sep = ""
    if num[:1] in "vr" and num[1:2].isdigit():
        num = num[0].upper() + num[1:]
    disp = f"{fam}{sep}{num}"
    return disp + (f" {suffix.capitalize()}" if suffix else "")


# ---------------------------------------------------------------- term extraction

def extract_terms(text, query_terms=frozenset()):
    """Return {term_key: (tier, display)} and the list of content words for one post."""
    terms = {}
    raw = clean_text(text)
    masked = raw

    def add(key, tier, display):
        if key in query_terms:
            tier = 4
        old = terms.get(key)
        if old is None or tier < old[0]:
            terms[key] = (tier, display)

    def mask(m):  # blank out a matched span, keeping string length so offsets still line up
        nonlocal masked
        s, e = m.span()
        masked = masked[:s] + "|" + " " * (e - s - 1) + masked[e:]

    # tier 1: versioned names (searched in order, each match blanked out for the next)
    for m in PRODUCT_VERSION_RE.finditer(masked):
        name = next(n for n in LEXICON["product"] if n.lower() == m.group(1).lower())
        add(f"{name.lower()} {m.group(2)}".replace(" ", "-"), 1, f"{name} {m.group(2)}")
        add(name.lower(), 2, name)
        mask(m)
    for rx in (FAMILY_VERSION_RE, CAP_VERSION_RE):
        for m in rx.finditer(masked):
            parent, fam, num, suf = m.group(1), m.group(2), m.group(3), m.group(4)
            if rx is CAP_VERSION_RE and fam.lower() in VERSION_WORD_STOP:
                continue
            if rx is FAMILY_VERSION_RE and len(fam) == 1 and fam.lower() != "o" and not fam.isupper():
                continue  # "r1"/"m4" need a capital letter: "R1", "M4"
            if parent and parent.lower() == fam.lower():
                parent = None
            prefix = (parent.title().replace("Llama", "Llama") + " ") if parent else ""
            key = version_key(fam, num, suf)
            add(key, 1, prefix + version_display(fam, num, suf))
            if suf:
                add(version_key(fam, num, None), 1, prefix + version_display(fam, num, None))
            mask(m)
    for m in TICKER_RE.finditer(masked):
        add("$" + m.group(1).lower(), 1, "$" + m.group(1).upper())
        mask(m)
    for m in HASHTAG_RE.finditer(masked):
        tag = m.group(1).lower()
        if tag not in STOP_CAPS:
            add("#" + tag, 2, "#" + m.group(1))
        mask(m)
    # tier 2/3: known names
    for rx, name, kind in LEX_PATTERNS:
        for m in rx.finditer(masked):
            add(name.lower(), 2 if kind == "product" else 3, name)
            mask(m)
    # capitalized runs in what is left
    for chunk in re.split(r"[|.!?:;,()\"]+", masked):
        words = chunk.split()
        run = []
        start = 0
        for i, w in enumerate(words + [""]):
            w2 = w.strip("'-/&+")
            proper = bool(w2) and (w2[:1].isupper() or (w2[:1].islower() and any(c.isupper() for c in w2[1:])))
            if proper and w2.lower() not in STOP_CAPS and not w2.isdigit():
                if not run:
                    start = i
                run.append(w2)
            else:
                # a lone Titlecase word opening a sentence is usually just grammar ("Trying ...")
                if run and not (start == 0 and len(run) == 1 and run[0][1:].islower()):
                    _add_run(run, add)
                run = []
    content = []
    for w in WORD_RE.findall(raw.lower()):
        w = w.strip(".-'")
        if len(w) >= 4 and w not in STOP_WORDS and not w.isdigit():
            content.append(w)
    return terms, content


def _add_run(run, add):
    run = run[:4]
    if len(run) >= 2:
        add(" ".join(run).lower(), 2, " ".join(run))
    else:
        w = run[0]
        if len(w) >= 3 or w.isupper() and len(w) >= 2:
            if w.isupper() and len(w) > 6:
                return  # SHOUTING, not an acronym
            add(w.lower(), 3, w)


# ---------------------------------------------------------------- clustering

class Post:
    __slots__ = ("raw", "id", "at", "eng", "terms", "content", "vec")

    def __init__(self, raw, at, terms, content):
        self.raw = raw
        self.id = str(raw["id"])
        self.at = at
        self.eng = engagement(raw)
        self.terms = terms
        self.content = content
        self.vec = {}


def _cos(a, b):
    if len(a) > len(b):
        a, b = b, a
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    if not dot:
        return 0.0
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _sum_vec(posts):
    out = defaultdict(float)
    for p in posts:
        for k, v in p.vec.items():
            out[k] += v
    return dict(out)


def cluster_posts(posts):
    """Return a list of clusters (lists of Post), deterministic for a given input."""
    n = len(posts)
    df = Counter()
    for p in posts:
        df.update(p.terms.keys())
        df.update({"~" + w for w in set(p.content)})
    idf = {k: math.log((n + 1) / (c + 1)) + 1.0 for k, c in df.items()}
    for p in posts:
        vec = {}
        for k, (tier, _d) in p.terms.items():
            vec[k] = TIER_WEIGHT[tier] * idf[k]
        for w in set(p.content):
            vec["~" + w] = TIER_WEIGHT[5] * idf["~" + w]
        p.vec = vec

    # anchor pass
    tier_of = {}
    for p in posts:
        for k, (tier, _d) in p.terms.items():
            tier_of[k] = min(tier, tier_of.get(k, 9))
    anchors = sorted((k for k in tier_of if df[k] >= 2),
                     key=lambda k: (tier_of[k], -df[k], k))
    assigned = {}
    clusters = []
    for term in anchors:
        if n >= 10 and df[term] > GENERIC_SHARE * n and tier_of[term] >= 3:
            continue
        members = [p for p in posts if p.id not in assigned and term in p.terms]
        if len(members) < 2:
            continue
        for p in members:
            assigned[p.id] = len(clusters)
        clusters.append(members)

    # second pass: a post that shares a specific term (not a broad company/person name)
    # with an existing cluster joins the cluster holding most posts with that term
    for term in anchors:
        if term in _ORG_KEYS or tier_of[term] > 3 or (n >= 10 and df[term] > GENERIC_SHARE * n):
            continue
        free = [p for p in posts if p.id not in assigned and term in p.terms]
        if not free:
            continue
        holders = Counter(assigned[p.id] for p in posts if p.id in assigned and term in p.terms)
        if not holders:
            continue
        target, _cnt = sorted(holders.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        for p in free:
            assigned[p.id] = target
            clusters[target].append(p)

    # leftovers: attach to the most similar cluster, or stand alone
    vecs = [_sum_vec(c) for c in clusters]
    for p in posts:
        if p.id in assigned:
            continue
        best, best_cos = None, ATTACH_COS
        for i, v in enumerate(vecs):
            c = _cos(p.vec, v)
            if c > best_cos + 1e-12:
                best, best_cos = i, c
        if best is None:
            clusters.append([p])
            vecs.append(dict(p.vec))
        else:
            clusters[best].append(p)
            vecs[best] = _sum_vec(clusters[best])

    # merge near-duplicates, most similar pair first
    while True:
        best = None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                c = _cos(vecs[i], vecs[j])
                if c >= MERGE_COS and (best is None or c > best[0] + 1e-12):
                    best = (c, i, j)
        if best is None:
            break
        _c, i, j = best
        clusters[i] = clusters[i] + clusters[j]
        vecs[i] = _sum_vec(clusters[i])
        del clusters[j], vecs[j]
    for c in clusters:
        c.sort(key=lambda p: (p.at, p.id))
    return clusters


# ---------------------------------------------------------------- story building

def _rank_terms(cluster):
    """Cluster terms ranked by how well they name the story: tier weight x share of posts."""
    count = Counter()
    disp = defaultdict(Counter)
    tier = {}
    for p in cluster:
        for k, (t, d) in p.terms.items():
            count[k] += 1
            disp[k][d] += 1
            tier[k] = min(t, tier.get(k, 9))
    size = len(cluster)

    def score(k):
        return TIER_WEIGHT[tier[k]] * (count[k] / size)
    ranked = sorted(count, key=lambda k: (-score(k), tier[k], k))
    display = {k: sorted(disp[k].items(), key=lambda kv: (-kv[1], kv[0]))[0][0] for k in ranked}
    return ranked, display, tier, count


def _redundant(a, b):
    a2, b2 = a.replace("-", " "), b.replace("-", " ")
    return a2 in b2 or b2 in a2


def _action(cluster):
    best, best_hits = None, 0
    for label, triggers in ACTIONS:  # most posts wins; ties go to the earlier (more specific) action
        hits = sum(1 for p in cluster if _has_any(p, triggers))
        if hits > best_hits:
            best, best_hits = label, hits
    return best if best_hits >= max(1, len(cluster) * 0.3) else None


def _has_any(post, triggers):
    words = set(w.lower() for w in re.findall(r"[A-Za-z][A-Za-z\-]+", clean_text(post.raw.get("text", ""))))
    return any(t in words for t in triggers)


def _snippet(text, limit=160):
    t = clean_text(text)
    t = re.sub(r"^(breaking|just in|big news|huge|new)\s*[:\-]\s*", "", t, flags=re.I)
    t = re.sub(r"(\s#\w+)+$", "", t).strip()
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
    return t


def _post_out(p):
    raw = p.raw
    out = {"id": p.id, "url": raw["url"], "author": raw.get("author") or {"handle": "unknown"},
           "text": raw.get("text", ""), "created_at": iso(p.at),
           "likes": int(raw.get("likes") or 0), "reposts": int(raw.get("reposts") or 0)}
    for k in ("replies", "quotes", "views"):
        if isinstance(raw.get(k), int) and raw[k] >= 0:
            out[k] = raw[k]
    if raw.get("query"):
        out["query"] = str(raw["query"])
    return out


def build_story(cluster, now):
    ranked, display, tier, count = _rank_terms(cluster)
    named = [k for k in ranked if tier[k] <= 3] or [k for k in ranked]
    primary = named[0] if named else None
    if primary is None:  # no terms at all: fall back to the top post's words
        top = max(cluster, key=lambda p: (p.eng, p.id))
        words = [w for w in top.content[:3]] or ["ai", "news"]
        primary_disp = " ".join(words).title()
        primary = slugify(primary_disp)
        secondary = []
    else:
        # prefer a longer variant used by most posts: "Gemini 3 Pro" over "Gemini 3"
        for k in named[1:]:
            if tier[k] == tier[primary] and k.startswith(primary + "-") and count[k] >= 0.6 * count[primary]:
                primary = k
                break
        primary_disp = display[primary]
        secondary = [k for k in named[1:] if not _redundant(k, primary) and k != primary
                     and (count[k] >= 2 or len(cluster) < 3)]

    # an organisation that frames the primary term, e.g. "OpenAI" for "GPT-5.5"
    org = None
    for k in secondary:
        if tier[k] == 3 and count[k] >= max(1, 0.3 * len(cluster)) and k in _ORG_KEYS:
            org = display[k]
            break
    action = _action(cluster)

    show_org = org and not _redundant(org.lower(), primary) and len(primary_disp.split()) < 3
    title = " ".join(([org] if show_org else []) + [primary_disp])
    if not action:
        # no clear action word: use the topic word most posts share, e.g. "Claude Code plugins"
        forms = defaultdict(Counter)
        for p in cluster:
            for w in set(p.content):
                forms[w.rstrip("s")][w] += 1
        title_low = title.lower()
        for stem, c in sorted(forms.items(), key=lambda kv: (-sum(kv[1].values()), kv[0])):
            if sum(c.values()) < max(2, 0.5 * len(cluster)):
                break
            word = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            if stem not in title_low and len(stem) >= 4:
                action = word
                break
    if action:
        title += f" {action}"

    q_words = title.split()
    if len(q_words) < 2:
        extra = next((display[k] for k in secondary), None)
        if extra is None:
            words = Counter(w for p in cluster for w in set(p.content))
            extra = next((w for w, _ in sorted(words.items(), key=lambda kv: (-kv[1], kv[0]))
                          if w not in primary_disp.lower()), "news")
        q_words += extra.split()
    search_query = " ".join(w.lstrip("$#") for w in q_words[:5])

    keywords = []
    for k in [primary] + secondary:
        d = display.get(k, primary_disp)
        if d not in keywords:
            keywords.append(d)
        if len(keywords) >= 6:
            break
    if len(keywords) < 3:
        words = Counter(w for p in cluster for w in set(p.content))
        for w, c in sorted(words.items(), key=lambda kv: (-kv[1], kv[0])):
            if c < 2 and len(cluster) >= 2:
                break
            if not any(w in x.lower() or x.lower() in w for x in keywords):
                keywords.append(w)
            if len(keywords) >= 4:
                break

    total = sum(p.eng for p in cluster)
    first = cluster[0]
    hours = max(1.0, (now - first.at).total_seconds() / 3600.0)
    velocity = total / hours
    recent = 0.0
    for p in cluster:
        age = max(0.0, (now - p.at).total_seconds() / 3600.0)
        w = 1.0 if age <= RECENT_HOURS else 0.5 ** ((age - RECENT_HOURS) / RECENT_HOURS)
        recent += p.eng * w
    rank = math.log1p(recent) + 0.5 * math.log1p(velocity) + 0.2 * math.log1p(len(cluster))

    top = sorted(cluster, key=lambda p: (-p.eng, p.at, p.id))[:3]
    lead = top[0]
    handle = (lead.raw.get("author") or {}).get("handle", "")
    summary = _snippet(lead.raw.get("text", ""))
    if handle:
        summary = f"@{handle}: {summary}"

    story = {
        "id": slugify(primary_disp if primary else title),
        "title": title,
        "summary": summary,
        "keywords": keywords,
        "search_query": search_query,
        "first_seen": iso(first.at),
        "post_ids": [p.id for p in cluster],
        "post_count": len(cluster),
        "engagement": int(total),
        "velocity": round(velocity, 1),
        "top_posts": [_post_out(p) for p in top],
        "first_post": {"id": first.id, "url": first.raw["url"],
                       "handle": (first.raw.get("author") or {}).get("handle", ""),
                       "created_at": iso(first.at)},
        "rank_score": round(rank, 3),
    }
    alt_ids = [slugify(f"{primary_disp} {display[k]}") for k in secondary[:2]]
    return story, alt_ids


_ORG_KEYS = {n.lower() for n in LEXICON["org"]}


def build_stories(doc):
    if not isinstance(doc, dict) or not isinstance(doc.get("posts"), list):
        raise ValueError("x.json has no posts list")
    queries = doc.get("queries") or []
    query_terms = set()
    for q in queries:
        if isinstance(q, str):
            ql = q.lower().strip()
            if ql and " " not in ql:  # a one-word query ("Claude") would otherwise name every story
                query_terms.add(ql)

    seen = set()
    posts = []
    for raw in doc["posts"]:
        if not isinstance(raw, dict):
            continue
        pid, url = raw.get("id"), raw.get("url")
        at = parse_time(raw.get("created_at"))
        if pid is None or str(pid) in seen or not isinstance(url, str) or not url.startswith("https://") or at is None:
            continue
        seen.add(str(pid))
        terms, content = extract_terms(raw.get("text", ""), frozenset(query_terms))
        posts.append(Post(raw, at, terms, content))
    if not posts:
        raise ValueError("x.json has no usable posts")
    posts.sort(key=lambda p: (p.at, p.id))

    now = parse_time(doc.get("grabbed_at")) or max(p.at for p in posts)
    now = max(now, max(p.at for p in posts))

    clusters = cluster_posts(posts)
    # keep clusters that name something (a model, product, company, phrase...) and are
    # either 2+ posts or one post with real engagement
    clusters = [c for c in clusters
                if any(t <= 3 for p in c for (t, _d) in p.terms.values())
                and (len(c) >= 2 or sum(p.eng for p in c) >= MIN_SINGLETON_ENGAGEMENT)]
    built = [build_story(c, now) for c in clusters]
    built.sort(key=lambda sa: (-sa[0]["rank_score"], sa[0]["id"]))
    built = built[:MAX_STORIES]

    used = set()
    stories = []
    for story, alts in built:
        sid = story["id"]
        if sid in used:
            sid = next((a for a in alts if a not in used), None) or sid
            k = 2
            base = sid
            while sid in used:
                sid = f"{base}-{k}"
                k += 1
        used.add(sid)
        story["id"] = sid
        stories.append(story)
    return stories, now


def write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--x", default=str(DEFAULT_X), help="input x.json")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output stories.json")
    args = ap.parse_args(argv)
    try:
        doc = json.loads(Path(args.x).read_text(encoding="utf-8"))
        stories, now = build_stories(doc)
        out = {
            "generated_at": iso(datetime.now(timezone.utc)),
            "x_grabbed_at": iso(parse_time(doc.get("grabbed_at")) or now),
            "stories": stories,
        }
        if doc.get("sample"):
            out = {"sample": True, **out}
        write_json_atomic(args.out, out)
    except Exception as e:  # any failure leaves the old file in place
        print(f"stories: FAILED: {e}", file=sys.stderr)
        return 1
    print(f"stories: {len(stories)} stories from {len(doc['posts'])} posts -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
