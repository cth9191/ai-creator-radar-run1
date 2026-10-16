"""Validate every data/*.json against shell/schema/<name>.schema.json.

Fails on a data file with no schema, a schema with no data file, or any schema error.
Run: python3 shell/tools/validate.py
"""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "shell" / "schema"
DATA = ROOT / "data"


def main():
    errors = []
    schema_names = {p.name.removesuffix(".schema.json") for p in SCHEMAS.glob("*.schema.json")}
    data_names = {p.stem for p in DATA.glob("*.json")}
    for name in sorted(data_names - schema_names):
        errors.append(f"data/{name}.json has no schema in shell/schema/")
    for name in sorted(schema_names - data_names):
        errors.append(f"data/{name}.json is missing (the page needs a file for every schema)")
    for name in sorted(data_names & schema_names):
        schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text())
        try:
            doc = json.loads((DATA / f"{name}.json").read_text())
        except json.JSONDecodeError as e:
            errors.append(f"data/{name}.json is not valid JSON: {e}")
            continue
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
            where = "/".join(str(p) for p in err.path) or "(root)"
            errors.append(f"data/{name}.json {where}: {err.message}")
    for e in errors:
        print("FAIL", e)
    print(f"{len(data_names)} data files checked, {len(errors)} problems")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
