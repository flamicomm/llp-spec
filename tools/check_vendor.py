#!/usr/bin/env python3
"""Check that the vendored reference implementations match their pinned hashes.

Every file listed in the table of ``reference/VENDOR.md`` is a byte-identical
copy of ``llp-protocol/scripts/`` (see that file for the source commit). CI runs
this script so that a local edit of a vendored reference is caught immediately.

Usage:
    python3 tools/check_vendor.py
    python3 tools/check_vendor.py --against ../llp-protocol/scripts/llp_v4.py \\
                                  --against ../llp-protocol/scripts/llp_v4_rel.py
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "reference"
VENDOR_MD = REFERENCE / "VENDOR.md"

# One row per vendored file: ``| `llp_x.py` | `source/path.py` | `<sha256>` |``.
PIN_ROW = re.compile(
    r"^\|\s*`(llp_[a-z0-9_]+\.py)`\s*\|\s*`([^`]+)`\s*\|\s*`([0-9a-f]{64})`\s*\|",
    re.MULTILINE,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pins() -> dict[str, str]:
    """Return ``{vendored file name: pinned sha256}`` from ``VENDOR.md``."""
    text = VENDOR_MD.read_text(encoding="utf-8")
    found = {name: digest for name, _source, digest in PIN_ROW.findall(text)}
    if not found:
        raise SystemExit(f"error: no pinned sha256 rows found in {VENDOR_MD}")
    return found


def check_pins() -> tuple[int, dict[str, str]]:
    """Verify every pinned file against its hash. Returns status and hashes."""
    status = 0
    hashes: dict[str, str] = {}
    for name, expected in pins().items():
        path = REFERENCE / name
        print(f"vendored : {path.relative_to(ROOT)}")
        if not path.is_file():
            print(f"FAIL  missing vendored reference: {path.relative_to(ROOT)}")
            status = 1
            continue
        actual = sha256(path)
        hashes[name] = actual
        print(f"sha256   : {actual}")
        print(f"pinned   : {expected}")
        if actual != expected:
            print("FAIL  the vendored reference does not match reference/VENDOR.md")
            print("      update the pin only as part of a reviewed specification change")
            status = 1
        else:
            print("ok    vendored reference matches its pin")
    return status, hashes


def check_against(paths: list[str], hashes: dict[str, str]) -> int:
    """Compare each ``--against`` file with the vendored copy of the same name."""
    status = 0
    for raw in paths:
        other = Path(raw).resolve()
        if not other.is_file():
            print(f"FAIL  --against file not found: {other}")
            return 1
        vendored = hashes.get(other.name)
        if vendored is None:
            print(f"FAIL  --against file is not vendored here: {other.name}")
            return 1
        other_hash = sha256(other)
        print(f"compare  : {other} ({other_hash})")
        if other_hash != vendored:
            print(f"FAIL  {other.name} differs from reference/{other.name}")
            status = 1
        else:
            print(f"ok    {other.name} copies are byte-identical")
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--against",
        metavar="PATH",
        action="append",
        default=[],
        help="also compare byte-for-byte against another copy of a vendored file "
        "(repeatable; matched by file name)",
    )
    args = parser.parse_args()

    status, hashes = check_pins()
    if args.against:
        status |= check_against(args.against, hashes)

    return status


if __name__ == "__main__":
    sys.exit(main())
