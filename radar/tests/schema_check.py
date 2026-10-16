"""Validate against shell/schema/ with jsonschema when it is installed, else check key fields."""
import json
from pathlib import Path

SCHEMAS = Path(__file__).resolve().parents[2] / "shell" / "schema"

try:
    from jsonschema import Draft202012Validator
except ImportError:  # CI's worker-test job runs with the standard library only
    Draft202012Validator = None

REQUIRED = {
    "stories": ("stories", ("id", "title", "search_query", "first_seen", "post_count", "engagement")),
    "radar": ("stories", ("id", "title", "x", "youtube", "gap", "trail")),
    "ideas": ("ideas", ("rank", "story_id", "title", "angle", "gap_score")),
}


def check_schema(test, name, doc):
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text())
    if Draft202012Validator is not None:
        errors = [f"{'/'.join(map(str, e.path))}: {e.message}" for e in Draft202012Validator(schema).iter_errors(doc)]
        test.assertEqual(errors, [], f"{name} does not match its schema")
        return
    test.assertIn("generated_at", doc)
    key, fields = REQUIRED[name]
    test.assertIsInstance(doc[key], list)
    for item in doc[key]:
        for f in fields:
            test.assertIn(f, item)
