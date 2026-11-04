#!/usr/bin/env python3
"""Run every conformance vector in ``vectors/`` against the reference driver.

Usage:
    python3 tools/validate_vectors.py            # summary
    python3 tools/validate_vectors.py --verbose  # one line per case
    python3 tools/validate_vectors.py --strict   # also fail on an empty corpus

Exit code is 0 only when every case passes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "interoperability" / "python"))

import runner  # noqa: E402

VECTORS = ROOT / "vectors"


def load_cases() -> list[tuple[str, dict]]:
    cases: list[tuple[str, dict]] = []
    for path in sorted(VECTORS.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for case in document["cases"]:
            cases.append((path.name, case))
    return cases


def main() -> int:
    verbose = "--verbose" in sys.argv
    strict = "--strict" in sys.argv

    if not VECTORS.is_dir():
        print(f"FAIL  missing vectors directory: {VECTORS}")
        return 1

    cases = load_cases()
    if not cases:
        print("FAIL  no cases found")
        return 1
    if strict and len(cases) < 100:
        print(f"FAIL  only {len(cases)} cases; the corpus looks truncated")
        return 1

    failures = 0
    by_kind: dict[str, int] = {}
    for filename, case in cases:
        by_kind[case["kind"]] = by_kind.get(case["kind"], 0) + 1
        problems = runner.check(case)
        if problems:
            failures += 1
            print(f"FAIL  {filename}:{case['id']}")
            for problem in problems:
                print(f"        {problem}")
        elif verbose:
            print(f"ok    {filename}:{case['id']}")

    kinds = ", ".join(f"{kind} {count}" for kind, count in sorted(by_kind.items()))
    print()
    print(f"Total: {len(cases)}  Passed: {len(cases) - failures}  Failed: {failures}")
    print(f"Kinds: {kinds}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
