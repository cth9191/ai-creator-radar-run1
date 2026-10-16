"""Minimal JSON Schema checker (stdlib only) for the subset shell/schema/ uses.

CI's worker-test job has no jsonschema package, so tests check output with this.
"""
import json
import re
from datetime import datetime
from pathlib import Path

SCHEMAS = Path(__file__).resolve().parents[2] / "shell" / "schema"
TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def load(name):
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text())


def errors(doc, schema, path="$"):
    out = []
    t = schema.get("type")
    if t:
        ok = (isinstance(doc, int) and not isinstance(doc, bool)) if t == "integer" else \
             (isinstance(doc, (int, float)) and not isinstance(doc, bool)) if t == "number" else \
             isinstance(doc, TYPES[t])
        if not ok:
            return [f"{path}: expected {t}, got {type(doc).__name__}"]
    if "minimum" in schema and doc < schema["minimum"]:
        out.append(f"{path}: {doc} < minimum {schema['minimum']}")
    if "maximum" in schema and doc > schema["maximum"]:
        out.append(f"{path}: {doc} > maximum {schema['maximum']}")
    if "pattern" in schema and not re.search(schema["pattern"], doc):
        out.append(f"{path}: {doc!r} does not match {schema['pattern']}")
    if schema.get("format") == "date-time":
        try:
            datetime.fromisoformat(doc.replace("Z", "+00:00"))
        except ValueError:
            out.append(f"{path}: {doc!r} is not a date-time")
    if isinstance(doc, dict):
        for k in schema.get("required", []):
            if k not in doc:
                out.append(f"{path}: missing {k}")
        props = schema.get("properties", {})
        for k, v in doc.items():
            sub = props.get(k, schema.get("additionalProperties"))
            if isinstance(sub, dict):
                out += errors(v, sub, f"{path}.{k}")
    if isinstance(doc, list) and isinstance(schema.get("items"), dict):
        for i, v in enumerate(doc):
            out += errors(v, schema["items"], f"{path}[{i}]")
    return out
