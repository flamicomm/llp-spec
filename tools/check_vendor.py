#!/usr/bin/env python3
"""Check that the vendored reference implementation matches its pinned hash.

The reference in ``reference/llp_v4.py`` is a byte-identical copy of
``llp-protocol/scripts/llp_v4.py`` (see ``reference/VENDOR.md``). CI runs this
script so that a local edit of the vendored file is caught immediately.

Usage:
    python3 tools/check_vendor.py
    python3 tools/check_vendor.py --against ../llp-protocol/scripts/llp_v4.py
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR_MD = ROOT / "reference" / "VENDOR.md"
VENDORED = ROOT / "reference" / "llp_v4.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pinned_hash() -> str:
    text = VENDOR_MD.read_text(encoding="utf-8")
    match = re.search(r"\|\s*sha256\s*\|\s*`([0-9a-f]{64})`\s*\|", text)
    if not match:
        raise SystemExit(f"error: no pinned sha256 found in {VENDOR_MD}")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--against",
        metavar="PATH",
        help="also compare byte-for-byte against another copy of llp_v4.py",
    )
    args = parser.parse_args()

    if not VENDORED.is_file():
        print(f"FAIL  missing vendored reference: {VENDORED}")
        return 1

    actual = sha256(VENDORED)
    expected = pinned_hash()
    print(f"vendored : {VENDORED.relative_to(ROOT)}")
    print(f"sha256   : {actual}")
    print(f"pinned   : {expected}")

    status = 0
    if actual != expected:
        print("FAIL  the vendored reference does not match reference/VENDOR.md")
        print("      update the pin only as part of a reviewed specification change")
        status = 1
    else:
        print("ok    vendored reference matches its pin")

    if args.against:
        other = Path(args.against).resolve()
        if not other.is_file():
            print(f"FAIL  --against file not found: {other}")
            return 1
        other_hash = sha256(other)
        print(f"compare  : {other} ({other_hash})")
        if other_hash != actual:
            print("FAIL  the two copies differ")
            status = 1
        else:
            print("ok    copies are byte-identical")

    return status


if __name__ == "__main__":
    sys.exit(main())
