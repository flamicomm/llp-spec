#!/usr/bin/env python3
"""Validate every vector file against ``schema/vector.schema.json``.

Usage:
    python3 tools/check_schema.py

Requires ``jsonschema`` (installed by CI; locally: ``pip install jsonschema``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schema" / "vector.schema.json"
VECTORS = ROOT / "vectors"


def main() -> int:
    try:
        import jsonschema
    except ImportError:
        print("FAIL  jsonschema is not installed (pip install jsonschema)")
        return 2

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    files = sorted(VECTORS.glob("*.json"))
    if not files:
        print(f"FAIL  no vector files under {VECTORS}")
        return 1

    errors = 0
    for path in files:
        document = json.loads(path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft7Validator(schema)
        problems = sorted(validator.iter_errors(document), key=lambda e: list(e.path))
        for problem in problems:
            errors += 1
            location = "/".join(str(part) for part in problem.absolute_path) or "<root>"
            print(f"FAIL  {path.name}:{location}: {problem.message}")

    if errors:
        print(f"\n{errors} schema error(s)")
        return 1

    print(f"ok    {len(files)} vector files valid against schema {schema['version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
